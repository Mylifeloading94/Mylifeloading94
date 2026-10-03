"""
Candle-by-candle replay of the live bot over historical M1 bid/ask data.

Unlike the vectorised backtest (xau_engine), nothing here is computed ahead of
time. The loop walks M1 candles in order and does only what a live bot can:

  * builds signal-timeframe bars incrementally as candles arrive;
  * when a bucket completes, calls bot_gold.latest_signal() on the TRAILING
    window of closed bars -- the exact function the live bot calls;
  * fills at the next candle's open (ask for longs, bid for shorts);
  * manages stop / target / time exit candle by candle (stop wins a tie, gaps fill
    at the open, flat before any market closure) -- same rules as xau_engine;
  * sizes in real 0.01-lot steps from COMPOUNDING equity, charges commission and
    optional slippage, and marks equity to market every candle.

check_replay_engine.py proves it reproduces the vectorised backtest trade for trade.
"""
import numpy as np
import pandas as pd

import bot_gold as B
import xau_engine as E

CONTRACT_OZ = B.CONTRACT_OZ


def replay(m1, cfg, start=None, end=None, equity0=10_000.0, sizing="lots",
           commission_per_lot=0.0, slip=0.0, daily_loss_pct=None, dd_brake=None,
           risk_pct=None):
    """Replay `cfg` over m1[start:end]. Returns (trades_df, equity_series, info).

    sizing:  'lots' = real 0.01-lot steps (compounding);  'fractional' = exact
             risk_pct sizing with no lot rounding (used to compare with xau_engine).
    daily_loss_pct: stop opening trades for the rest of a UTC day once the day is
             down this % of start-of-day equity.
    dd_brake: (dd_pct, scale) halve (scale) the risk while drawdown >= dd_pct.
    """
    risk_pct = cfg["risk_pct"] if risk_pct is None else risk_pct
    tfm = B.TF_MIN[cfg["tf"]]
    warm_bars = B.WARMUP_BARS
    t0 = pd.Timestamp(start, tz="UTC") if start is not None else m1.index[0]
    t1 = pd.Timestamp(end, tz="UTC") if end is not None else m1.index[-1] + pd.Timedelta(minutes=1)
    # lead-in is WALL-CLOCK: weekends have no bars, so ask for 2x the bars needed
    lo = max(0, m1.index.searchsorted(t0 - pd.Timedelta(minutes=(2 * warm_bars + 50) * tfm)))
    hi = min(len(m1), m1.index.searchsorted(t1 + pd.Timedelta(minutes=cfg["hold"] + 60)))
    d = m1.iloc[lo:hi]
    tmin = E._min(d.index)
    bo, bh, bl, bc, ao, ah, al, ac = (d[c].to_numpy("float64") for c in ("bo", "bh", "bl", "bc", "ao", "ah", "al", "ac"))
    mo, mh, ml, mc = (bo + ao) / 2, (bh + ah) / 2, (bl + al) / 2, (bc + ac) / 2
    bucket = tmin // tfm
    start_min = int(E._min(pd.DatetimeIndex([t0]))[0]); end_min = int(E._min(pd.DatetimeIndex([t1]))[0])
    n = len(d)

    hist = []                                  # completed TF bars: (bucket, o, h, l, c)
    cb = None; co = chh = cll = ccl = 0.0
    pos = None
    equity, peak = equity0, equity0
    day_start_eq, cur_day, day_blocked = equity0, None, False
    last_exit = -10
    trades, skipped = [], 0
    eq_curve = np.full(n, np.nan)

    for j in range(n):
        b = bucket[j]
        # ---- a bucket just completed: this candle is the first at/after its close ----
        if cb is not None and b != cb:
            hist.append((cb, co, chh, cll, ccl))
            if len(hist) > warm_bars:
                del hist[0]
            tradable = (tmin[j] >= start_min and tmin[j] < end_min and pos is None
                        and j >= last_exit + 2 and len(hist) >= warm_bars - 100
                        and (tmin[j] - (cb + 1) * tfm) <= 15 and not day_blocked)
            if tradable:
                arr = np.array(hist)
                bars = pd.DataFrame({"open": arr[:, 1], "high": arr[:, 2], "low": arr[:, 3], "close": arr[:, 4]},
                                    index=pd.to_datetime(arr[:, 0].astype("int64") * tfm * 60, unit="s", utc=True))
                direction, risk = B.latest_signal(bars, cfg)
                if direction != 0:
                    scale, _ = B.risk_controls(equity, peak, day_start_eq, dd_brake, None)
                    rp = risk_pct * scale
                    if sizing == "fractional":
                        lots = equity * rp / 100 / (risk * CONTRACT_OZ)
                    else:
                        lots = B.size_lots(equity, rp, risk, cfg["max_lots"])
                    if lots < (B.MIN_LOT if sizing != "fractional" else 1e-9):
                        skipped += 1
                    else:
                        entry = (ao[j] if direction == 1 else bo[j]) + direction * slip / 2
                        pos = dict(j0=j, d=direction, entry=entry, risk=risk, lots=lots,
                                   stop=entry - direction * risk,
                                   target=(entry + direction * cfg["tp"] * risk) if cfg["tp"] > 0 else None,
                                   deadline=tmin[j] + cfg["hold"])
            cb, co, chh, cll, ccl = b, mo[j], mh[j], ml[j], mc[j]
        elif cb is None:
            cb, co, chh, cll, ccl = b, mo[j], mh[j], ml[j], mc[j]
        else:
            chh, cll, ccl = max(chh, mh[j]), min(cll, ml[j]), mc[j]

        # ---- day bookkeeping for the daily loss limit ----
        day = tmin[j] // 1440
        if day != cur_day:
            cur_day, day_start_eq, day_blocked = day, equity, False

        # ---- manage the open position on THIS candle (including the entry candle) ----
        if pos is not None:
            dd_, st, tg = pos["d"], pos["stop"], pos["target"]
            ex = None; why = ""
            if dd_ == 1:
                if j > pos["j0"] and bo[j] <= st: ex, why = bo[j], "stop"
                elif bl[j] <= st: ex, why = st, "stop"
                elif tg is not None and bh[j] >= tg: ex, why = tg, "target"
            else:
                if j > pos["j0"] and ao[j] >= st: ex, why = ao[j], "stop"
                elif ah[j] >= st: ex, why = st, "stop"
                elif tg is not None and al[j] <= tg: ex, why = tg, "target"
            if ex is None:
                if tmin[j] + 1 >= pos["deadline"]:
                    ex, why = (bc[j] if dd_ == 1 else ac[j]), "time"
                elif j + 1 < n and tmin[j + 1] - tmin[j] > 30:
                    ex, why = (bc[j] if dd_ == 1 else ac[j]), "closure"
            if ex is not None:
                ex = ex - dd_ * slip / 2
                pnl_px = (ex - pos["entry"]) * dd_
                usd = pnl_px * pos["lots"] * CONTRACT_OZ - commission_per_lot * pos["lots"]
                equity += usd
                peak = max(peak, equity)
                trades.append(dict(entry_time=d.index[pos["j0"]], exit_time=d.index[j], dir=dd_,
                                   entry=pos["entry"], exit=ex, lots=pos["lots"], risk=pos["risk"],
                                   r=pnl_px / pos["risk"], usd=usd, reason=why, equity=equity))
                last_exit = j
                pos = None
                _, blk = B.risk_controls(equity, peak, day_start_eq, None, daily_loss_pct)
                if blk:
                    day_blocked = True
        if pos is not None:
            unreal = ((bc[j] if pos["d"] == 1 else -ac[j]) - (pos["entry"] if pos["d"] == 1 else -pos["entry"])) \
                * pos["lots"] * CONTRACT_OZ
            eq_curve[j] = equity + unreal
        else:
            eq_curve[j] = equity

    t = pd.DataFrame(trades)
    mask = (d.index >= t0) & (d.index < t1)
    eq = pd.Series(eq_curve, index=d.index)[mask]
    return t, eq, dict(skipped_below_min_lot=skipped, final_equity=equity)


