"""
Walk-forward meta-labelling driver.

  python3 run_meta.py 15min     # intraday-style (holds 1-4h)
  python3 run_meta.py 5min      # scalp-style  (holds up to 15 min)

OOS years 2021..2026 (model for year Y sees only data before Y).
Settings are SELECTED on 2021-2024; 2025-2026 is the final untouched check.
"""
import json, os, sys, time
from multiprocessing import Pool
import numpy as np, pandas as pd
import xau_engine as E, xau_meta as M

HERE = os.path.dirname(os.path.abspath(__file__))
RULE = sys.argv[1] if len(sys.argv) > 1 else "15min"
SEL_YEARS, FIN_YEARS = [2021, 2022, 2023, 2024], [2025, 2026]
QS = (0.005, 0.01, 0.03, 0.10)
LABELINGS = {
    "15min": [dict(sl=1.5, tp=1.0, hold=120), dict(sl=1.5, tp=2.0, hold=240), dict(sl=3.0, tp=1.0, hold=240),
              dict(sl=1.0, tp=1.0, hold=60), dict(sl=1.5, tp=0.0, hold=240), dict(sl=2.0, tp=3.0, hold=240)],
    "1h":    [dict(sl=2.0, tp=1.0, hold=240), dict(sl=2.0, tp=2.0, hold=480), dict(sl=3.0, tp=1.0, hold=480),
              dict(sl=3.0, tp=2.0, hold=1440), dict(sl=2.0, tp=0.0, hold=480), dict(sl=4.0, tp=1.0, hold=1440)],
    "5min":  [dict(sl=1.5, tp=1.0, hold=15), dict(sl=1.0, tp=1.0, hold=10), dict(sl=2.0, tp=1.0, hold=15),
              dict(sl=1.5, tp=0.5, hold=15), dict(sl=1.5, tp=0.0, hold=15), dict(sl=1.5, tp=2.0, hold=15)],
}[RULE]
_G = {}


def _init():
    m1 = E.load_m1(); b = E.to_tf(m1, RULE)
    _G.update(m1=m1, b=b, X=M.build_features(b, m1, RULE), ent=M.entry_index(m1, b, RULE))


def job(lb):
    m1, b, X, ent = _G["m1"], _G["b"], _G["X"], _G["ent"]
    lab = M.label_all(m1, b, ent, lb["sl"], lb["tp"], lb["hold"])
    pred = M.walk_forward_preds(X, lab, X.index, lb["hold"], SEL_YEARS + FIN_YEARS)
    res = []
    for q in QS:
        t = M.pick_trades(pred, lab, ent, X.index, q, SEL_YEARS + FIN_YEARS)
        sel = t[t.entry_time.dt.year.isin(SEL_YEARS)]; fin = t[t.entry_time.dt.year.isin(FIN_YEARS)]
        res.append(dict(rule=RULE, lb=lb, q=q, sel=E.stats(sel), fin=E.stats(fin),
                        yrs={y: round(s["pf"], 2) for y, s in E.by_year(t).items()},
                        yrs_wr={y: round(s["wr"], 1) for y, s in E.by_year(t).items()}))
    return res


def main():
    out = os.path.join(HERE, "results", f"meta_{RULE}.jsonl")
    t0 = time.time(); allr = []
    with Pool(4, initializer=_init) as p:
        for res in p.imap_unordered(job, LABELINGS):
            allr += res
            with open(out, "a") as f:
                for r in res:
                    f.write(json.dumps(r, default=float) + "\n")
            print(f"  batch done {time.time()-t0:.0f}s", flush=True)
    print(f"\n{'labeling':28s} {'q':>5} | {'SELECTION 2021-24':^30} | {'FINAL 2025-26':^30}")
    for r in sorted(allr, key=lambda r: -r["sel"]["pf"] if r["sel"]["n"] >= 30 else 0)[:14]:
        l = r["lb"]; s, f = r["sel"], r["fin"]
        print(f"sl{l['sl']} tp{l['tp']} h{l['hold']:<4d}{'':8s} {r['q']:5.3f} | n={s['n']:4d} WR {s['wr']:5.1f} PF {s['pf']:5.2f} R {s['tot_r']:+6.1f} | "
              f"n={f['n']:4d} WR {f['wr']:5.1f} PF {f['pf']:5.2f} R {f['tot_r']:+6.1f}")


if __name__ == "__main__":
    main()
