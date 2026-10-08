"""Run the 90-day study: combos x score tiers, IS/OOS selection, pair ranking, account sims."""
import json, csv, random, statistics as st, datetime as dt, sys, os
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
import engine as E

OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
COMBOS = {  # (entry/setup TF, bias TF)
    "Scalp  H4 bias -> M15 entry": ("15m", "4h"),
    "Scalp  H1 bias -> M15 entry": ("15m", "1h"),
    "Intra  H4 bias -> M30 entry": ("30m", "4h"),
    "Intra  H1 bias -> M30 entry": ("30m", "1h"),
    "Intra  H4 bias -> H1 entry": ("1h", "4h"),
    "Intra  D1 bias -> H1 entry": ("1h", "1D"),
}
TIERS = [50, 60, 70, 80, 90]
MAX_FILLS_PER_DAY = 4


def day(ts): return dt.datetime.fromtimestamp(ts, dt.UTC).date()


def window():
    bars = E.load("EURUSD", "1h")
    days = sorted({day(b[0]) for b in bars if day(b[0]).weekday() < 5})
    last_full = [d for d in days if d < day(bars[-1][0])][-1]
    days = [d for d in days if d <= last_full]
    start = days[-90]
    ts = lambda d: int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp())
    return start, last_full, ts(start), ts(last_full) + 86400


def portfolio(trades):
    """One open position per symbol, max N new fills per UTC day, in fill order."""
    trades = sorted(trades, key=lambda x: (x["fill_t"], x["sym"]))
    busy, per_day, taken = {}, defaultdict(int), []
    for t in trades:
        if busy.get(t["sym"], 0) > t["fill_t"]: continue
        d = day(t["fill_t"])
        if per_day[d] >= MAX_FILLS_PER_DAY: continue
        busy[t["sym"]] = t["exit_t"]; per_day[d] += 1; taken.append(t)
    return taken


def stats(tr):
    if not tr: return dict(n=0)
    rs = [t["r"] for t in sorted(tr, key=lambda x: x["exit_t"])]
    w = [r for r in rs if r > 0]; l = [r for r in rs if r <= 0]
    eq = pk = dd = 0; cw = cl = mw = ml = 0
    for r in rs:
        eq += r; pk = max(pk, eq); dd = max(dd, pk - eq)
        if r > 0: cw += 1; cl = 0
        else: cl += 1; cw = 0
        mw, ml = max(mw, cw), max(ml, cl)
    weeks = defaultdict(float)
    for t in tr: weeks[day(t["exit_t"]).isocalendar()[:2]] += t["r"]
    return dict(n=len(rs), wr=len(w) / len(rs), pf=(sum(w) / -sum(l)) if l and sum(l) < 0 else float("inf"),
                avg_r=sum(rs) / len(rs), net_r=sum(rs), max_dd_r=dd, max_cw=mw, max_cl=ml,
                avg_win=(sum(w) / len(w)) if w else 0, avg_loss=(sum(l) / len(l)) if l else 0,
                pos_weeks=sum(1 for v in weeks.values() if v > 0) / max(1, len(weeks)))


def accounts(tr, start_bal, pct):
    """Compounding sim: risk = pct x equity at fill; P/L realized at exit."""
    ev = sorted([(t["fill_t"], 0, i) for i, t in enumerate(tr)] + [(t["exit_t"], 1, i) for i, t in enumerate(tr)])
    eq = start_bal; risk_at = {}; pk = eq; dd = 0; daily = defaultdict(lambda: [0.0, 0, 0, 0.0, None])
    for ts, kind, i in ev:
        if kind == 0: risk_at[i] = eq * pct; continue
        pnl = tr[i]["r"] * risk_at[i]; d = day(ts)
        rec = daily[d]
        if rec[4] is None: rec[4] = eq
        eq += pnl; pk = max(pk, eq); dd = max(dd, (pk - eq) / pk)
        rec[0] += pnl; rec[1] += 1; rec[2] += tr[i]["r"] > 0; rec[3] += tr[i]["r"]
    return eq, dd, daily


def ror(rs, pct, ruin=0.5, sims=5000, horizon=250):
    """Monte-Carlo bootstrap: P(equity ever falls >= ruin from start) over `horizon` trades."""
    if not rs: return None
    rnd = random.Random(7); hit = 0
    for _ in range(sims):
        eq = 1.0
        for _ in range(horizon):
            eq *= 1 + pct * rnd.choice(rs)
            if eq <= 1 - ruin: hit += 1; break
    return hit / sims


