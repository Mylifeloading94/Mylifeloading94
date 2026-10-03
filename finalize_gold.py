"""Final full-period (2019 -> today) report for the two shipped gold configs."""
import json, numpy as np, pandas as pd, xau_engine as E, xau_strategies as S

m1 = E.load_m1()
BH = {}
mid = (m1.bc + m1.ac) / 2
prev = mid.iloc[0]
for ts, v in mid.resample("YS").last().items():
    BH[ts.year] = 100 * (v / prev - 1); prev = v

CONFIGS = {
 "intraday": dict(name="gold_intraday", fam="fade", tf="15min", hold=240, tp=2.0,
                  p=dict(bb_k=3.0, rsi_thr=20.0, adx_max=99.0, sl_atr=6.0, side="long"),
                  risk_pct=0.5, symbol="XAUUSD", max_lots=1.0, validated=True),
 "scalp":    dict(name="gold_scalp", fam="fade", tf="5min", hold=10, tp=0.5,
                  p=dict(bb_k=3.0, rsi_thr=15.0, adx_max=99.0, sl_atr=2.0, side="long"),
                  risk_pct=0.25, symbol="XAUUSD", max_lots=1.0, validated=False),
}
report = {}
for mode, c in CONFIGS.items():
    b = E.to_tf(m1, c["tf"])
    L, Sh, R = S.STRATEGIES[c["fam"]](b, **c["p"])
    t = E.run(m1, b, c["tf"], L, Sh, R, hold_min=c["hold"], tp_mult=c["tp"])
    a = E.stats(t, c["risk_pct"])
    print(f"\n===== {mode.upper()}  ({c['fam']} {c['tf']} hold {c['hold']}m tp {c['tp']}R, long-only) =====")
    print(f"2019 -> {m1.index[-1].date()}:  n={a['n']}  WR {a['wr']:.1f}%  PF {a['pf']:.2f}  exp {a['exp_r']:+.4f}R  total {a['tot_r']:+.1f}R  t={a['t']:+.2f}")
    print(f"avg win {a['avg_win']:+.3f}R / avg loss {a['avg_loss']:+.3f}R   maxDD {a['dd_r']:.1f}R")
    for rp in (0.25, 0.5, 1.0):
        s = E.stats(t, rp)
        print(f"   risk {rp:4.2f}%/trade -> compounded return {s['ret_pct']:+7.1f}% over 7.75y, max DD {s['dd_pct']:.1f}%")
    print(f"{'year':>6} {'n':>5} {'WR%':>6} {'PF':>6} {'R':>8}   gold b&h")
    for y, s in E.by_year(t, c["risk_pct"]).items():
        print(f"{y:>6} {s['n']:5d} {s['wr']:6.1f} {s['pf']:6.2f} {s['tot_r']:+8.1f}   {BH[y]:+5.0f}%")
    rr = t.r - 0.25 / t.risk
    print(f"cost stress (+$0.25/oz): PF {rr[rr>0].sum()/max(-rr[rr<=0].sum(),1e-9):.2f}  totR {rr.sum():+.1f}")
    report[mode] = dict(config=c, stats=a, by_year={y: s for y, s in E.by_year(t, c["risk_pct"]).items()},
                        dd_at_risk={str(rp): E.stats(t, rp)["dd_pct"] for rp in (0.25, 0.5, 1.0)},
                        ret_at_risk={str(rp): E.stats(t, rp)["ret_pct"] for rp in (0.25, 0.5, 1.0)})
    t.to_csv(f"results/trades_{mode}_2019_today.csv", index=False)
    json.dump(c, open(f"configs/gold_{mode}.json", "w"), indent=2)
json.dump(report, open("results/final_gold_bots.json", "w"), indent=2, default=float)
