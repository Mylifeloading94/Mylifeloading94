"""Module 14 - reporting: metrics, period breakdowns, ranking and grading."""
import datetime as dt, math, statistics as st
from collections import defaultdict


def _d(ts): return dt.datetime.fromtimestamp(ts, dt.UTC)


def streaks(rs):
    bw = bl = cw = cl = 0
    for r in rs:
        if r > 0: cw += 1; cl = 0
        else: cl += 1; cw = 0
        bw, bl = max(bw, cw), max(bl, cl)
    return bw, bl


def metrics(trades, t0=None, t1=None, balance=None, money="usd"):
    """Metrics in R always; in $ too when trades carry `usd` (account ledgers)."""
    n = len(trades)
    if n == 0: return dict(n=0)
    rs = [t["r"] for t in trades]; w = [r for r in rs if r > 0]; l = [r for r in rs if r <= 0]
    eq = pk = dd = 0.0
    for r in rs: eq += r; pk = max(pk, eq); dd = max(dd, pk - eq)
    bw, bl = streaks(rs)
    days = (t1 - t0) / 86400 * 5 / 7 if t0 and t1 else None                 # trading days in window
    m = dict(n=n, wins=len(w), losses=len(l), wr=len(w) / n, avg_win_r=st.mean(w) if w else 0, avg_loss_r=st.mean(l) if l else 0,
             pf=(sum(w) / -sum(l)) if l and sum(l) < 0 else (99.0 if w else 0), net_r=sum(rs), avg_r=st.mean(rs),
             max_dd_r=dd, max_consec_w=bw, max_consec_l=bl, best_r=max(rs), worst_r=min(rs),
             avg_minutes=st.mean((t["exit_t"] - t["t"]) / 60 for t in trades),
             t_stat=st.mean(rs) / st.pstdev(rs) * math.sqrt(n) if n > 2 and st.pstdev(rs) > 0 else 0)
    if days:
        m.update(trades_day=n / days, trades_week=n / days * 5, trades_month=n / days * 21)
    wk = defaultdict(float)
    for t in trades: wk[_d(t["exit_t"]).isocalendar()[:2]] += t["r"]
    m["pos_weeks"] = sum(v > 0 for v in wk.values()) / len(wk) if wk else 0
    if balance and "usd" in trades[0]:
        u = [t["usd"] for t in trades]; uw = [x for x in u if x > 0]; ul = [x for x in u if x <= 0]
        eq = pk = balance; ddp = ddu = 0.0
        for x in u: eq += x; pk = max(pk, eq); ddu = max(ddu, pk - eq); ddp = max(ddp, (pk - eq) / pk)
        daily = defaultdict(float)
        for t in trades: daily[_d(t["exit_t"]).date()] += t["usd"]
        dv = list(daily.values()); rets = [v / balance for v in dv]
        m.update(net_usd=sum(u), end=balance + sum(u), roi=sum(u) / balance, avg_win_usd=st.mean(uw) if uw else 0,
                 avg_loss_usd=st.mean(ul) if ul else 0, pf_usd=(sum(uw) / -sum(ul)) if ul and sum(ul) < 0 else 99.0,
                 max_dd_usd=ddu, max_dd_pct=ddp, best_usd=max(u), worst_usd=min(u), expectancy_usd=st.mean(u),
                 sharpe=(st.mean(rets) / st.pstdev(rets) * math.sqrt(252)) if len(rets) >= 10 and st.pstdev(rets) > 0 else None)
    return m


def periods(trades, balance, key):
    """Per day / ISO week / month: trades, wins, losses, $ profit, ROI (vs starting balance), win rate."""
    g = defaultdict(lambda: [0, 0, 0, 0.0])
    for t in trades:
        d = _d(t["exit_t"]); k = d.date().isoformat() if key == "day" else (f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}" if key == "week" else d.strftime("%Y-%m"))
        x = g[k]; x[0] += 1; x[1] += t["r"] > 0; x[2] += t["r"] <= 0; x[3] += t.get("usd", 0.0)
    return {k: dict(n=v[0], wins=v[1], losses=v[2], usd=round(v[3], 2), roi=v[3] / balance if balance else None,
                    wr=v[1] / v[0]) for k, v in sorted(g.items())}


def grade(m, oos=None):
    """Grade with a sample-size gate: fewer than 30 trades can never grade above C."""
    if not m or m.get("n", 0) == 0: return "F"
    n, pf, ar, dd = m["n"], m["pf"], m["avg_r"], m["max_dd_r"]
    opf = oos.get("pf", 0) if oos and oos.get("n", 0) >= 10 else None
    def oos_ok(x): return opf is not None and opf >= x
    if n >= 100 and pf >= 2.0 and ar >= 0.40 and dd <= 6 and oos_ok(1.5): return "S+"
    if n >= 60 and pf >= 1.8 and ar >= 0.30 and oos_ok(1.3): return "S"
    if n >= 50 and pf >= 1.5 and ar >= 0.20 and oos_ok(1.2): return "A+"
    if n >= 40 and pf >= 1.3 and ar >= 0.12 and oos_ok(1.0): return "A"
    if n >= 30 and pf >= 1.15 and ar > 0.05: return "B"
    if pf >= 1.0: return "C"
    if pf >= 0.85: return "D"
    return "F"


def rank(rows, min_n=10):
    """Rank by PF, win rate, expectancy, drawdown, ROI, consistency (weighted rank-sum 6..1).
    Rows with fewer than min_n trades are ranked after all qualified rows."""
    ok = [r for r in rows if r["m"].get("n", 0) >= min_n]; rest = [r for r in rows if r not in ok]
    keys = [("pf", 6, True), ("wr", 5, True), ("avg_r", 4, True), ("max_dd_r", 3, False), ("net_r", 2, True), ("pos_weeks", 1, True)]
    score = defaultdict(float)
    for k, wgt, hi in keys:
        for pos, r in enumerate(sorted(ok, key=lambda r: r["m"][k], reverse=hi)): score[id(r)] += wgt * pos
    ok.sort(key=lambda r: score[id(r)])
    rest.sort(key=lambda r: -r["m"].get("net_r", -99) if r["m"].get("n") else 99)   # small samples: by net R
    return ok + rest


def fmt_pct(x): return "—" if x is None else f"{x * 100:.1f}%"
def fmt(x, nd=2): return "—" if x is None else f"{x:.{nd}f}"
