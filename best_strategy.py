"""
Which strategy (or combination) earns the most, honestly?

Protocol, fixed before looking at results:
  * candidates = strategies already identified in earlier rounds (no new searching)
  * INCLUDED only if PF > 1.05 on train (2019-22) AND validation (2023-24)
  * risk per trade is chosen on the DESIGN period (2019-2024) only, as the largest risk whose
    design-period max drawdown stays within the budget
  * 2025 -> today is held out and scored once, at that risk
  * portfolios are event-driven: each trade risks risk% of the equity REALISED at its entry, so
    overlapping trades across strategies are handled; drawdown is on realised equity (an
    approximation: no intra-trade mark-to-market)
  * drawdown risk is shown as a bootstrap (trade order reshuffled) because one historical
    path understates what the same trades can do in a different order
"""
import json, os
import numpy as np, pandas as pd
import xau_engine as E, xau_strategies as S, screen_watchlist as W

HERE = os.path.dirname(os.path.abspath(__file__))
lines = []
def out(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)

TR_END = pd.Timestamp("2023-01-01", tz="UTC"); DES_END = pd.Timestamp("2025-01-01", tz="UTC")


def h1_ledger(sym, name, p, hold):
    cfg = dict(name=name, fam="momentum", hold=hold, p=p)
    h1 = W.load_h1(sym); b, L, Sh, R = W.signals(h1, cfg)
    return W.evaluate(h1, b, L, Sh, R, cfg)


def ledgers():
    L = {}
    m1 = E.load_m1(); g = json.load(open(os.path.join(HERE, "configs", "gold_intraday.json")))
    b = E.to_tf(m1, g["tf"]); l, s, r = S.fade(b, **g["p"])
    L["GOLD M15 fade (long)"] = E.run(m1, b, g["tf"], l, s, r, hold_min=g["hold"], tp_mult=g["tp"])
    mom = lambda t: dict(bo_len=20, rsi_thr=t, sl_atr=3., side="both")
    L["USDJPY H1 momentum RSI>75"] = h1_ledger("USDJPY", "m75", mom(75.), 480)
    L["USDJPY H1 momentum RSI>80 (post-hoc)"] = h1_ledger("USDJPY", "m80", mom(80.), 480)
    L["USDCHF H1 momentum RSI>75"] = h1_ledger("USDCHF", "m75", mom(75.), 480)
    # gold M5 long-only momentum (the one-year 'v2' strategy), for comparison
    b5 = E.to_tf(m1, "5min"); l, s, r = S.momentum(b5, bo_len=20, rsi_thr=75., sl_atr=10., side="long")
    L["GOLD M5 momentum RSI>75 (v2)"] = E.run(m1, b5, "5min", l, s, r, hold_min=90)
    return {k: v.sort_values("entry_time").reset_index(drop=True) for k, v in L.items()}


def pf(t):
    r = t.r.to_numpy(); l = -r[r <= 0].sum()
    return r[r > 0].sum() / l if l > 0 else float("inf")


def simulate(parts, risk_pct, start=None, end=None):
    """Event-driven shared-equity simulation. parts: list of (ledger, weight). Returns realised equity series."""
    ev = []
    for k, (t, w) in enumerate(parts):
        d = t if start is None else t[(t.entry_time >= start) & (t.entry_time < end)]
        for i, row in d.iterrows():
            ex = max(row.exit_time, row.entry_time + pd.Timedelta(microseconds=1))   # a trade can stop out inside its entry bar
            ev.append((row.entry_time, 1, k, i, w, row.r)); ev.append((ex, 0, k, i, w, row.r))
    ev.sort(key=lambda e: (e[0], e[1]))          # exits before entries at the same instant
    eq, open_amt, times, vals = 1.0, {}, [], []
    for tm, typ, k, i, w, r in ev:
        if typ == 1:
            open_amt[(k, i)] = eq * risk_pct / 100.0 * w
        else:
            eq += open_amt.pop((k, i)) * r; times.append(tm); vals.append(eq)
    return pd.Series(vals, index=pd.DatetimeIndex(times))


def eq_stats(eq):
    if len(eq) < 3:
        return dict(ret=0.0, dd=0.0, sharpe=0.0, cagr=0.0)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq.to_numpy()]))[1:]
    dd = float(((peak - eq.to_numpy()) / peak).max() * 100)
    daily = eq.resample("1D").last().ffill().pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    ret = (eq.iloc[-1] - 1) * 100
    return dict(ret=float(ret), dd=dd, sharpe=float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0,
                cagr=float(((eq.iloc[-1]) ** (1 / yrs) - 1) * 100) if yrs > 0 and eq.iloc[-1] > 0 else float("nan"))


def boot_dd(r_sorted, risk_pct, n=3000, seed=0):
    rng = np.random.default_rng(seed); k = len(r_sorted); dds = np.empty(n)
    for i in range(n):
        eq = np.cumprod(1 + risk_pct / 100 * rng.choice(r_sorted, k, replace=True))
        pk = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
        dds[i] = ((pk - eq) / pk).max() * 100
    return float(np.percentile(dds, 50)), float(np.percentile(dds, 95))