def account_stats(trades, eq, equity0=10_000.0):
    """Account-level numbers from the replay: true MTM drawdown, CAGR, profit factor in $."""
    if trades is None or len(trades) == 0:
        return {}
    w, l = trades.usd[trades.usd > 0].sum(), -trades.usd[trades.usd <= 0].sum()
    peak = eq.cummax()
    dd = ((peak - eq) / peak).max() * 100
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    final = float(eq.iloc[-1])
    daily = eq.resample("1D").last().dropna().pct_change().dropna()
    return dict(n=len(trades), wr=100 * (trades.usd > 0).mean(), pf=(w / l) if l > 0 else float("inf"),
                net_usd=float(trades.usd.sum()), final=final, ret_pct=100 * (final / equity0 - 1),
                cagr_pct=100 * ((final / equity0) ** (1 / yrs) - 1) if final > 0 and yrs > 0 else float("nan"),
                max_dd_pct=float(dd),
                sharpe=float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0,
                avg_r=float(trades.r.mean()))


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(description="Replay the bot candle by candle over a date range.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--risk", type=float, default=None, help="override risk %% per trade")
    ap.add_argument("--commission", type=float, default=0.0, help="USD per lot, round turn")
    ap.add_argument("--slip", type=float, default=0.0, help="adverse USD per fill")
    ap.add_argument("--brake", default=None, help="dd_pct,scale e.g. 5,0.5")
    ap.add_argument("--daily-loss", type=float, default=None)
    ap.add_argument("--out", default=None, help="prefix for <out>_trades.csv / <out>_equity.png")
    a = ap.parse_args()
    cfg = B.load_config(a.config)
    m1 = E.load_m1()
    brake = tuple(float(x) for x in a.brake.split(",")) if a.brake else (tuple(cfg["dd_brake"]) if cfg["dd_brake"] else None)
    t, eq, info = replay(m1, cfg, a.start, a.end, equity0=a.equity, risk_pct=a.risk,
                         commission_per_lot=a.commission, slip=a.slip, dd_brake=brake,
                         daily_loss_pct=a.daily_loss if a.daily_loss is not None else cfg["daily_loss_pct"])
    st = account_stats(t, eq, a.equity)
    print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in {**st, **info}.items()}, indent=1))
    if a.out:
        t.to_csv(f"{a.out}_trades.csv", index=False)
        try:
            import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
            d = eq.resample("1h").last().dropna()
            fig, ax = plt.subplots(2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
            ax[0].plot(d.index, d.values); ax[0].set_ylabel("equity $"); ax[0].set_title(f"{cfg.get('name','bot')} replay {a.start} -> {a.end}")
            ax[1].fill_between(d.index, -(d.cummax() - d) / d.cummax() * 100, 0, color="tab:red", alpha=.5); ax[1].set_ylabel("drawdown %")
            fig.tight_layout(); fig.savefig(f"{a.out}_equity.png", dpi=110)
            print(f"wrote {a.out}_trades.csv, {a.out}_equity.png")
        except ImportError:
            print(f"wrote {a.out}_trades.csv (matplotlib not installed; no chart)")
