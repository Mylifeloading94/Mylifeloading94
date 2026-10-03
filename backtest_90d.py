"""
90-day backtest. Everything is computed on the FULL history (indicators need warm-up), but only
trades ENTERED inside the window are counted.

  A. watchlist: every instrument on disk x the 10 fixed screen configs, H1 bid/ask bars
  B. gold bot (shipped M15 fade): vectorised AND candle-by-candle replay on real M1 bid/ask,
     with real 0.01-lot sizing and compounding equity

For each highlighted strategy it also prints a 95% bootstrap interval on mean R and a time-shift
null (where would total R land with signals that carry no information?). With a few dozen trades
those intervals are WIDE -- that is the point of showing them.
"""
import json, os, sys
import numpy as np, pandas as pd
import xau_engine as E, xau_strategies as S, screen_watchlist as W, fetch_candles as F
import replay_engine as R

HERE = os.path.dirname(os.path.abspath(__file__))
DAYS = 90
lines = []
def out(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)


def boot_ci(r, rng, n=5000):
    if len(r) < 3:
        return (float("nan"), float("nan"))
    m = np.array([rng.choice(r, len(r), replace=True).mean() for _ in range(n)])
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def fmt(s):
    pf = "inf" if not np.isfinite(s["pf"]) else f"{s['pf']:5.2f}"
    return f"n={s['n']:3d} WR {s['wr']:5.1f}% PF {pf:>5s} R {s['tot_r']:+6.1f}"


def run_cfg(h1, cfg, t0):
    b, L, Sh, Rk = W.signals(h1, cfg)
    t = W.evaluate(h1, b, L, Sh, Rk, cfg)
    return b, L, Sh, Rk, t[t.entry_time >= t0]


def main():
    rng = np.random.default_rng(1)
    syms = [s for s in list(F.INDICES) + F.FOREX + ["XAUUSD"] if W.h1_path(s)]
    end = min(W.load_h1(s).index[-1] for s in syms)
    t0 = (end - pd.Timedelta(days=DAYS)).normalize()
    out(f"90-DAY WINDOW: {t0.date()} -> {end.date()}   instruments: {', '.join(syms)}")
    out("NOT covered (data source throttled): SPX500, NAS100 and 19 FX crosses.\n")

    out("=== A. watchlist, H1 bars: profit factor / trades per (instrument x fixed config) ===")
    names = [c["name"] for c in W.CONFIGS]
    out(f"{'':8s} " + " ".join(f"{n[:11]:>11s}" for n in names))
    results = {}
    for s in syms:
        h1 = W.load_h1(s); row = []
        for cfg in W.CONFIGS:
            *_, t = run_cfg(h1, cfg, t0); st = E.stats(t); results[(s, cfg["name"])] = (st, t)
            pf = "  inf" if (st["n"] and not np.isfinite(st["pf"])) else f"{st['pf']:5.2f}"
            row.append(f"{pf}/{st['n']:<3d}  ".rjust(11) if st["n"] else "     -     ")
        out(f"{s:8s} " + " ".join(row))
    out("\n(cell = PF/trades; '-' = no trades)")

    # pooled view per config: all instruments' trades together
    out("\n=== pooled across instruments, per config (a cross-sectional read of the 90 days) ===")
    for n in names:
        ts = [results[(s, n)][1] for s in syms if len(results[(s, n)][1])]
        if not ts:
            continue
        t = pd.concat(ts); st = E.stats(t); lo, hi = boot_ci(t.r.to_numpy(), rng)
        out(f"{n:16s} {fmt(st)}  mean R {st['exp_r']:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")

    out("\n=== highlighted: USDJPY momentum (the full-history candidate) ===")
    for nm, p in (("mom rsi75 h8 (pre-registered)", dict(bo_len=20, rsi_thr=75.)), ("mom rsi80 h8 (post-hoc neighbour)", dict(bo_len=20, rsi_thr=80.))):
        cfg = dict(name=nm, fam="momentum", hold=480, p=dict(p, sl_atr=3., side="both"))
        h1 = W.load_h1("USDJPY"); b, L, Sh, Rk, t = run_cfg(h1, cfg, t0); st = E.stats(t); lo, hi = boot_ci(t.r.to_numpy(), rng)
        null = []
        for k in rng.integers(300, len(L) - 300, 300):
            tt = W.evaluate(h1, b, np.roll(L, int(k)), np.roll(Sh, int(k)), Rk, cfg); tt = tt[tt.entry_time >= t0]
            null.append(tt.r.sum() if len(tt) else 0.0)
        p_ = (1 + sum(x >= t.r.sum() for x in null)) / 301
        out(f"{nm:34s} {fmt(st)}  mean R {st['exp_r']:+.3f} CI [{lo:+.3f},{hi:+.3f}]  | null total R mean {np.mean(null):+.1f} (95th {np.percentile(null,95):+.1f}), p={p_:.2f}")
        if len(t):
            for _, r in t.iterrows():
                out(f"      {r.entry_time:%m-%d %H:%M} {'LONG ' if r.dir==1 else 'SHORT'} R {r.r:+.2f}  ({E.REASONS[int(r.reason)]})")
    json.dump({f"{k[0]}|{k[1]}": v[0] for k, v in results.items()}, open(os.path.join(HERE, "results", "backtest_90d_watchlist.json"), "w"), indent=1, default=float)

    out("\n=== B. gold bot (shipped M15 fade, long-only, 4h hold) on real M1 bid/ask ===")
    cfg = json.load(open(os.path.join(HERE, "configs", "gold_intraday.json")))
    m1 = E.load_m1()
    gend = m1.index[-1]; gt0 = (gend - pd.Timedelta(days=DAYS)).normalize()
    b = E.to_tf(m1, cfg["tf"]); L, Sh, Rk = S.fade(b, **cfg["p"])
    tv = E.run(m1, b, cfg["tf"], L, Sh, Rk, hold_min=cfg["hold"], tp_mult=cfg["tp"]); tv = tv[tv.entry_time >= gt0]
    st = E.stats(tv); lo, hi = boot_ci(tv.r.to_numpy(), rng)
    out(f"window {gt0.date()} -> {gend.date()}  vectorised: {fmt(st)}  mean R {st['exp_r']:+.3f} CI [{lo:+.3f},{hi:+.3f}]")
    for rp in (0.5, 1.0):
        t, eq, info = R.replay(m1, cfg, str(gt0.date()), str((gend + pd.Timedelta(days=1)).date()), risk_pct=rp)
        a = R.account_stats(t, eq)
        out(f"  replay candle-by-candle, $10k, real lots, risk {rp}%: n={a.get('n',0)} WR {a.get('wr',0):.1f}% PF($) {a.get('pf',0):.2f} net ${a.get('net_usd',0):+.0f} ({a.get('ret_pct',0):+.2f}%) maxDD {a.get('max_dd_pct',0):.2f}% skipped(min-lot) {info['skipped_below_min_lot']}")
        if rp == 0.5 and len(t):
            for _, r in t.iterrows():
                out(f"      {r.entry_time:%m-%d %H:%M} {'LONG' if r.dir==1 else 'SHORT'} {r.lots:.2f}lot entry {r.entry:8.2f} exit {r.exit:8.2f} {r.reason:7s} R {r.r:+.2f}  ${r.usd:+7.0f}")
    open(os.path.join(HERE, "results", "backtest_90d.txt"), "w").write("\n".join(lines))


if __name__ == "__main__":
    main()
