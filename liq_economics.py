"""Economics of the strategy as written: break-even win rate, spread cost, and gross-of-spread results.
The strategy buys at the ASK and sells at the BID, so it pays ONE spread per round trip (ask-bid at entry)."""
import numpy as np, pandas as pd, xau_engine as E, liq_scalp as LS, liq_exec as X
m1 = E.load_m1(); b15 = E.to_tf(m1, "15min"); b1h = E.to_tf(m1, "1h"); sp = (m1.ac - m1.bc)
print("economics of the strategy as written (aligned, nearest 15M swing, no RR filter, full history)")
for e in ("E1", "E2", "E3"):
    t = X.run(m1, b15, LS.generate(b15, b1h, entry=e, aligned=True), risk_rules=False)
    s = E.stats(t); cost = sp.reindex(t.entry_time).to_numpy() / t.risk.to_numpy()
    be = -s["avg_loss"] / (s["avg_win"] - s["avg_loss"]) * 100
    print(f"  {e}: n={s['n']:4d} | win rate {s['wr']:4.1f}% vs BREAK-EVEN {be:4.1f}% (avg win {s['avg_win']:+.2f}R, avg loss {s['avg_loss']:+.2f}R) | "
          f"spread {np.nanmean(cost):.3f}R per round trip = {100*np.nanmean(cost)/s['avg_win']:.0f}% of an average win | median stop ${np.median(t.risk):.1f}")
    for lo, hi in ((0, 0.5), (0.5, 1.0), (1.0, 99)):
        m = t[(t.rr_plan >= lo) & (t.rr_plan < hi)]
        if len(m) >= 15:
            x = E.stats(m); print(f"       planned RR {lo:.1f}-{hi:.1f}: n={x['n']:3d} WR {x['wr']:4.1f}% PF {x['pf']:4.2f} meanR {x['exp_r']:+.3f}")
    if e in ("E1", "E2"):
        for tag, r in (("net of spread (as backtested)", t.r.to_numpy()), ("ZERO-SPREAD world (spread added back once)", t.r.to_numpy() + cost)):
            w, l = r[r > 0].sum(), -r[r <= 0].sum(); print(f"       {tag:44s}: PF {w/l:4.2f}  mean R {r.mean():+.3f}")
