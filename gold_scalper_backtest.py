"""
Tick-accurate backtester for the Gold Sniper Scalper (XAUUSD).

Honesty rules enforced here:
  * Signals are computed ONLY from CLOSED bars. The decision on bar i uses data
    up to and including bar i's close; the fill happens at the first tick AFTER
    that close (= the next bar's open). Nothing peeks forward. This is what
    makes the Pine port non-repainting.
  * Exits are resolved on the REAL TICK STREAM, not on bar OHLC. When one bar
    contains both the stop and the target, the tick sequence decides which came
    first. Bar-based tests get this wrong and invent win rate.
  * Spread is paid from the real bid/ask quotes: longs enter at ask and exit at
    bid, shorts the reverse. Roughly 0.06-0.11R per round turn on gold.

Two setup families are supported so they can be compared on equal terms:
  'breakout' - trend continuation: trade the break of an N-bar range in the
               direction of the EMA stack. (This is the one with a measurable
               edge in the 90-day study; see EDGE_STUDY notes in the report.)
  'sweep'    - liquidity sweep + rejection, i.e. mean reversion. Kept because
               it is the popular "smart money" scalp, and because measuring it
               honestly is how we learned it is on the WRONG side for gold.

Usage:
    python3 gold_scalper_backtest.py
"""
import argparse, json, os
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

ATR_MED_LEN = 500   # bars used for the volatility-regime baseline (mirrored in Pine)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    setup: str = "breakout"       # 'breakout' | 'sweep'
    tf: str = "M5"

    # trend definition
    ema_fast: int = 50
    ema_slow: int = 200
    require_stack: bool = True    # demand ema_fast on the correct side of ema_slow
    htf_ema: int = 0              # >0: extra slow EMA on the SAME series, used as
                                  # a higher-timeframe proxy. No request.security().

    # trigger
    bo_len: int = 20              # breakout: range length that must be broken
    sweep_lookback: int = 12      # sweep: extreme that must be taken out
    close_pos: float = 0.6        # sweep: rejection close quality

    # momentum band (breakout) / extreme (sweep)
    rsi_len: int = 14
    rsi_lookback: int = 3
    rsi_band_lo: float = 50.0
    rsi_band_hi: float = 80.0
    rsi_long: float = 35.0
    rsi_short: float = 65.0

    # quality filters
    max_ext_atr: float = 99.0     # reject if close is further than this many ATRs
                                  # from the fast EMA (anti-chase)
    min_body: float = 0.0         # trigger candle body as a fraction of its range

    # volatility gate
    atr_len: int = 14
    atr_min_mult: float = 0.5
    atr_max_mult: float = 2.2

    # entry
    entry_mode: str = "market"    # 'market' | 'retest'
    retest_off_atr: float = 0.0   # limit sits this many ATRs beyond the broken
                                  # level (negative demands a deeper pullback)
    retest_bars: int = 6          # cancel the resting order after this many bars

    # risk model
    stop_mode: str = "atr"        # 'atr' (k*ATR from entry) | 'swing' (structure)
    sl_atr: float = 1.8
    swing_len: int = 12
    swing_buf_atr: float = 0.25
    tp_r: float = 1.5
    be_at_r: float = 0.0

    # exit
    exit_mode: str = "fixed"      # 'fixed' | 'trail' | 'trail_bar'
                                  # 'trail'     ratchets on every TICK.
                                  # 'trail_bar' ratchets once per BAR CLOSE,
                                  #   which is what Pine's strategy.exit can
                                  #   actually do. Use trail_bar for anything
                                  #   the .pine file has to reproduce.
    trail_atr: float = 2.0
    trail_start_r: float = 1.0

    # execution
    sess_start: int = 12
    sess_end: int = 20
    max_bars_in_trade: int = 72
    cooldown_bars: int = 3
    side: str = "both"            # 'both' | 'long' | 'short'


# ---------------------------------------------------------------------------
# Indicators (all causal / closed-bar only)
# ---------------------------------------------------------------------------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rma(s, n):
    """Wilder smoothing - matches Pine ta.rma / ta.atr / ta.rsi."""
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def atr(df, n):
    pc = df.close.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()],
                   axis=1).max(axis=1)
    return rma(tr, n)


