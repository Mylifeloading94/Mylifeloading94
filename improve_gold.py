"""
Principled improvement study for the gold intraday fade (M15).

~25 SINGLE-CHANGE variants, each motivated by the diagnosis (see README). A change
is ACCEPTED only if it improves profit factor on BOTH train (2019-22) and
validation (2023-24) while keeping a usable sample. Accepted changes are then
combined greedily (max 3 steps, each step must again improve both). The held-out
test (2025 -> today) is scored ONCE, for the final combination only; it is never
shown for individual variants and never used to choose.
"""
import json, os, sys
from dataclasses import dataclass
import numpy as np, pandas as pd
import xau_engine as E, xau_strategies as S

TRAIN_END = pd.Timestamp("2023-01-01", tz="UTC"); VALID_END = pd.Timestamp("2025-01-01", tz="UTC")
m1 = E.load_m1(); BARS = {}

BASE = dict(tf="15min", hold=240, tp=2.0,
            p=dict(bb_k=3.0, rsi_thr=20.0, adx_max=99.0, sl_atr=6.0, side="long"))


def run(cfg):
    b = BARS.setdefault(cfg["tf"], E.to_tf(m1, cfg["tf"]))
    L, Sh, R = S.fade(b, **cfg["p"])
    return E.run(m1, b, cfg["tf"], L, Sh, R, hold_min=cfg["hold"], tp_mult=cfg["tp"])


def split(t):
    return (E.stats(t[t.entry_time < TRAIN_END]),
            E.stats(t[(t.entry_time >= TRAIN_END) & (t.entry_time < VALID_END)]),
            E.stats(t[t.entry_time >= VALID_END]), E.stats(t))


def mod(cfg, **kw):
    c = json.loads(json.dumps(cfg))
    for k, v in kw.items():
        if k in ("hold", "tp", "tf"):
            c[k] = v
        else:
            c["p"][k] = v
    return c


VARIANTS = (
    [(f"trend_ema={n}", dict(trend_ema=n)) for n in (200, 1000, 4800)]
    + [("confirm", dict(confirm=True))]
    + [(f"min_ratio={x}", dict(min_ratio=x)) for x in (0.8, 1.0, 1.3)]
    + [(f"hold={h}", dict(hold=h)) for h in (120, 180, 360, 480)]
    + [(f"sl_atr={x}", dict(sl_atr=x)) for x in (3.0, 4.0, 10.0)]
    + [("sl3,tp1.0", dict(sl_atr=3.0, tp=1.0))]
    + [(f"bb_k={x}", dict(bb_k=x)) for x in (2.5, 3.5)]
    + [(f"rsi_thr={x}", dict(rsi_thr=x)) for x in (15.0, 25.0)]
    + [("both+trend1000", dict(side="both", trend_ema=1000)), ("both+trend4800", dict(side="both", trend_ema=4800))]
)


def f(s):
    pf = "inf" if not np.isfinite(s["pf"]) else f"{s['pf']:4.2f}"
    return f"n={s['n']:3d} WR {s['wr']:4.1f} PF {pf:>4s} R {s['tot_r']:+6.1f}"


def main():
    base_t, base_v, base_te, base_all = split(run(BASE))
    print(f"{len(VARIANTS)} single-change variants. BASE: train {f(base_t)} | valid {f(base_v)}\n")
    print(f"{'variant':20s} | {'train 2019-22':^32s} | {'valid 2023-24':^32s} | accepted")
    acc = []
    for name, kw in VARIANTS:
        c = mod(BASE, **kw)
        tr, va, _, _ = split(run(c))
        ok = (tr["pf"] > base_t["pf"] and va["pf"] > base_v["pf"] and tr["n"] >= 100 and va["n"] >= 50)
        print(f"{name:20s} | {f(tr):32s} | {f(va):32s} | {'YES' if ok else 'no'}")
        if ok:
            acc.append((name, kw, tr, va))
    print(f"\n{len(acc)} accepted of {len(VARIANTS)}")
    cur, cur_t, cur_v, steps = BASE, base_t, base_v, []
    pool = list(acc)
    for _ in range(3):
        best = None
        for name, kw, *_ in pool:
            c = mod(cur, **kw)
            tr, va, _, _ = split(run(c))
            if tr["pf"] > cur_t["pf"] and va["pf"] > cur_v["pf"] and tr["n"] >= 100 and va["n"] >= 50:
                if best is None or tr["pf"] > best[3]["pf"]:
                    best = (name, c, kw, tr, va)
        if best is None:
            break
        steps.append(best[0]); cur, cur_t, cur_v = best[1], best[3], best[4]
        print(f"  + {best[0]:18s} -> train {f(cur_t)} | valid {f(cur_v)}")
    tr, va, te, al = split(run(cur))
    print(f"\nFINAL COMBINATION: {steps if steps else 'BASE (nothing improved both periods)'}")
    print(json.dumps(cur, indent=1))
    print(f"  train {f(tr)}\n  valid {f(va)}\n  TEST  {f(te)}   <- scored once\n  ALL   {f(al)}")
    print("  BASE test for reference:", f(base_te))
    print("  by year PF:", {y: round(s['pf'], 2) for y, s in E.by_year(run(cur)).items()})
    json.dump(dict(final=cur, steps=steps, train=tr, valid=va, test=te, base_test=base_te),
              open("results/improve_gold.json", "w"), indent=2, default=float)


if __name__ == "__main__":
    main()
