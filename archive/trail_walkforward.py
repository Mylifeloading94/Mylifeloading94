"""
Does a trailing stop survive OUT OF SAMPLE?

Runs the same anchored walk-forward used for the baseline, with the trail
variant applied. Nothing about the trail is selected on the test data: each
variant is simply carried through unchanged and reported.
"""
import numpy as np, pandas as pd
import tl_data, strategy as st, signal_sim as ss, config

TRAIN_START = pd.Timestamp("2024-04-01", tz="UTC")
M15 = {s: tl_data.load(s) for s in tl_data.SYMBOLS}
M1 = {s: tl_data.load_m1(s) for s in tl_data.SYMBOLS}
CTX = {}


def ctx_for(s, p):
    k = (s, p.tf_minutes, p.sl_atr_buffer, p.tp_r, p.require_bias, p.time_stop_bars, p.sessions)
    if k not in CTX:
        CTX[k] = st.Context(s, M15[s], p)
    return CTX[k]


def pooled(rows):
    if not rows:
        return None
    r = np.array([x["r"] for x in rows])
    gp, gl = r[r > 0].sum(), -r[r <= 0].sum()
    return dict(n=len(r), wr=100 * (r > 0).mean(),
                pf=gp / gl if gl > 0 else 99.0, exp=r.mean(), tot=r.sum())


def variant(name, **kw):
    cuts = pd.date_range("2025-04-01", "2026-07-01", freq="3MS", tz="UTC")
    oos = []
    per_block = []
    use_m1 = kw.get("trail_pips", 0) > 0 or kw.get("trail_r", 0) > 0
    for cut in cuts:
        te_s = cut
        te_e = min(cut + pd.offsets.MonthBegin(3) - pd.Timedelta(seconds=1),
                   pd.Timestamp("2026-08-22 23:59", tz="UTC"))
        if te_s >= pd.Timestamp("2026-08-22", tz="UTC"):
            break
        # threshold chosen on TRAIN only, exactly as the baseline does
        base = config.locked_params()
        for k, v in kw.items():
            setattr(base, k, v)
        tr_rows = []
        for s in tl_data.SYMBOLS:
            tr_rows += ss.simulate_symbol(s, M15[s], base, TRAIN_START,
                                          cut - pd.Timedelta(seconds=1),
                                          ctx=ctx_for(s, base),
                                          m1=M1[s] if use_m1 else None)
        best_thr, best_pf = 60, -1
        df = pd.DataFrame(tr_rows) if tr_rows else None
        if df is not None and len(df):
            for thr in (50, 55, 60, 65, 70):
                rr = df.r[df.score >= thr].values
                if len(rr) < 25:
                    continue
                gp, gl = rr[rr > 0].sum(), -rr[rr <= 0].sum()
                pf = gp / gl if gl > 0 else 99.0
                if pf > best_pf:
                    best_pf, best_thr = pf, thr
        p = config.locked_params()
        for k, v in kw.items():
            setattr(p, k, v)
        p.min_score = best_thr
        te_rows = []
        for s in tl_data.SYMBOLS:
            te_rows += [x for x in ss.simulate_symbol(
                s, M15[s], p, te_s, te_e, ctx=ctx_for(s, p),
                m1=M1[s] if use_m1 else None) if x["score"] >= best_thr]
        oos += te_rows
        k = pooled(te_rows)
        per_block.append(k["pf"] if k else np.nan)
    k = pooled(oos)
    pos = sum(1 for x in per_block if x == x and x > 1)
    return name, k, pos, len(per_block), oos


print("=== TRAILING STOP, OUT OF SAMPLE (anchored walk-forward) ===\n")
results = []
for name, kw in [("no trail (baseline)", {}),
                 ("20 pips / 20 gap", dict(trail_pips=20.0, trail_gap_pips=20.0)),
                 ("20 pips / 10 gap", dict(trail_pips=20.0, trail_gap_pips=10.0)),
                 ("proportional 0.5R / 0.25R", dict(trail_r=0.5, trail_gap_r=0.25))]:
    nm, k, pos, tot, oos = variant(name, **kw)
    results.append((nm, k, pos, tot, oos))
    print(f"{nm:28s} n={k['n']:4d} wr={k['wr']:5.2f}% pf={k['pf']:6.3f} "
          f"exp={k['exp']:+.4f}R  periods PF>1: {pos}/{tot}")

# per-instrument robustness against the baseline
base_rows = results[0][4]
b = pd.DataFrame(base_rows)
print("\n=== per-instrument robustness vs baseline (out of sample) ===")
for nm, k, pos, tot, oos in results[1:]:
    d = pd.DataFrame(oos)
    helped = hurt = 0
    for s in tl_data.SYMBOLS:
        bs = b[b.symbol == s]; ts = d[d.symbol == s]
        if len(bs) < 3 or len(ts) < 3:
            continue
        if ts.r.mean() > bs.r.mean():
            helped += 1
        elif ts.r.mean() < bs.r.mean():
            hurt += 1
    print(f"  {nm:28s} helped {helped}, hurt {hurt}")