def rsi(s, n):
    d = s.diff()
    return 100 - 100 / (1 + rma(d.clip(lower=0), n) / rma(-d.clip(upper=0), n))


def build_indicators(df, c: Config):
    x = df.copy()
    x["ema_f"] = ema(x.close, c.ema_fast)
    x["ema_s"] = ema(x.close, c.ema_slow)
    x["ema_h"] = ema(x.close, c.htf_ema) if c.htf_ema > 0 else np.nan
    x["atr"] = atr(x, c.atr_len)
    x["rsi"] = rsi(x.close, c.rsi_len)
    # Rolling median ATR = volatility-regime baseline. Rolling (not expanding)
    # so it maps 1:1 onto Pine's ta.median(atr, ATR_MED_LEN).
    x["atr_med"] = x["atr"].rolling(ATR_MED_LEN).median()
    # Prior extremes EXCLUDE the current bar -> .shift(1). This offset is what
    # guarantees the level cannot be redrawn by the bar we are judging.
    x["bo_hi"] = x.high.rolling(c.bo_len).max().shift(1)
    x["bo_lo"] = x.low.rolling(c.bo_len).min().shift(1)
    x["sw_hi"] = x.high.rolling(c.sweep_lookback).max().shift(1)
    x["sw_lo"] = x.low.rolling(c.sweep_lookback).min().shift(1)
    x["sg_hi"] = x.high.rolling(c.swing_len).max().shift(1)
    x["sg_lo"] = x.low.rolling(c.swing_len).min().shift(1)
    x["rsi_lo"] = x.rsi.rolling(c.rsi_lookback).min()
    x["rsi_hi"] = x.rsi.rolling(c.rsi_lookback).max()
    x["hour"] = x.index.hour
    return x


# ---------------------------------------------------------------------------
# Signals - vectorised but strictly causal
# ---------------------------------------------------------------------------
def signals(x, c: Config):
    """int8 array: +1 long, -1 short, 0 none."""
    close, high, low = x.close.to_numpy(), x.high.to_numpy(), x.low.to_numpy()
    a, med = x.atr.to_numpy(), x.atr_med.to_numpy()
    ef, es = x.ema_f.to_numpy(), x.ema_s.to_numpy()
    r_ = x.rsi.to_numpy()
    hour = x.hour.to_numpy()

    ok = (np.isfinite(a) & np.isfinite(es) & np.isfinite(ef) & np.isfinite(med)
          & np.isfinite(r_)
          & (hour >= c.sess_start) & (hour < c.sess_end)
          & (a >= c.atr_min_mult * med) & (a <= c.atr_max_mult * med))

    up = close > es
    dn = close < es
    if c.require_stack:
        up = up & (ef > es)
        dn = dn & (ef < es)
    if c.htf_ema > 0:
        eh = x.ema_h.to_numpy()
        ok = ok & np.isfinite(eh)
        up = up & (close > eh)
        dn = dn & (close < eh)
    # anti-chase: refuse to buy a market already stretched from its fast EMA
    if c.max_ext_atr < 90:
        ok = ok & (np.abs(close - ef) / a <= c.max_ext_atr)
    if c.min_body > 0:
        op = x.open.to_numpy()
        rb = high - low
        body = np.abs(close - op) / np.where(rb <= 0, np.nan, rb)
        ok = ok & np.isfinite(body) & (body >= c.min_body)

    if c.setup == "breakout":
        bh, bl = x.bo_hi.to_numpy(), x.bo_lo.to_numpy()
        ok = ok & np.isfinite(bh) & np.isfinite(bl)
        # Continuation: close BREAKS the prior N-bar range in the trend
        # direction, with momentum present but not yet exhausted.
        long_ = (ok & up & (close > bh)
                 & (r_ >= c.rsi_band_lo) & (r_ <= c.rsi_band_hi))
        short_ = (ok & dn & (close < bl)
                  & (r_ <= 100 - c.rsi_band_lo) & (r_ >= 100 - c.rsi_band_hi))
    else:
        sh, sl_ = x.sw_hi.to_numpy(), x.sw_lo.to_numpy()
        rlo, rhi = x.rsi_lo.to_numpy(), x.rsi_hi.to_numpy()
        rng = high - low
        rng = np.where(rng <= 0, np.nan, rng)
        ok = ok & np.isfinite(sh) & np.isfinite(sl_) & np.isfinite(rng) \
             & np.isfinite(rlo) & np.isfinite(rhi)
        long_ = (ok & up & (low < sl_) & (close > sl_)
                 & ((close - low) / rng >= c.close_pos) & (rlo <= c.rsi_long))
        short_ = (ok & dn & (high > sh) & (close < sh)
                  & ((high - close) / rng >= c.close_pos) & (rhi >= c.rsi_short))

    if c.side == "long":
        short_ = np.zeros(len(close), bool)
    elif c.side == "short":
        long_ = np.zeros(len(close), bool)
    return np.where(long_, 1, np.where(short_, -1, 0)).astype(np.int8)


