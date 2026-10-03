"""
Select finalists from research_<mode>.jsonl and score them on the held-out test.

Selection uses ONLY train (2019-2022) numbers. Validation (2023-24) is shown so
you can see whether the train edge survived. The test period (2025 -> today) is
computed here, once, for the finalists only -- it never influenced selection.

Usage: python3 select_gold.py scalp|intraday [top_k]
"""
import json, os, sys
import numpy as np
import pandas as pd

import xau_engine as E
import xau_strategies as S

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_START = pd.Timestamp("2025-01-01", tz="UTC")
MIN_TRAIN_TRADES = 150


def label(r):
    p = ",".join(f"{k}={v}" for k, v in r["p"].items())
    return f"{r['fam']:<16s} {r['tf']:<5s} h{r['hold']:<3d} tp{r['tp']:<3} {p}"


def worst_year_pf(r):
    v = [x for x in r["yrs"].values() if np.isfinite(x)]
    return min(v) if len(v) >= 3 else 0.0


def fmt(s):
    pf = "inf" if not np.isfinite(s["pf"]) else f"{s['pf']:.2f}"
    return f"n={s['n']:5d} WR {s['wr']:5.1f}% PF {pf:>5s} R {s['tot_r']:+8.1f}"


def main():
    mode = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    rows = [json.loads(l) for l in open(os.path.join(HERE, "results", f"research_{mode}.jsonl"))]
    for r in rows:
        for part in ("train", "valid"):
            if r[part]["pf"] is None:
                r[part]["pf"] = float("inf")
    elig = [r for r in rows if r["train"]["n"] >= MIN_TRAIN_TRADES]
    print(f"{mode}: {len(rows)} configs run, {len(elig)} with >= {MIN_TRAIN_TRADES} train trades\n")

    # ---- the user's targets, checked honestly on train AND validation ----
    def meets(s):
        return s["n"] >= 100 and s["wr"] >= 55 and s["pf"] >= 3 and s["exp_r"] > 0
    both = [r for r in elig if meets(r["train"]) and meets(r["valid"])]
    either = [r for r in elig if meets(r["train"]) or meets(r["valid"])]
    print(f"configs meeting WR>=55% & PF>=3 on BOTH train and validation: {len(both)}")
    print(f"configs meeting it on train OR validation (n>=100):          {len(either)}")
    pos = [r for r in elig if r["train"]["pf"] > 1 and r["valid"]["pf"] > 1]
    print(f"configs profitable (PF>1) on BOTH train and validation:       {len(pos)}\n")

    # ---- shortlist: rank by WORST train year, then require validation to hold ----
    ranked = sorted(elig, key=lambda r: (worst_year_pf(r), r["train"]["pf"]), reverse=True)
    print(f"=== top {k} by worst train-year PF (selection uses train only) ===")
    for r in ranked[:k]:
        print(label(r)); print(f"     train {fmt(r['train'])} | worst-yr PF {worst_year_pf(r):.2f}")
        print(f"     valid {fmt(r['valid'])}")
    print("\n=== best WIN RATE among configs profitable on train (PF>1.1) ===")
    wr = sorted([r for r in elig if r["train"]["pf"] > 1.1], key=lambda r: r["train"]["wr"], reverse=True)
    for r in wr[:5]:
        print(label(r)); print(f"     train {fmt(r['train'])}"); print(f"     valid {fmt(r['valid'])}")

    # ---- one-shot test on finalists: top by train that also stayed profitable in valid ----
    final = [r for r in ranked if r["valid"]["pf"] > 1.0 and r["valid"]["n"] >= 50][:k]
    print(f"\n=== HELD-OUT TEST (2025 -> today), {len(final)} finalists, scored once ===")
    m1 = E.load_m1()
    out = []
    cache = {}
    for r in final:
        if r["tf"] not in cache:
            cache[r["tf"]] = E.to_tf(m1, r["tf"])
        b = cache[r["tf"]]
        L, Sh, R = S.STRATEGIES[r["fam"]](b, **r["p"])
        t = E.run(m1, b, r["tf"], L, Sh, R, hold_min=r["hold"], tp_mult=r["tp"])
        te = t[t.entry_time >= TEST_START]
        s = E.stats(te)
        print(label(r)); print(f"     train {fmt(r['train'])}\n     valid {fmt(r['valid'])}\n     TEST  {fmt(s)}  DD {s['dd_r']:.1f}R")
        out.append(dict(cfg={k_: r[k_] for k_ in ("fam", "tf", "hold", "tp", "p")},
                        train=r["train"], valid=r["valid"], test=s))
    json.dump(out, open(os.path.join(HERE, "results", f"finalists_{mode}.json"), "w"), indent=2, default=float)


if __name__ == "__main__":
    main()