def main():
    L = ledgers()
    out("=== 1. candidates on a common footing (R-based, spread paid) ===")
    out(f"{'strategy':40s} {'trades':>6s} | {'train PF':>8s} {'valid PF':>8s} {'test PF':>8s} | {'all PF':>6s} {'tot R':>7s} {'incl':>5s}")
    keep = {}
    for k, t in L.items():
        tr, va, te = t[t.entry_time < TR_END], t[(t.entry_time >= TR_END) & (t.entry_time < DES_END)], t[t.entry_time >= DES_END]
        inc = pf(tr) > 1.05 and pf(va) > 1.05 and len(tr) >= 100 and len(va) >= 40 and "post-hoc" not in k
        out(f"{k:40s} {len(t):6d} | {pf(tr):8.2f} {pf(va):8.2f} {pf(te):8.2f} | {pf(t):6.2f} {t.r.sum():+7.1f} {'YES' if inc else 'no':>5s}")
        if inc:
            keep[k] = t
    out("\n(post-hoc variants are shown but never eligible: they were picked after seeing results)")
    out(f"\nINCLUDED by the pre-registered rule: {list(keep)}")

    parts = [(t, 1.0 / len(keep)) for t in keep.values()]
    port_trades = pd.concat(keep.values()).sort_values("exit_time")
    out("\n=== 2. diversification: do the included edges move together? (daily R, correlation) ===")
    daily = pd.DataFrame({k: t.set_index("exit_time").r.resample("1D").sum() for k, t in keep.items()}).fillna(0)
    out(daily.corr().round(2).to_string())

    out("\n=== 3. sizing on the DESIGN period (2019-24); then 2025+ held out and scored once ===")
    out(f"{'risk budget':>11s} | {'design ret':>10s} {'design DD':>9s} | {'TEST ret':>9s} {'TEST DD':>8s} | {'full ret':>9s} {'full DD':>8s} {'CAGR':>6s} {'Sharpe':>6s} | {'bootstrap DD med/95th':>22s}")
    rs = port_trades.r.to_numpy(); chosen = None
    for rp in (0.25, 0.5, 1.0, 1.5, 2.0, 3.0):
        des = eq_stats(simulate(parts, rp, pd.Timestamp("2019-01-01", tz="UTC"), DES_END))
        tst = eq_stats(simulate(parts, rp, DES_END, pd.Timestamp("2030-01-01", tz="UTC")))
        full = eq_stats(simulate(parts, rp))
        bm, b95 = boot_dd(rs, rp / len(keep))      # each trade risks rp/len(keep) of equity
        out(f"{rp:10.2f}% | {des['ret']:+9.1f}% {des['dd']:8.1f}% | {tst['ret']:+8.1f}% {tst['dd']:7.1f}% | {full['ret']:+8.1f}% {full['dd']:7.1f}% {full['cagr']:5.1f}% {full['sharpe']:6.2f} | {bm:9.1f}% / {b95:5.1f}%")
        if des["dd"] <= 5.0:
            chosen = rp
    out(f"\nlargest risk with design-period DD <= 5% (leaves headroom: live DD is usually worse): {chosen}%")

    out("(risk budget is split equally across the included strategies; each trade risks budget/3 of equity)")
    out("\n=== 4. the same, strategy by strategy, at risk sized to the same 5% design-DD budget ===")
    out(f"{'strategy':40s} {'risk':>6s} | {'design ret':>10s} {'TEST ret':>9s} {'TEST DD':>8s} | {'full ret':>9s} {'full DD':>8s} {'Sharpe':>6s}")
    for k, t in list(keep.items()) + [("PORTFOLIO (equal risk split)", None), ("HINDSIGHT: USDJPY RSI>80 (post-hoc, NOT eligible)", L["USDJPY H1 momentum RSI>80 (post-hoc)"])]:
        pr = parts if t is None else [(t, 1.0)]
        best = 0.1
        for rp in np.arange(0.1, 6.01, 0.1):
            if eq_stats(simulate(pr, rp, pd.Timestamp("2019-01-01", tz="UTC"), DES_END))["dd"] <= 5.0:
                best = rp
        des = eq_stats(simulate(pr, best, pd.Timestamp("2019-01-01", tz="UTC"), DES_END))
        tst = eq_stats(simulate(pr, best, DES_END, pd.Timestamp("2030-01-01", tz="UTC")))
        full = eq_stats(simulate(pr, best))
        out(f"{k:40s} {best:5.1f}% | {des['ret']:+9.1f}% {tst['ret']:+8.1f}% {tst['dd']:7.1f}% | {full['ret']:+8.1f}% {full['dd']:7.1f}% {full['sharpe']:6.2f}")
    open(os.path.join(HERE, "results", "best_strategy.txt"), "w").write("\n".join(lines))


if __name__ == "__main__":
    main()