# ---------------------------------------------------------------------------
# Tick-accurate simulation
# ---------------------------------------------------------------------------
def simulate(bars, ticks, c: Config):
    x = build_indicators(bars, c)
    sig = signals(x, c)
    cand = np.flatnonzero(sig)

    tick_ts = ticks.index.values.astype("datetime64[ns]")
    bid, ask = ticks.bid.to_numpy(), ticks.ask.to_numpy()
    idx = x.index.values.astype("datetime64[ns]")
    atrs = x.atr.to_numpy()
    sg_hi, sg_lo = x.sg_hi.to_numpy(), x.sg_lo.to_numpy()
    bo_hi, bo_lo = x.bo_hi.to_numpy(), x.bo_lo.to_numpy()
    highs_a, lows_a = x.high.to_numpy(), x.low.to_numpy()
    bar_sec = {"M1": 60, "M5": 300, "M15": 900}[c.tf]
    bar_ns = np.timedelta64(bar_sec, "s")

    trades = []
    i_cool = -10**9
    for i in cand:
        if i <= i_cool:
            continue
        d = int(sig[i])

        close_ts = idx[i] + bar_ns
        j0 = int(np.searchsorted(tick_ts, close_ts, side="left"))
        if j0 >= len(tick_ts):
            break
        if (tick_ts[j0] - close_ts) > np.timedelta64(15, "m"):
            continue                                   # market shut; no fill

        a_i = atrs[i]
        if not np.isfinite(a_i) or a_i <= 0:
            continue
        if c.entry_mode == "retest":
            # Broken resistance becomes support: rest the order back AT the
            # level and only trade if price returns to it.
            lvl = bo_hi[i] if d == 1 else bo_lo[i]
            if not np.isfinite(lvl):
                continue
            limit = (lvl + c.retest_off_atr * a_i) if d == 1 \
                else (lvl - c.retest_off_atr * a_i)
            exp_ts = idx[i] + bar_ns * (c.retest_bars + 1)
            j_exp = min(int(np.searchsorted(tick_ts, exp_ts, side="left")),
                        len(tick_ts))
            if j_exp <= j0:
                continue
            w = (ask if d == 1 else bid)[j0:j_exp]
            touch = (w <= limit) if d == 1 else (w >= limit)
            if not touch.any():
                continue                 # never came back; no trade taken
            j_fill = j0 + int(np.argmax(touch))
            entry = float(w[int(np.argmax(touch))])
        else:
            j_fill = j0
            entry = float(ask[j0] if d == 1 else bid[j0])

        if c.stop_mode == "swing":
            lvl = sg_lo[i] if d == 1 else sg_hi[i]
            if not np.isfinite(lvl):
                continue
            stop = (lvl - c.swing_buf_atr * atrs[i]) if d == 1 \
                else (lvl + c.swing_buf_atr * atrs[i])
        else:
            stop = (entry - c.sl_atr * atrs[i]) if d == 1 \
                else (entry + c.sl_atr * atrs[i])

        risk = (entry - stop) if d == 1 else (stop - entry)
        if not np.isfinite(risk) or risk <= 0:
            continue
        target = (entry + c.tp_r * risk) if d == 1 else (entry - c.tp_r * risk)

        deadline = idx[i] + bar_ns * (c.max_bars_in_trade + 1)
        j_end = min(int(np.searchsorted(tick_ts, deadline, side="left")), len(tick_ts))
        if j_end <= j_fill + 1:
            continue

        if c.exit_mode == "trail_bar":
            # Walk bar by bar. Within each bar the stop is frozen at the value
            # set by the PREVIOUS bar's close, and ticks decide whether it is
            # hit. This is the only trail a non-repainting Pine strategy can
            # honestly claim, so it is what we measure.
            exch = (bid if d == 1 else ask)
            cur = stop
            run = entry
            b_last = min(i + c.max_bars_in_trade, len(idx) - 1)
            exit_px = exit_ts = None
            reason = "timeout"
            jb = j_fill + 1
            for b in range(i + 1, b_last + 1):
                b_close_ts = idx[b] + bar_ns
                jb_end = min(int(np.searchsorted(tick_ts, b_close_ts, side="left")),
                             j_end)
                if jb_end > jb:
                    w = exch[jb:jb_end]
                    h_sl = (w <= cur) if d == 1 else (w >= cur)
                    h_tp = (w >= target) if d == 1 else (w <= target)
                    k_sl = int(np.argmax(h_sl)) if h_sl.any() else 10**9
                    k_tp = int(np.argmax(h_tp)) if h_tp.any() else 10**9
                    if min(k_sl, k_tp) < 10**9:
                        if k_sl <= k_tp:
                            kk = jb + k_sl
                            exit_px, reason = float(w[k_sl]), "trail"
                        else:
                            kk = jb + k_tp
                            exit_px, reason = float(w[k_tp]), "tp"
                        exit_ts = tick_ts[kk]
                        break
                jb = jb_end
                # bar has closed: ratchet on its extreme
                run = max(run, highs_a[b]) if d == 1 else min(run, lows_a[b])
                reached = (run >= entry + c.trail_start_r * risk) if d == 1 \
                    else (run <= entry - c.trail_start_r * risk)
                if reached:
                    nt = (run - c.trail_atr * a_i) if d == 1 else (run + c.trail_atr * a_i)
                    cur = max(cur, nt) if d == 1 else min(cur, nt)
                if jb >= j_end:
                    break
            if exit_px is None:
                kk = max(min(jb, j_end) - 1, j_fill + 1)
                exit_px = float(exch[kk])
                exit_ts = tick_ts[kk]
            pnl = (exit_px - entry) if d == 1 else (entry - exit_px)
            trades.append(dict(dir="long" if d == 1 else "short",
                               signal_time=str(idx[i]),
                               entry_time=str(tick_ts[j_fill]),
                               exit_time=str(exit_ts), entry=entry, stop=stop,
                               target=target, exit=exit_px, risk=risk,
                               r=pnl / risk, usd=pnl, reason=reason))
            exit_bar = int(np.searchsorted(idx, exit_ts, side="right")) - 1
            i_cool = max(int(i), exit_bar) + c.cooldown_bars
            continue

        px = (bid if d == 1 else ask)[j_fill + 1:j_end]   # exits cross the spread
        if c.exit_mode == "trail":
            # Ratcheting ATR trail, armed once the trade is trail_start_r in
            # front. run is monotone, so the effective stop never loosens.
            run = np.maximum.accumulate(px) if d == 1 else np.minimum.accumulate(px)
            armed = (run >= entry + c.trail_start_r * risk) if d == 1 \
                else (run <= entry - c.trail_start_r * risk)
            tr = (run - c.trail_atr * a_i) if d == 1 else (run + c.trail_atr * a_i)
            eff = np.where(armed,
                           np.maximum(stop, tr) if d == 1 else np.minimum(stop, tr),
                           stop)
            hit_sl = (px <= eff) if d == 1 else (px >= eff)
        else:
            hit_sl = (px <= stop) if d == 1 else (px >= stop)
        hit_tp = (px >= target) if d == 1 else (px <= target)
        i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10**9
        i_tp = int(np.argmax(hit_tp)) if hit_tp.any() else 10**9

        be_used = False
        if c.be_at_r > 0 and c.exit_mode == "fixed":
            trg = (entry + c.be_at_r * risk) if d == 1 else (entry - c.be_at_r * risk)
            armed = (px >= trg) if d == 1 else (px <= trg)
            if armed.any():
                i_arm = int(np.argmax(armed))
                if i_arm < min(i_sl, i_tp):
                    tail = px[i_arm + 1:]
                    hb = (tail <= entry) if d == 1 else (tail >= entry)
                    if hb.any():
                        i_be = i_arm + 1 + int(np.argmax(hb))
                        if i_be < i_tp:
                            i_sl, be_used = i_be, True

        if i_sl == 10**9 and i_tp == 10**9:
            k = j_end - 1
            exit_px, reason = (bid[k] if d == 1 else ask[k]), "timeout"
        elif i_sl <= i_tp:
            k = j_fill + 1 + i_sl
            exit_px = float(px[i_sl])
            reason = "be" if be_used else ("trail" if c.exit_mode == "trail" else "sl")
        else:
            k = j_fill + 1 + i_tp
            exit_px, reason = float(px[i_tp]), "tp"
        exit_ts = tick_ts[k]

        pnl = (exit_px - entry) if d == 1 else (entry - exit_px)
        trades.append(dict(dir="long" if d == 1 else "short",
                           signal_time=str(idx[i]),
                           entry_time=str(tick_ts[j_fill]), exit_time=str(exit_ts),
                           entry=entry, stop=stop, target=target, exit=exit_px,
                           risk=risk, r=pnl / risk, usd=pnl, reason=reason))

        exit_bar = int(np.searchsorted(idx, exit_ts, side="right")) - 1
        i_cool = max(int(i), exit_bar) + c.cooldown_bars

    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def stats(t):
    if t is None or t.empty:
        return dict(trades=0, win_rate=0.0, expectancy_r=0.0, profit_factor=0.0,
                    total_r=0.0, max_dd_r=0.0, avg_win_r=0.0, avg_loss_r=0.0,
                    usd_per_1lot=0.0, tp=0, sl=0, be=0, trail=0, timeout=0)
    wins, losses = t[t.r > 0], t[t.r <= 0]
    gp, gl = wins.r.sum(), -losses.r.sum()
    eq = t.r.cumsum()
    return dict(
        trades=int(len(t)),
        win_rate=round(100.0 * len(wins) / len(t), 2),
        expectancy_r=round(float(t.r.mean()), 4),
        profit_factor=round(float(gp / gl), 3) if gl > 0 else float("inf"),
        total_r=round(float(t.r.sum()), 2),
        max_dd_r=round(float((eq.cummax() - eq).max()), 2),
        avg_win_r=round(float(wins.r.mean()), 3) if len(wins) else 0.0,
        avg_loss_r=round(float(losses.r.mean()), 3) if len(losses) else 0.0,
        usd_per_1lot=round(float(t.usd.sum() * 100), 2),
        tp=int((t.reason == "tp").sum()), sl=int((t.reason == "sl").sum()),
        be=int((t.reason == "be").sum()), trail=int((t.reason == "trail").sum()),
        timeout=int((t.reason == "timeout").sum()),
    )


def load(tf="M5"):
    bars = pd.read_csv(os.path.join(DATA, f"XAUUSD_{tf}.csv"),
                       parse_dates=["time"], index_col="time")
    ticks = pd.read_parquet(os.path.join(DATA, "XAUUSD_ticks.parquet"))
    return bars, ticks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="M5")
    a = ap.parse_args()
    bars, ticks = load(a.tf)
    print(f"bars {len(bars):,}  ticks {len(ticks):,}  "
          f"{bars.index[0]} -> {bars.index[-1]}\n")
    for setup in ("breakout", "sweep"):
        c = Config(setup=setup, tf=a.tf)
        print(f"--- {setup} ---")
        print(json.dumps(stats(simulate(bars, ticks, c)), indent=2))


if __name__ == "__main__":
    main()
