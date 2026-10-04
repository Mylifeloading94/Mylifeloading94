"""
Pre-registered grid for the Brad-Gold liquidity-scalping strategy on gold (real M1 bid/ask, 2019 -> today).

24 configs: entry model {E1 aggressive, E2 Brad+confirm candle, E3 conservative} x target {nearest 15M swing,
1H swing} x minimum reward:risk {none, 1.0} x timeframe rule {1H+15M aligned (the spec), 15M trend only (ablation)}.
Spec's risk rules on: max 3 trades/day, stop for the day at -2R. Max hold 6h.
Ranked on train (2019-22); qualifies only if PF > 1.05 on train AND validation (2023-24); test only for qualifiers.
"""
import itertools, json, os
import numpy as np, pandas as pd
import xau_engine as E, liq_scalp as LS, liq_exec as X

HERE = os.path.dirname(os.path.abspath(__file__))
TR = pd.Timestamp("2023-01-01", tz="UTC"); VA = pd.Timestamp("2025-01-01", tz="UTC")
f = lambda s: f"n={s['n']:4d} WR {s['wr']:4.1f} PF {('inf' if not np.isfinite(s['pf']) else format(s['pf'], '4.2f')):>4s} R {s['tot_r']:+6.1f}"


def boot(r, rng, n=4000):
    if len(r) < 5: return (np.nan, np.nan)
    m = [rng.choice(r, len(r), replace=True).mean() for _ in range(n)]
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    m1 = E.load_m1(); b15 = E.to_tf(m1, "15min"); b1h = E.to_tf(m1, "1h"); rng = np.random.default_rng(0)
    res = []
    for entry, tp, mrr, al in itertools.product(("E1", "E2", "E3"), ("swing15", "swing1h"), (0.0, 1.0), (True, False)):
        sg = LS.generate(b15, b1h, entry=entry, aligned=al, tp_mode=tp, min_rr=mrr)
        t = X.run(m1, b15, sg)
        sp = lambda x: E.stats(x)
        res.append(dict(entry=entry, tp=tp, min_rr=mrr, aligned=al, signals=len(sg), trades=t,
                        tr=sp(t[t.entry_time < TR]), va=sp(t[(t.entry_time >= TR) & (t.entry_time < VA)]),
                        te=sp(t[t.entry_time >= VA]), al=sp(t)))
    lab = lambda r: f"{r['entry']} {r['tp']:7s} minRR{r['min_rr']:.0f} {'1H+15M' if r['aligned'] else '15M   '}"
    print(f"{'config':32s} | {'train 2019-22':^28s} | {'valid 2023-24':^28s} | sigs")
    for r in sorted(res, key=lambda r: -r["tr"]["pf"] if r["tr"]["n"] >= 30 else 0):
        print(f"{lab(r):32s} | {f(r['tr']):28s} | {f(r['va']):28s} | {r['signals']}")
    q = [r for r in res if r["tr"]["n"] >= 40 and r["va"]["n"] >= 20 and r["tr"]["pf"] > 1.05 and r["va"]["pf"] > 1.05]
    print(f"\nQUALIFIERS (PF > 1.05 on train AND validation, n>=40/20): {len(q)} of {len(res)}")
    for r in q:
        lo, hi = boot(r["trades"].r.to_numpy(), rng)
        print(f"  {lab(r)} | train {f(r['tr'])} | valid {f(r['va'])} | TEST {f(r['te'])} | all-period mean R CI [{lo:+.3f},{hi:+.3f}]")
    print("\n=== the strategy AS WRITTEN (1H+15M aligned, nearest 15M swing, no RR filter), full history, by entry model ===")
    for r in res:
        if r["aligned"] and r["tp"] == "swing15" and r["min_rr"] == 0.0:
            t = r["trades"]; s = r["al"]; lo, hi = boot(t.r.to_numpy(), rng)
            print(f"  {r['entry']}: {f(s)} | avg win {s['avg_win']:+.2f}R avg loss {s['avg_loss']:+.2f}R | median planned RR {t.rr_plan.median():.2f} | mean R {s['exp_r']:+.3f} CI [{lo:+.3f},{hi:+.3f}] t={s['t']:+.2f}")
            print(f"       by year PF: { {y: round(x['pf'],2) for y,x in E.by_year(t).items()} }")
    print("\n=== does the '1H and 15M must agree' rule help? (same entry/target/RR, aligned vs 15M-only), full history ===")
    for entry, tp, mrr in itertools.product(("E1", "E2", "E3"), ("swing15", "swing1h"), (0.0, 1.0)):
        a = next(r for r in res if (r["entry"], r["tp"], r["min_rr"], r["aligned"]) == (entry, tp, mrr, True))
        u = next(r for r in res if (r["entry"], r["tp"], r["min_rr"], r["aligned"]) == (entry, tp, mrr, False))
        print(f"  {entry} {tp:7s} minRR{mrr:.0f}: aligned PF {a['al']['pf']:4.2f} (n={a['al']['n']:4d}) | 15M-only PF {u['al']['pf']:4.2f} (n={u['al']['n']:4d})")
    json.dump([{k: v for k, v in r.items() if k != "trades"} for r in res], open(os.path.join(HERE, "results", "liq_grid.json"), "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