def main():
    d0, d1, T0, T1 = window()
    print("window", d0, "->", d1)
    allt = {}
    for name, (etf, btf) in COMBOS.items():
        tr = []
        for s in E.SYMBOLS:
            tr += [t for t in E.find_trades(s, etf, btf, start_ts=T0, end_ts=T1) if t["exit_t"] < T1]
        allt[name] = tr
        print(name, "raw signals filled:", len(tr))
    json.dump({k: v for k, v in allt.items()}, open(f"{OUT}/raw_trades.json", "w"))
    # IS / OOS split per combo on its own effective window (M15 data starts later)
    grid = []
    for name, tr in allt.items():
        if not tr: continue
        a = min(t["signal_t"] for t in tr); b = T1
        cut = a + 0.6 * (b - a)
        for tier in TIERS:
            sel = portfolio([t for t in tr if t["score"] >= tier])
            IS = [t for t in sel if t["signal_t"] < cut]; OOS = [t for t in sel if t["signal_t"] >= cut]
            grid.append(dict(combo=name, tier=tier, eff_start=str(day(a)), cut=str(day(cut)),
                             full=stats(sel), IS=stats(IS), OOS=stats(OOS)))
    json.dump(grid, open(f"{OUT}/grid.json", "w"), default=str, indent=1)
    # selection on IS only: max IS net R subject to IS n>=15 and IS PF>1
    cands = [g for g in grid if g["IS"].get("n", 0) >= 15 and g["IS"]["pf"] > 1]
    best = max(cands, key=lambda g: g["IS"]["net_r"]) if cands else max(grid, key=lambda g: g["full"].get("net_r", -1e9))
    print("selected", best["combo"], best["tier"], "IS", best["IS"], "OOS", best["OOS"])
    json.dump(best, open(f"{OUT}/selected.json", "w"), default=str, indent=1)
    sel = portfolio([t for t in allt[best["combo"]] if t["score"] >= best["tier"]])
    with open(f"{OUT}/trades_selected.csv", "w", newline="") as f:
        cols = ["date", "sym", "session", "side", "entry_tf", "bias_tf", "entry", "stop", "tp1", "tp2", "rr", "risk_pips",
                "setup", "mss", "pool", "tdi", "tdi_os", "div", "pd", "dol_room", "score", "exit", "r", "mfe", "mae"]
        w = csv.writer(f); w.writerow(cols)
        for t in sorted(sel, key=lambda x: x["fill_t"]):
            w.writerow([dt.datetime.fromtimestamp(t["fill_t"], dt.UTC).strftime("%Y-%m-%d %H:%M")] + [t[c] for c in cols[1:]])
    # pair stats on selected config + on every combo (best combo per pair)
    pairs = {}
    for s in E.SYMBOLS:
        row = {}
        for name, tr in allt.items():
            p = portfolio([t for t in tr if t["sym"] == s and t["score"] >= best["tier"]])
            row[name] = stats(p)
        pairs[s] = row
    json.dump(pairs, open(f"{OUT}/pairs.json", "w"), default=str, indent=1)
    # confluence breakdown on all filled signals of the selected combo (score>=50)
    base = portfolio(allt[best["combo"]])
    conf = {}
    for key, fn in [("tdi", lambda t: t["tdi"]), ("div", lambda t: t["div"]), ("session", lambda t: t["session"]),
                    ("setup", lambda t: t["setup"]), ("in_pd", lambda t: t["in_pd"]), ("pool", lambda t: t["pool"]),
                    ("tdi_os", lambda t: t["tdi_os"])]:
        g = defaultdict(list)
        for t in base: g[str(fn(t))].append(t)
        conf[key] = {k: stats(v) for k, v in g.items()}
    json.dump(conf, open(f"{OUT}/confluence.json", "w"), default=str, indent=1)
    # accounts
    acc = {}
    rs = [t["r"] for t in sel]
    for bal in (500, 1000):
        for pct in (0.01, 0.02):
            end, dd, daily = accounts(sel, bal, pct)
            days = sorted(daily)
            dpl = [daily[d][0] for d in days]
            weeks, months = defaultdict(lambda: [0.0, 0, 0, None]), defaultdict(lambda: [0.0, 0, 0, None, []])
            for d in days:
                pl, n, wn, rr, sb = daily[d]
                wk = weeks[d.isocalendar()[:2]]; mo = months[(d.year, d.month)]
                if wk[3] is None: wk[3] = sb
                if mo[3] is None: mo[3] = sb
                wk[0] += pl; wk[1] += n; wk[2] += wn; mo[0] += pl; mo[1] += n; mo[2] += wn
            acc[f"{bal}@{int(pct*100)}%"] = dict(
                start=bal, end=end, net=end - bal, roi=(end - bal) / bal, max_dd=dd,
                trading_days=len(days), avg_trades_day=sum(daily[d][1] for d in days) / max(1, len(days)),
                avg_daily_pl=st.mean(dpl) if dpl else 0, best_day=max(dpl) if dpl else 0, worst_day=min(dpl) if dpl else 0,
                avg_daily_roi=st.mean([daily[d][0] / daily[d][4] for d in days]) if days else 0,
                weeks={f"{k[0]}-W{k[1]:02d}": dict(pl=v[0], n=v[1], wr=v[2] / v[1] if v[1] else 0, roi=v[0] / v[3]) for k, v in sorted(weeks.items())},
                months={f"{k[0]}-{k[1]:02d}": dict(pl=v[0], n=v[1], wr=v[2] / v[1] if v[1] else 0, roi=v[0] / v[3]) for k, v in sorted(months.items())},
                ror_50dd=ror(rs, pct))
    json.dump(acc, open(f"{OUT}/accounts.json", "w"), default=str, indent=1)
    print(json.dumps({k: {x: v[x] for x in ("end", "roi", "max_dd", "ror_50dd")} for k, v in acc.items()}, default=str, indent=1))


if __name__ == "__main__":
    main()
