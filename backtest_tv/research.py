"""Strategy improvement search with in-sample selection and out-of-sample validation.

All configs run on the same 90-trading-day window. IS = first 60% of time, OOS = last 40%.
Selection uses IS only (n_IS >= 30, rank by IS t-score = mean/sd*sqrt(n)). OOS is reported, never used.
"""
import itertools, json, os, sys, statistics as st, time
sys.path.insert(0, os.path.dirname(__file__))
import engine as E, run as Rn, alt

OUT = os.path.join(os.path.dirname(__file__), "out")
d0, d1, T0, T1 = Rn.window(); CUT = T0 + 0.6 * (T1 - T0)


def tscore(tr):
    rs = [t["r"] for t in tr]
    if len(rs) < 3: return -9
    sd = st.pstdev(rs) or 1
    return st.mean(rs) / sd * len(rs) ** 0.5


def evaluate(name, cfg, trades):
    sel = Rn.portfolio([t for t in trades if t["exit_t"] < T1])
    IS = [t for t in sel if t["signal_t"] < CUT]; OOS = [t for t in sel if t["signal_t"] >= CUT]
    return dict(name=name, cfg=cfg, full=Rn.stats(sel), IS=Rn.stats(IS), OOS=Rn.stats(OOS), t_IS=tscore(IS), t_OOS=tscore(OOS))


def main():
    rows = []; t0 = time.time()
    # --- A: SMC sniper variants ---
    for bias, entry, partial, tp2, disp, stop_atr in itertools.product(
            ["4h", "1h"], ["ce", "edge"], [True, False], [2.0, 3.0], [1.0, 1.5], [0.3, 0.6]):
        cfg = dict(E.CFG, entry=entry, partial=partial, tp2=tp2, disp_atr=disp, stop_atr=stop_atr)
        tr = []
        for s in E.SYMBOLS: tr += E.find_trades(s, "30m", bias, cfg, T0, T1)
        for tier, no_os in itertools.product([50, 70], [False, True]):
            sub = [t for t in tr if t["score"] >= tier and not (no_os and t["tdi_os"])]
            rows.append(evaluate(f"A SMC {bias}->M30 entry={entry} partial={partial} tp={tp2} disp={disp} stop={stop_atr} score>={tier} noTDIext={no_os}",
                                 dict(fam="A", bias=bias, entry=entry, partial=partial, tp2=tp2, disp=disp, stop_atr=stop_atr, tier=tier, no_os=no_os), sub))
        print("A", bias, entry, partial, tp2, disp, stop_atr, round(time.time() - t0), flush=True)
    # --- B: trend pullback + TDI ---
    for tp, partial, stop_atr, kz in itertools.product([1.5, 2.0, 3.0], [True, False], [0.2, 0.5], [False, True]):
        cfg = dict(tp=tp, partial=partial, stop_atr=stop_atr, kz_only=kz)
        tr = []
        for s in E.SYMBOLS: tr += alt.pullback(s, cfg, T0, T1)
        rows.append(evaluate(f"B pullback tp={tp} partial={partial} stop={stop_atr} kz={kz}", dict(fam="B", **cfg), tr))
    print("B done", round(time.time() - t0), flush=True)
    # --- C: Asian range breakout-retest ---
    for tp, partial, pad in itertools.product([1.5, 2.0, 3.0], [True, False], [0.0, 0.25]):
        cfg = dict(tp=tp, partial=partial, stop_pad=pad, window=8)
        tr = []
        for s in E.SYMBOLS: tr += alt.asia_breakout(s, cfg, T0, T1)
        rows.append(evaluate(f"C asia-breakout tp={tp} partial={partial} pad={pad}", dict(fam="C", **cfg), tr))
    print("C done", round(time.time() - t0), flush=True)
    json.dump(rows, open(f"{OUT}/research_grid.json", "w"), default=str, indent=1)
    ok = [r for r in rows if r["IS"].get("n", 0) >= 30]
    ok.sort(key=lambda r: -r["t_IS"])
    f = lambda s: "n=%3d wr=%3.0f%% pf=%4.2f avgR=%+.2f net=%+6.1f dd=%4.1f" % (s["n"], s["wr"] * 100, min(s["pf"], 99), s["avg_r"], s["net_r"], s["max_dd_r"]) if s.get("n") else "n=0"
    print("\nconfigs:", len(rows), " with IS n>=30:", len(ok), " OOS PF>1 among them:", sum(1 for r in ok if r["OOS"].get("pf", 0) > 1))
    for fam in "ABC":
        fr = [r for r in ok if r["cfg"]["fam"] == fam]
        print(f"family {fam}: {len(fr)} configs, OOS PF>1: {sum(1 for r in fr if r['OOS'].get('pf', 0) > 1)}")
    print("\nTOP 10 by IS t-score:")
    for r in ok[:10]:
        print(f"{r['name']}\n   IS  {f(r['IS'])} t={r['t_IS']:.2f}\n   OOS {f(r['OOS'])} t={r['t_OOS']:.2f}")


if __name__ == "__main__":
    main()
