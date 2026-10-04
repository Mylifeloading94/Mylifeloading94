"""Full profit statistics for the Brad-Gold liquidity-scalping strategy on a $25,000 account.
Three versions x three risk levels x (with / without the $1,250 drawdown breaker). Real 0.01-lot sizing, spread paid."""
import json, os
import numpy as np, pandas as pd
import xau_engine as E, liq_scalp as LS, liq_exec as X, account_sim as A

HERE = os.path.dirname(os.path.abspath(__file__)); EQ0 = 25_000.0
m1 = E.load_m1(); b15 = E.to_tf(m1, "15min"); b1h = E.to_tf(m1, "1h")
grid = json.load(open(os.path.join(HERE, "results", "liq_improve.json")))
el = [r for r in grid if r["tr"]["n"] >= 100 and r["va"]["n"] >= 40]
best = max(el, key=lambda r: min(r["tr"]["pf"], r["va"]["pf"]))["cfg"]
VERS = {"E1 (as written)": dict(entry="E1", buf=0.1, min_risk=0.5, tp_min_r=0.0, kz=False, aligned=True),
        "E2 (as written)": dict(entry="E2", buf=0.1, min_risk=0.5, tp_min_r=0.0, kz=False, aligned=True),
        "Best improved": best}
lines = []
def out(s=""):
    print(s); lines.append(s)


def ledger(c):
    sg = LS.generate(b15, b1h, entry=c["entry"].split("-")[0], e2_mode=("loose" if c["entry"] == "E2-loose" else "strict"),
                     aligned=c["aligned"], stop_buf=c["buf"], min_risk_atr=c["min_risk"], tp_min_r=c["tp_min_r"], kz=c["kz"])
    return X.run(m1, b15, sg)


def streak(x, positive):
    best = cur = 0
    for v in x:
        cur = cur + 1 if ((v > 0) == positive) else 0
        best = max(best, cur)
    return best


def stats(led, st, years):
    u = led.usd.to_numpy(); w, l = u[u > 0], u[u <= 0]
    eq = led.set_index("exit_time").equity
    pk = eq.cummax(); dd_real = (pk - eq).max()
    daily = eq.resample("1D").last().ffill().pct_change().dropna()
    under = (eq < pk)
    dur = 0; start = None
    for ts, flag in under.items():
        if flag and start is None: start = ts
        if not flag and start is not None: dur = max(dur, (ts - start).days); start = None
    if start is not None: dur = max(dur, (eq.index[-1] - start).days)
    return dict(trades=len(u), wr=100 * (u > 0).mean() if len(u) else 0, gp=w.sum(), gl=l.sum(), net=u.sum(),
                pf=(w.sum() / -l.sum()) if len(l) and l.sum() < 0 else float("inf"), ret=100 * u.sum() / EQ0,
                cagr=100 * (((EQ0 + u.sum()) / EQ0) ** (1 / years) - 1) if EQ0 + u.sum() > 0 else float("nan"),
                avg_win=w.mean() if len(w) else 0, avg_loss=l.mean() if len(l) else 0, exp=u.mean() if len(u) else 0,
                best=u.max() if len(u) else 0, worst=u.min() if len(u) else 0, max_w=streak(u, True), max_l=streak(u, False),
                lots=led.lots.mean() if len(led) else 0, hold=(led.exit_time - led.entry_time).mean(),
                mtm_dd=st["max_dd"], mtm_dd_pct=100 * st["max_dd"] / EQ0, real_dd=dd_real, dd_days=dur,
                sharpe=(daily.mean() / daily.std() * np.sqrt(252)) if len(daily) > 5 and daily.std() > 0 else 0.0,
                final=st["final"], first=led.entry_time.iloc[0] if len(led) else None, last=led.exit_time.iloc[-1] if len(led) else None)


ledgers = {n: ledger(c) for n, c in VERS.items()}
out("FULL PROFIT STATISTICS  |  gold (XAUUSD)  |  Brad-Gold liquidity scalping  |  $25,000 start  |  2019-01 -> 2026-10")
out("real M1 bid/ask, spread paid, 0.01-lot steps, no commission; drawdown is mark-to-market (worst adverse excursion per M1 bar)")
out("'breaker' = trading halts permanently when drawdown reaches $1,250 (5% of the account)\n")
out(f"best improved config: {best}\n")
rows = []
for name, t in ledgers.items():
    r0 = E.stats(t); rr = t.r.to_numpy(); rng = np.random.default_rng(0)
    ci = np.percentile([rng.choice(rr, len(rr)).mean() for _ in range(3000)], [2.5, 97.5])
    out(f"--- {name}: ledger of {len(t)} trades | WR {r0['wr']:.1f}% | PF(R) {r0['pf']:.2f} | mean R {r0['exp_r']:+.3f} (95% CI {ci[0]:+.3f}..{ci[1]:+.3f}) | t = {r0['t']:+.2f} | avg win {r0['avg_win']:+.2f}R avg loss {r0['avg_loss']:+.2f}R")
    for rp in (0.25, 0.5, 1.0):
        for breaker in (True, False):
            led, st = A.simulate(m1, t, rp, halt_on_breach=breaker)
            yrs = max((led.exit_time.iloc[-1] - led.entry_time.iloc[0]).days / 365.25, 0.25) if len(led) else 1
            s = stats(led, st, yrs); s.update(version=name, risk=rp, breaker=breaker, breached=st["breached"], breach_at=st["breach_at"], skipped=st["skipped"], years=yrs)
            rows.append(s)
