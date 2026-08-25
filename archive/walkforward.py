"""
Walk-forward validation -- the PRIMARY evidence for this build.

Anchored-window walk-forward across the whole usable history. Each cycle:
    train on everything up to a cut-off, choose the score threshold and the
    pair watchlist there, then trade the NEXT 3 months with that frozen choice.

No window is ever used for both selection and evaluation, so unlike a single
train/test split this cannot be contaminated by re-examining the test set.
"""
import numpy as np, pandas as pd
import tl_data, strategy as st, signal_sim as ss, config

frames = {s: tl_data.load(s) for s in tl_data.SYMBOLS}
CTX = {}


def sim(sym, p, s, e):
    key = (sym, p.tf_minutes, p.sl_atr_buffer, p.tp_r, p.retr_frac,
           p.require_bias, p.time_stop_bars)
    if key not in CTX:
        CTX[key] = st.Context(sym, frames[sym], p)
    return ss.simulate_symbol(sym, frames[sym], p, s, e, ctx=CTX[key])


def pooled(rows):
    if not rows:
        return None
    r = np.array([x["r"] for x in rows])
    gp, gl = r[r > 0].sum(), -r[r <= 0].sum()
    return dict(n=len(r), wr=100 * (r > 0).mean(),
                pf=gp / gl if gl > 0 else 99.0, exp=r.mean(), tot=r.sum())


TRAIN_START = pd.Timestamp("2024-04-01", tz="UTC")
cuts = pd.date_range("2025-04-01", "2026-07-01", freq="3MS", tz="UTC")

rows = []
oos_all = []
for cut in cuts:
    te_s = cut
    te_e = cut + pd.offsets.MonthBegin(3) - pd.Timedelta(seconds=1)
    if te_s >= pd.Timestamp("2026-08-22", tz="UTC"):
        break

    # ---- train on everything before the cut ----
    base = config.locked_params()
    per, allr = {}, []
    for s in tl_data.SYMBOLS:
        r = sim(s, base, TRAIN_START, cut - pd.Timedelta(seconds=1))
        per[s] = r
        allr += r
    if len(allr) < 30:
        continue
    df = pd.DataFrame(allr)

    # choose the score threshold on TRAIN only
    best_thr, best_pf = base.min_score, -1
    for thr in (50, 55, 60, 65, 70):
        rr = df.r[df.score >= thr].values
        if len(rr) < 25:
            continue
        gp, gl = rr[rr > 0].sum(), -rr[rr <= 0].sum()
        pf = gp / gl if gl > 0 else 99.0
        if pf > best_pf:
            best_pf, best_thr = pf, thr

    # choose the watchlist on TRAIN only
    wl = [s for s, r in per.items()
          if len(r) >= 3 and pooled(r) and pooled(r)["pf"] > 1.2]
    if len(wl) < 3:
        wl = list(tl_data.SYMBOLS)

    # ---- trade the next 3 months with the frozen choice ----
    p = config.locked_params()
    p.min_score = best_thr
    ter_sel, ter_all = [], []
    for s in tl_data.SYMBOLS:
        r = [x for x in sim(s, p, te_s, te_e) if x["score"] >= best_thr]
        ter_all += r
        if s in wl:
            ter_sel += r
    k_sel, k_all = pooled(ter_sel), pooled(ter_all)
    oos_all += ter_all
    rows.append(dict(
        test=f"{te_s:%Y-%m}..{te_e:%Y-%m}", thr=best_thr, wl=len(wl),
        train_n=len(df), train_pf=round(best_pf, 3),
        sel_n=k_sel["n"] if k_sel else 0,
        sel_wr=round(k_sel["wr"], 1) if k_sel else np.nan,
        sel_pf=round(k_sel["pf"], 3) if k_sel else np.nan,
        all_n=k_all["n"] if k_all else 0,
        all_wr=round(k_all["wr"], 1) if k_all else np.nan,
        all_pf=round(k_all["pf"], 3) if k_all else np.nan,
        all_exp=round(k_all["exp"], 3) if k_all else np.nan))

df = pd.DataFrame(rows)
pd.set_option("display.width", 220)
print("=== ANCHORED WALK-FORWARD (train to cut -> trade next 3 months) ===")
print(df.to_string(index=False))

k = pooled(oos_all)
print("\n=== POOLED OUT-OF-SAMPLE (every trade, no window reused) ===")
print(f"  trades      {k['n']}")
print(f"  win rate    {k['wr']:.2f}%")
print(f"  profit factor {k['pf']:.3f}")
print(f"  expectancy  {k['exp']:+.4f}R")
print(f"  total       {k['tot']:+.2f}R")
v = df.dropna(subset=["all_pf"])
print(f"\n  periods with PF > 1 (all pairs): {(v.all_pf > 1).sum()} / {len(v)}")
print(f"  periods with PF > 1 (filtered) : {(v.sel_pf > 1).sum()} / {len(v)}")
if v.train_pf.std() > 0 and v.all_pf.std() > 0:
    print(f"  corr(train PF, test PF): {np.corrcoef(v.train_pf, v.all_pf)[0,1]:+.3f}")
df.to_csv("walkforward.csv", index=False)
