"""
Improvement study for the Brad-Gold liquidity-scalping strategy. 96 pre-registered configs:
entry {E1, E2-loose} x stop buffer {0.1, 0.5 ATR} x min stop {0.5, 1.5 ATR} x target {nearest swing, nearest swing paying
>=1R, >=1.5R} x kill zones {off, on} x timeframe rule {1H+15M aligned, 15M only}.
Rank on train (2019-22); QUALIFY only if PF > 1.10 on train AND validation (2023-24), n >= 100 / 50.
Test (2025+) is shown only for qualifiers. Multiple-testing note: 96 configs, so a lone PF of 1.15 is expected by chance.
"""
import itertools, json, os
from multiprocessing import Pool
import numpy as np, pandas as pd
import xau_engine as E, liq_scalp as LS, liq_exec as X

HERE = os.path.dirname(os.path.abspath(__file__))
TR = pd.Timestamp("2023-01-01", tz="UTC"); VA = pd.Timestamp("2025-01-01", tz="UTC")
_G = {}


def init():
    m1 = E.load_m1(); _G.update(m1=m1, b15=E.to_tf(m1, "15min"), b1h=E.to_tf(m1, "1h"))


def job(a):
    entry, buf, minr, tpm, kz, al = a
    m1, b15, b1h = _G["m1"], _G["b15"], _G["b1h"]
    sg = LS.generate(b15, b1h, entry=entry.split("-")[0], e2_mode=("loose" if entry == "E2-loose" else "strict"),
                     aligned=al, stop_buf=buf, min_risk_atr=minr, tp_min_r=tpm, kz=kz)
    t = X.run(m1, b15, sg)
    sp = E.stats
    return dict(cfg=dict(entry=entry, buf=buf, min_risk=minr, tp_min_r=tpm, kz=kz, aligned=al), signals=len(sg),
                tr=sp(t[t.entry_time < TR]), va=sp(t[(t.entry_time >= TR) & (t.entry_time < VA)]),
                te=sp(t[t.entry_time >= VA]), al=sp(t))


def f(s):
    return f"n={s['n']:4d} WR {s['wr']:4.1f} PF {('inf' if not np.isfinite(s['pf']) else format(s['pf'],'4.2f')):>4s} R {s['tot_r']:+6.1f}"


def lab(c):
    return f"{c['entry']:8s} buf{c['buf']} minrisk{c['min_risk']} tp>={c['tp_min_r']} kz={'Y' if c['kz'] else 'N'} {'1H+15M' if c['aligned'] else '15M'}"


def main():
    grid = list(itertools.product(("E1", "E2-loose"), (0.1, 0.5), (0.5, 1.5), (0.0, 1.0, 1.5), (False, True), (True, False)))
    with Pool(4, initializer=init) as p:
        res = p.map(job, grid, chunksize=2)
    json.dump(res, open(os.path.join(HERE, "results", "liq_improve.json"), "w"), indent=1, default=float)
    el = [r for r in res if r["tr"]["n"] >= 100]
    print(f"{len(res)} configs, {len(el)} with >=100 train trades\n")
    print(f"{'config':58s} | {'train 2019-22':^28s} | {'valid 2023-24':^28s}")
    for r in sorted(el, key=lambda r: -r["tr"]["pf"])[:14]:
        print(f"{lab(r['cfg']):58s} | {f(r['tr']):28s} | {f(r['va']):28s}")
    q = [r for r in el if r["tr"]["pf"] > 1.10 and r["va"]["pf"] > 1.10 and r["va"]["n"] >= 50]
    print(f"\nQUALIFIERS (PF > 1.10 on train AND validation): {len(q)} of {len(el)}")
    for r in sorted(q, key=lambda r: -min(r["tr"]["pf"], r["va"]["pf"])):
        print(f"  {lab(r['cfg'])} | train {f(r['tr'])} | valid {f(r['va'])} | TEST {f(r['te'])}")
    print("\n=== effect of each lever (median train PF / median valid PF across the configs that differ only in that lever) ===")
    for k, vals in (("entry", ("E1", "E2-loose")), ("buf", (0.1, 0.5)), ("min_risk", (0.5, 1.5)), ("tp_min_r", (0.0, 1.0, 1.5)), ("kz", (False, True)), ("aligned", (True, False))):
        row = []
        for v in vals:
            rs = [r for r in el if r["cfg"][k] == v]
            row.append(f"{k}={v}: train {np.median([r['tr']['pf'] for r in rs]):.2f} valid {np.median([r['va']['pf'] for r in rs]):.2f} (n={len(rs)})")
        print("  " + " | ".join(row))


if __name__ == "__main__":
    main()
