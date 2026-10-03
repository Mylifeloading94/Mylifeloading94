"""
Deep backtest of the screened top performers (H1 bid/ask bars, 2019 -> today).

For each instrument, using the config that screen_watchlist.py chose ON TRAIN:
  * per-year table, long/short split
  * risk-sized equity (0.5% and 1% per trade): return and max drawdown
  * cost stress: spread x1.5 and x2
  * PERMUTATION TEST: 400 time-shifted copies of the signals (same frequency, no
    information) -> p-value for the observed total R. Reported next to a
    multiple-testing threshold, because the instruments were picked as winners
    out of 31 and the best of many will always look good.
Then a combined basket of the qualifiers (equal risk per trade, shared equity).

Usage: python3 deep_watchlist.py [SYM,SYM,...]   (default: qualifiers in results/screen_watchlist.json)
"""
import json, os, sys
import numpy as np, pandas as pd
import xau_engine as E
import screen_watchlist as W

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = {c["name"]: c for c in W.CONFIGS}
N_PERM = 400


def trades_for(sym, cfg):
    h1 = W.load_h1(sym)
    b, L, Sh, R = W.signals(h1, cfg)
    t = W.evaluate(h1, b, L, Sh, R, cfg)
    spr = (h1.ao - h1.bo).reindex(t.entry_time).to_numpy()
    t["spr"] = spr
    return h1, b, L, Sh, R, t


def perm_p(h1, b, L, Sh, R, cfg, observed, rng):
    n = len(L); null = np.empty(N_PERM)
    for k in range(N_PERM):
        s = int(rng.integers(300, n - 300))
        t = W.evaluate(h1, b, np.roll(L, s), np.roll(Sh, s), R, cfg)
        null[k] = t.r.sum() if len(t) else 0.0
    return (1 + (null >= observed).sum()) / (1 + N_PERM), float(null.mean()), float(np.percentile(null, 95))


def stress(t, mult):
    """Extra cost = (mult-1) x the entry spread, in R."""
    r = t.r - (mult - 1.0) * t.spr / t.risk
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    return (w / l if l > 0 else float("inf")), float(r.sum())


def report(sym, cfgname, rng, n_tested):
    cfg = CFG[cfgname]
    h1, b, L, Sh, R, t = trades_for(sym, cfg)
    tr, va, te, al = W.split_stats(t)
    p, nm, n95 = perm_p(h1, b, L, Sh, R, cfg, t.r.sum(), rng)
    print(f"\n=== {sym}  [{cfgname}]  both-sided, stop 3 ATR, {cfg['hold']//60}h time exit ===")
    print(f"  ALL   n={al['n']:4d} WR {al['wr']:4.1f}%  PF {al['pf']:4.2f}  exp {al['exp_r']:+.3f}R  total {al['tot_r']:+6.1f}R  t={al['t']:+.2f}  maxDD {al['dd_r']:.1f}R")
    print(f"  train n={tr['n']:4d} PF {tr['pf']:4.2f} | valid n={va['n']:4d} PF {va['pf']:4.2f} | TEST n={te['n']:4d} WR {te['wr']:4.1f}% PF {te['pf']:4.2f} R {te['tot_r']:+.1f}")
    for rp in (0.5, 1.0):
        s = E.stats(t, rp); print(f"  risk {rp}%/trade: return {s['ret_pct']:+6.1f}%  maxDD {s['dd_pct']:.1f}%")
    ys = E.by_year(t)
    print("  by year PF:", {y: round(s['pf'], 2) for y, s in ys.items()})
    for d_, nm_ in ((1, "long"), (-1, "short")):
        s = E.stats(t[t.dir == d_]); print(f"  {nm_:5s} n={s['n']:4d} WR {s['wr']:4.1f}% PF {s['pf']:4.2f} R {s['tot_r']:+6.1f}")
    for m in (1.5, 2.0):
        pf, tot = stress(t, m); print(f"  cost x{m}: PF {pf:4.2f}  total {tot:+6.1f}R")
    thr = 0.05 / n_tested
    print(f"  permutation test: observed {t.r.sum():+.1f}R vs null mean {nm:+.1f}R (95th pct {n95:+.1f}R)  p = {p:.3f}"
          f"   -> {'SURVIVES' if p <= thr else 'does NOT survive'} Bonferroni for {n_tested} instruments (needs p <= {thr:.4f})")
    return dict(sym=sym, cfg=cfgname, all=al, tr=tr, va=va, te=te, p=p, trades=t)


def basket(results, risk_pct=0.5):
    t = pd.concat([r["trades"].assign(sym=r["sym"]) for r in results]).sort_values("exit_time").reset_index(drop=True)
    s = E.stats(t, risk_pct)
    eq = pd.Series(np.cumprod(1 + risk_pct / 100 * t.r.to_numpy()), index=t.exit_time)
    d = eq.resample("1D").last().ffill().pct_change().dropna()
    sharpe = d.mean() / d.std() * np.sqrt(252) if d.std() > 0 else 0
    print(f"\n=== BASKET of {len(results)}: {', '.join(r['sym'] for r in results)} (risk {risk_pct}% per trade, shared equity) ===")
    print(f"  n={s['n']} WR {s['wr']:.1f}% PF {s['pf']:.2f} exp {s['exp_r']:+.3f}R t={s['t']:+.2f} | return {s['ret_pct']:+.1f}% maxDD {s['dd_pct']:.1f}% Sharpe {sharpe:.2f}")
    print("  by year PF:", {y: round(x['pf'], 2) for y, x in E.by_year(t).items()})


if __name__ == "__main__":
    scr = json.load(open(os.path.join(HERE, "results", "screen_watchlist.json")))["real"]
    n_tested = len(scr)
    pick = {r["sym"]: r["best"]["cfg"] for r in scr if r["best"]}
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else [r["sym"] for r in scr if r["qualifies"]]
    rng = np.random.default_rng(7)
    res = [report(s, pick[s], rng, n_tested) for s in syms]
    if len(res) > 1:
        basket(res)