tbl = pd.DataFrame(rows)
out("\n=== A. WITH the $1,250 breaker (what the account actually does) ===")
out(f"{'version':16s} {'risk':>5s} {'trades':>6s} {'WR%':>5s} {'net $':>8s} {'return':>7s} {'PF($)':>6s} {'avg win':>8s} {'avg loss':>9s} {'exp $/tr':>8s} {'max DD $':>8s} {'span':>6s} breaker")
for _, s in tbl[tbl.breaker].iterrows():
    out(f"{s.version:16s} {s.risk:4.2f}% {s.trades:6d} {s.wr:5.1f} {s.net:+8.0f} {s.ret:+6.2f}% {s.pf:6.2f} {s.avg_win:+8.0f} {s.avg_loss:+9.0f} {s.exp:+8.1f} {s.mtm_dd:8.0f} {s.years:5.1f}y " + (f"HIT {s.breach_at:%Y-%m-%d}" if s.breached else "not hit"))
out("\n=== B. WITHOUT the breaker (full 7.75-year history, shows what the breaker prevented) ===")
out(f"{'version':16s} {'risk':>5s} {'trades':>6s} {'WR%':>5s} {'net $':>9s} {'return':>8s} {'CAGR':>6s} {'PF($)':>6s} {'max DD $':>9s} {'DD %':>6s} {'DD days':>7s} {'Sharpe':>6s} {'final $':>9s}")
for _, s in tbl[~tbl.breaker].iterrows():
    out(f"{s.version:16s} {s.risk:4.2f}% {s.trades:6d} {s.wr:5.1f} {s.net:+9.0f} {s.ret:+7.2f}% {s.cagr:5.1f}% {s.pf:6.2f} {s.mtm_dd:9.0f} {s.mtm_dd_pct:5.1f}% {s.dd_days:7.0f} {s.sharpe:6.2f} {s.final:9.0f}")
out("\n=== C. detail at 0.5% risk, no breaker ===")
for name in VERS:
    s = tbl[(tbl.version == name) & (tbl.risk == 0.5) & (~tbl.breaker)].iloc[0]
    out(f"{name:16s} gross profit ${s.gp:+,.0f} | gross loss ${s.gl:+,.0f} | avg win ${s.avg_win:+,.0f} / avg loss ${s.avg_loss:+,.0f} | best ${s.best:+,.0f} worst ${s.worst:+,.0f} | "
        f"max win streak {s.max_w} / loss streak {s.max_l} | avg lots {s.lots:.2f} | avg hold {str(s.hold).split('.')[0]} | longest drawdown {s.dd_days:.0f} days")
out("\n=== D. net P&L by calendar year ($), 0.5% risk, no breaker ===")
yr = {}
for name, t in ledgers.items():
    led, _ = A.simulate(m1, t, 0.5, halt_on_breach=False)
    yr[name] = led.groupby(led.exit_time.dt.year).usd.sum()
out(pd.DataFrame(yr).fillna(0).round(0).astype(int).T.to_string())
out("\n=== E. by direction and exit reason (R-based ledger, full history) ===")
for name, t in ledgers.items():
    d = {("long" if k == 1 else "short"): E.stats(g) for k, g in t.groupby("dir")}
    rs = {E.REASONS[int(k)]: (len(g), round(g.r.mean(), 2)) for k, g in t.groupby("reason")}
    out(f"{name:16s} long n={d['long']['n']} PF {d['long']['pf']:.2f} | short n={d['short']['n']} PF {d['short']['pf']:.2f} | exits (count, mean R): {rs}")
os.makedirs(os.path.join(HERE, "results", "full_stats"), exist_ok=True)
open(os.path.join(HERE, "results", "full_profit_stats.txt"), "w").write("\n".join(lines))
tbl.drop(columns=["hold"]).to_csv(os.path.join(HERE, "results", "full_stats", "summary.csv"), index=False)
for name, t in ledgers.items():
    led, _ = A.simulate(m1, t, 0.5, halt_on_breach=False)
    led.to_csv(os.path.join(HERE, "results", "full_stats", f"trades_{name.split()[0].lower()}_{name.split()[1].strip('()').lower()}_risk0.5.csv"), index=False)
print("\nsaved results/full_profit_stats.txt, results/full_stats/summary.csv and trade-by-trade CSVs")
