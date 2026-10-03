"""
Pre-registered SMC + kill-zone grid on gold (real M1 bid/ask, 2019 -> today).

48 configs, fixed before looking: TF {M5,M15} x liquidity {session, swing} x entry {FVG mid, FVG edge}
x HTF bias {off, on} x reward:risk {1,2,3}. Order valid 8 bars, 4h max hold, one position at a time.

  * configs are RANKED on train (2019-22, n>=100)
  * a config qualifies only if PF > 1.05 on train AND validation (2023-24, n>=40)
  * test (2025+) is shown ONLY for qualifiers
  * a mirror diagnostic trades the OPPOSITE side of every signal with the same stop/target distances:
    if the pattern predicts direction, the mirror must lose; if both lose, costs are eating the pattern
"""
import itertools, json, os, sys
from multiprocessing import Pool
import numpy as np, pandas as pd
import xau_engine as E, smc, smc_exec as X

HERE = os.path.dirname(os.path.abspath(__file__))
TR = pd.Timestamp("2023-01-01", tz="UTC"); VA = pd.Timestamp("2025-01-01", tz="UTC")
_M1 = None; _B = {}


def _init():
    global _M1
    _M1 = E.load_m1()


def split(t):
    return (E.stats(t[t.entry_time < TR]), E.stats(t[(t.entry_time >= TR) & (t.entry_time < VA)]),
            E.stats(t[t.entry_time >= VA]), E.stats(t))


def mirror(sig):
    m = sig.copy(); m["dir"] = -m["dir"]
    d = m["risk"]                                    # same planned risk distance on the other side
    m["limit"] = sig["limit"]; m["stop"] = sig["limit"] - m["dir"] * d
    return m


def job(args):
    rule, tfm, liq, entry, bias = args
    if rule not in _B:
        _B[rule] = E.to_tf(_M1, rule)
    b = _B[rule]; sg = smc.generate(b, tfm, liq=liq, entry=entry, bias=bias)
    res = []
    for rr in (1, 2, 3):
        t = X.run_orders(_M1, b, tfm, sg, rr)
        tr, va, te, al = split(t)
        mt = X.run_orders(_M1, b, tfm, mirror(sg), rr)
        res.append(dict(tf=rule, liq=liq, entry=entry, bias=bias, rr=rr, signals=len(sg),
                        tr=tr, va=va, te=te, al=al, mirror_all=E.stats(mt),
                        zone={z: E.stats(t[t.zone == z]) for z in ("london", "ny")},
                        side={("long" if d == 1 else "short"): E.stats(t[t.dir == d]) for d in (1, -1)},
                        by_year={y: round(s["pf"], 2) for y, s in E.by_year(t).items()}))
    return res


def f(s):
    pf = "inf" if not np.isfinite(s["pf"]) else f"{s['pf']:4.2f}"
    return f"n={s['n']:4d} WR {s['wr']:4.1f} PF {pf:>4s} R {s['tot_r']:+6.1f}"


def main():
    combos = list(itertools.product((("5min", 5), ("15min", 15)), ("session", "swing"), ("mid", "edge"), (False, True)))
    args = [(c[0][0], c[0][1], c[1], c[2], c[3]) for c in combos]
    allr = []
    with Pool(4, initializer=_init) as p:
        for r in p.imap_unordered(job, args):
            allr += r; print(f"  {len(allr)}/48", flush=True)
    json.dump(allr, open(os.path.join(HERE, "results", "smc_grid.json"), "w"), indent=1, default=float)
    lab = lambda r: f"{r['tf']:5s} {r['liq']:7s} {r['entry']:4s} bias={'Y' if r['bias'] else 'N'} rr{r['rr']}"
    elig = [r for r in allr if r["tr"]["n"] >= 100]
    print(f"\n48 configs, {len(elig)} with >=100 train trades\n")
    print(f"{'config':40s} | {'train 2019-22':^28s} | {'valid 2023-24':^28s}")
    for r in sorted(elig, key=lambda r: -r["tr"]["pf"])[:12]:
        print(f"{lab(r):40s} | {f(r['tr']):28s} | {f(r['va']):28s}")
    qual = [r for r in elig if r["tr"]["pf"] > 1.05 and r["va"]["pf"] > 1.05 and r["va"]["n"] >= 40]
    print(f"\nQUALIFIERS (PF>1.05 on train AND validation): {len(qual)} of {len(elig)}")
    for r in sorted(qual, key=lambda r: -min(r["tr"]["pf"], r["va"]["pf"])):
        print(f"  {lab(r)} | train {f(r['tr'])} | valid {f(r['va'])} | TEST {f(r['te'])}")
    print("\n=== aggregate over ALL 48 configs (train+valid trades only; no test) ===")
    for rr in (1, 2, 3):
        rs = [r for r in elig if r["rr"] == rr]
        wr = np.mean([(r["tr"]["wr"] * r["tr"]["n"] + r["va"]["wr"] * r["va"]["n"]) / (r["tr"]["n"] + r["va"]["n"]) for r in rs])
        pf = np.median([r["tr"]["pf"] for r in rs]); pfv = np.median([r["va"]["pf"] for r in rs])
        mir = np.median([r["mirror_all"]["pf"] for r in rs])
        print(f"  reward:risk {rr}: mean WR {wr:4.1f}% | median PF train {pf:4.2f} valid {pfv:4.2f} | median MIRROR PF (full history) {mir:4.2f}")
    print("\n=== kill-zone and side breakdown (all configs pooled, full history, PF median) ===")
    for z in ("london", "ny"):
        print(f"  {z:7s} median PF {np.median([r['zone'][z]['pf'] for r in elig if r['zone'][z]['n']>30]):4.2f}")
    for sd in ("long", "short"):
        print(f"  {sd:7s} median PF {np.median([r['side'][sd]['pf'] for r in elig if r['side'][sd]['n']>30]):4.2f}")


if __name__ == "__main__":
    main()
