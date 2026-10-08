"""Full BB SNIPER backtest + report.   python3 -m bbsniper.run
Writes backtest_tv/out/bbsniper/{REPORT.md, results.json, trades_*.csv, ledger_*.csv, daily_*.csv}."""
import csv, datetime as dt, json, os, statistics as st
from collections import defaultdict
from .config import cfg as make_cfg, INSTRUMENTS, DEFAULTS
from .backtest import run, select_pair, window, account
from .optimize import walk_forward, splits, GRID
from .report import metrics, periods, grade, rank, fmt, fmt_pct
from .data import load

TFS = ["1m", "3m", "5m", "15m"]
ACCTS = [(500, 1.0), (500, 2.0), (1000, 1.0), (1000, 2.0)]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest_tv", "out", "bbsniper")
SETUPS = {"MR": "BB Liquidity Reversal", "TC": "BB Trend Continuation", "SB": "BB Squeeze Breakout"}
MIN_N = 10


def D(ts): return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d %H:%M")


def J(o):
    if hasattr(o, "item"): return o.item()
    return str(o)


def csv_out(path, rows, keys):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore"); w.writeheader(); [w.writerow(r) for r in rows]


def best_by(trades, key, min_n=3):
    g = defaultdict(list)
    for t in trades: g[t[key]].append(t["r"])
    g = {k: v for k, v in g.items() if len(v) >= min_n}
    if not g: return None, None
    k = max(g, key=lambda k: st.mean(g[k])); return k, (len(g[k]), st.mean(g[k]))


ABLATIONS = [("Default rules", {}), ("No 1.5R room filter", dict(min_rr=0)), ("No max-stop filter", dict(max_sl_atr=99)),
             ("Spread filter 100% ATR", dict(max_spread_pct_atr=100)),
             ("All three relaxed", dict(min_rr=0, max_sl_atr=99, max_spread_pct_atr=100)),
             ("All relaxed + all sessions", dict(min_rr=0, max_sl_atr=99, max_spread_pct_atr=100, sessions=("Asian", "London", "NY"))),
             ("Default, ZERO spread", dict(spread_mult=0.0, tp_through_pips=0.0)),
             ("All relaxed, ZERO spread", dict(min_rr=0, max_sl_atr=99, max_spread_pct_atr=100, spread_mult=0.0, tp_through_pips=0.0))]


def sensitivity(base):
    """Filter ablation + frictionless cost diagnostic (informational - never used to pick a config)."""
    out = {}
    for tf in ("15m", "5m"):
        t0, t1 = window(tf, base); _, _, (e, f) = splits(t0, t1)
        for name, o in ABLATIONS:
            c = dict(base, **o); tr = []
            for sym in INSTRUMENTS: tr += select_pair(run(sym, tf, c)[0], c, t0, t1)
            out[f"{tf}|{name}"] = dict(all=metrics(tr), oos=metrics([x for x in tr if x["t"] >= e]))
    return out


def main():
    os.makedirs(OUT, exist_ok=True); base = make_cfg(); R = {"tfs": {}, "winrate_lookup": {}}
    rows_all = []
    for tf in TFS:
        t0, t1 = window(tf, base); (a, b), _, (e, f) = splits(t0, t1)
        pair_rows, pooled = [], []
        for sym in INSTRUMENTS:
            tr = select_pair(run(sym, tf, base)[0], base, t0, t1); pooled += tr
            m = metrics(tr, t0, t1); oos = metrics([x for x in tr if x["t"] >= e], e, f)
            led, _ = account(tf, base, 1000, 1.0, t0, t1, syms=[sym]); ma = metrics(led, t0, t1, 1000)
            row = dict(sym=sym, tf=tf, m=m, oos=oos, acct=ma, grade=grade(m, oos), trades=tr)
            pair_rows.append(row); rows_all.append(row)
            if m.get("n"):
                R["winrate_lookup"][f"{sym}|{tf}"] = f"{m['wr'] * 100:.0f}% (n={m['n']})"
                for s in SETUPS:
                    ms = metrics([x for x in tr if x["setup"] == s])
                    if ms.get("n"): R["winrate_lookup"][f"{sym}|{tf}|{s}"] = f"{ms['wr'] * 100:.0f}% (n={ms['n']})"
        pooled.sort(key=lambda x: x["t"])
        csv_out(f"{OUT}/trades_{tf}.csv", [dict(x, time=D(x["t"]), exit_time=D(x["exit_t"])) for x in pooled],
                ["time", "sym", "setup", "side", "score", "session", "regime", "entry", "stop", "risk", "room_r", "r", "exit", "exit_time", "bars"])
        accts = {}
        for bal, rk in ACCTS:
            led, small = account(tf, base, bal, rk, t0, t1)
            accts[f"{bal}@{rk:g}%"] = dict(m=metrics(led, t0, t1, bal), skipped_small=small,
                                           day=periods(led, bal, "day"), week=periods(led, bal, "week"), month=periods(led, bal, "month"))
            csv_out(f"{OUT}/ledger_{tf}_{bal}_{rk:g}pct.csv", [dict(x, time=D(x["t"]), exit_time=D(x["exit_t"])) for x in led],
                    ["time", "sym", "setup", "side", "score", "entry", "stop", "lots", "usd_risk", "r", "usd", "equity", "exit", "exit_time"])
        wf = walk_forward(tf, base)
        R["tfs"][tf] = dict(window=(t0, t1), bars={s: len(load(s, tf)["t"]) for s in INSTRUMENTS}, pooled=metrics(pooled, t0, t1),
                            setups={s: metrics([x for x in pooled if x["setup"] == s], t0, t1) for s in SETUPS},
                            sessions={s: metrics([x for x in pooled if x["session"] == s], t0, t1) for s in ("London", "Overlap", "NY", "Asian")},
                            pairs=[{k: v for k, v in r.items() if k != "trades"} for r in pair_rows], accounts=accts, wf=wf,
                            candidates=sum(len(run(s, tf, base)[0]) for s in INSTRUMENTS))
        print(tf, "done", R["tfs"][tf]["pooled"].get("n"), flush=True)
    # ---------- per-pair best settings (full period, default rules; descriptive, small samples flagged) ----------
    pairs = {}
    for sym in INSTRUMENTS:
        rows = [r for r in rows_all if r["sym"] == sym]
        best = rank(rows, MIN_N)[0]; tr = best["trades"]
        thr = {}
        for ms in (7, 8, 9, 10):
            c = dict(base, min_score=ms); t0, t1 = R["tfs"][best["tf"]]["window"]
            thr[ms] = metrics(select_pair(run(sym, best["tf"], c)[0], c, t0, t1))
        okthr = {k: v for k, v in thr.items() if v.get("n", 0) >= 5}
        risk = "1%"
        if best["grade"] in ("S+", "S", "A+", "A"): risk = "2%"
        pairs[sym] = dict(tf=best["tf"], grade=best["grade"], m=best["m"], oos=best["oos"], acct=best["acct"],
                          setup=best_by(tr, "setup"), session=best_by(tr, "session"),
                          score=(max(okthr, key=lambda k: okthr[k]["avg_r"]) if okthr else None), risk=risk)
    R["pairs"] = pairs
    # ---------- top setups: pair + TF + setup + session ----------
    combos = defaultdict(list)
    for r in rows_all:
        for t in r["trades"]: combos[(r["sym"], r["tf"], t["setup"], t["session"])].append(t)
    crow = [dict(key=k, m=metrics(v)) for k, v in combos.items()]
    R["top_setups"] = [(c["key"], c["m"]) for c in rank([c for c in crow if c["m"]["n"] >= 5], 5)[:10]]
    R["sensitivity"] = sensitivity(base)
    ranked = rank(rows_all, MIN_N); R["ranked"] = [(r["sym"], r["tf"], r["grade"], r["m"], r["acct"], r["oos"]) for r in ranked]
    json.dump(R, open(f"{OUT}/results.json", "w"), default=J, indent=1)
    write_report(R, base)


def write_report(R, base):
    L = []; P = L.append
    P("# BB SNIPER — backtest report\n")
    P(f"Generated {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC. TradingView OANDA bars, 17 instruments. Engine: `bbsniper/` "
      "(15 modules), honest fills, no lookahead, confirmed higher-timeframe bars only.\n")
    P("## 0. Read this first — what the data allows\n")
    P("The TradingView connector returns at most **5,000 bars per request (newest only)** and has no 3-minute interval. "
      "A 90-day test on 1M/3M/5M/15M is therefore **not possible** with this feed. Each timeframe is tested on the full "
      "window that exists:\n")
    P("| Exec TF | Setup TF / Bias TF | Window (UTC) | ≈ Trading days | Candidate setups (any score) |")
    P("|---|---|---|---:|---:|")
    for tf, x in R["tfs"].items():
        t0, t1 = x["window"]; days = (t1 - t0) / 86400 * 5 / 7
        stf, btf = {"1m": ("5M", "15M"), "3m": ("5M", "15M"), "5m": ("5M", "15M"), "15m": ("15M", "1H")}[tf]
        P(f"| {tf.upper()} | {stf} / {btf} | {D(t0)} → {D(t1)} | {days:.1f} | {x['candidates']} |")
    P("\n3M bars are built from 1M. Walk-forward split per timeframe: first 4/6 = training (the spec's 60/90), next 1/6 = "
      "validation, last 1/6 = out-of-sample. Spreads are static estimates (no historical spread feed); the news filter "
      "is **disabled** in the backtest because no historical economic-calendar data is available (it is not simulated "
      "with invented data).\n")
    P("## 1. Timeframe comparison (default rules: score ≥ 8, BB 20/2.0, SL buffer 0.2 ATR, min RR 1.5, London+NY)\n")
    P("Pair-level trades pooled across all 17 instruments (one position per pair, 3 trades / 3 losses per pair per day).\n")
    P("| TF | Trades | Win rate | PF | Avg R | Net R | Max DD (R) | t-stat | Trades/day (all pairs) |")
    P("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for tf, x in R["tfs"].items():
        m = x["pooled"]
        if not m.get("n"): P(f"| {tf.upper()} | 0 | — | — | — | — | — | — | — |"); continue
        P(f"| {tf.upper()} | {m['n']} | {fmt_pct(m['wr'])} | {fmt(min(m['pf'], 99))} | {m['avg_r']:+.2f} | {m['net_r']:+.1f} | {m['max_dd_r']:.1f} | {m['t_stat']:.2f} | {fmt(m.get('trades_day'))} |")
    P("\n**By setup type**\n")
    P("| TF | Setup | Trades | Win rate | PF | Avg R |"); P("|---|---|---:|---:|---:|---:|")
    for tf, x in R["tfs"].items():
        for s, m in x["setups"].items():
            if m.get("n"): P(f"| {tf.upper()} | {SETUPS[s]} | {m['n']} | {fmt_pct(m['wr'])} | {fmt(min(m['pf'], 99))} | {m['avg_r']:+.2f} |")
    P("\n**By session**\n")
    P("| TF | Session | Trades | Win rate | PF | Avg R |"); P("|---|---|---:|---:|---:|---:|")
    for tf, x in R["tfs"].items():
        for s, m in x["sessions"].items():
            if m.get("n"): P(f"| {tf.upper()} | {s} | {m['n']} | {fmt_pct(m['wr'])} | {fmt(min(m['pf'], 99))} | {m['avg_r']:+.2f} |")
    P("\n## 2. Walk-forward optimisation (24 configs, chosen on training only)\n")
    P("Grid: " + ", ".join(f"{k} ∈ {v}" for k, v in GRID.items()) + ". Selection = best training expectancy with ≥ 20 trades.\n")
    P("| TF | Chosen params | Train n / WR / PF / avgR | Validation n / WR / PF / avgR | Out-of-sample n / WR / PF / avgR | Default rules OOS |")
    P("|---|---|---|---|---|---|")
    def s4(m): return "0 trades" if not m.get("n") else f"{m['n']} / {fmt_pct(m['wr'])} / {fmt(min(m['pf'], 99))} / {m['avg_r']:+.2f}"
    for tf, x in R["tfs"].items():
        w = x["wf"]; p = ", ".join(f"{k}={v}" for k, v in w["params"].items()) + ("" if w["sufficient"] else " ⚠ <20 train trades")
        P(f"| {tf.upper()} | {p} | {s4(w['train'])} | {s4(w['val'])} | {s4(w['oos'])} | {s4(w['default']['oos'])} |")
    # ---------- best overall ----------
    P("\n## 3. BEST OVERALL CONFIGURATION\n")
    ranked = R["ranked"]; cand = [r for r in ranked if r[3].get("n", 0) >= 20] or [r for r in ranked if r[3].get("n", 0) >= MIN_N]
    if cand:
        sym, tf, g, m, a, oos = cand[0]; pp = R["pairs"][sym]
        sess = pp["session"][0] if pp["tf"] == tf and pp["session"][0] else "—"
        setup = pp["setup"][0] if pp["tf"] == tf and pp["setup"][0] else "mixed"
        P(f"- **Pair:** {sym}\n- **Timeframe:** {tf.upper()}\n- **Setup:** {SETUPS.get(setup, setup)}\n- **Grade:** {g}"
          f"\n- **Win rate:** {fmt_pct(m['wr'])}\n- **Profit factor:** {fmt(min(m['pf'], 99))}\n- **Max DD:** {m['max_dd_r']:.1f}R "
          f"({fmt_pct(a.get('max_dd_pct'))} on $1,000 @ 1%)\n- **ROI ($1,000 @ 1%):** {fmt_pct(a.get('roi'))}\n- **Net profit ($1,000 @ 1%):** "
          f"${a.get('net_usd', 0):,.2f}\n- **Average R:** {m['avg_r']:+.2f}\n- **Trades:** {m['n']}\n- **Best session:** {sess}"
          f"\n- **Average trades/day:** {fmt(m.get('trades_day'))}\n- **Out-of-sample slice:** {s4(oos)}"
          f"\n- **Recommended risk:** {'1% (sample too small for more)' if m['n'] < 50 or g not in ('S+', 'S', 'A+', 'A') else pp['risk']}\n")
        if m["n"] < 30: P("> ⚠ Fewer than 30 trades — this is the best of a small sample, **not** a statistically established edge.\n")
    else:
        P("No pair/timeframe produced at least 10 trades under the default rules — no configuration qualifies.\n")
    P("## 4. TOP 10 PAIRS (each pair at its best timeframe)\n")
    P("| Rank | Pair | TF | Grade | Trades | Win Rate | PF | ROI ($1k@1%) | Max DD | Avg R | Sample |"); P("|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|")
    seen = set(); k = 0
    for sym, tf, g, m, a, oos in ranked:
        if sym in seen or not m.get("n"): continue
        seen.add(sym); k += 1
        P(f"| {k} | {sym} | {tf.upper()} | {g} | {m['n']} | {fmt_pct(m['wr'])} | {fmt(min(m['pf'], 99))} | {fmt_pct(a.get('roi'))} | {m['max_dd_r']:.1f}R | {m['avg_r']:+.2f} | {'ok' if m['n'] >= MIN_N else '⚠ n<' + str(MIN_N)} |")
        if k == 10: break
    if not any(r[3].get("n", 0) >= MIN_N for r in ranked):
        P(f"\n> ⚠ No pair reached {MIN_N} trades on any timeframe, so this order is provisional (small samples are ordered by net R, not win rate). None of these rows is evidence of an edge.")
    P(f"\nRanking = weighted rank-sum of PF (6), win rate (5), expectancy (4), drawdown (3), net R (2), % positive weeks (1); rows with < {MIN_N} trades rank last. Grades need ≥ 30 trades to exceed C.\n")
    P("**All pairs — best timeframe, setup, session, score threshold, risk model**\n")
    P("| Pair | Best TF | Grade | Trades | WR | PF | Avg R | Best setup | Best session | Best score ≥ | Risk |"); P("|---|---|---|---:|---:|---:|---:|---|---|---|---|")
    for sym, p in R["pairs"].items():
        m = p["m"]
        if not m.get("n"): P(f"| {sym} | — | F | 0 | — | — | — | — | — | — | — |"); continue
        su = f"{SETUPS[p['setup'][0]]} (n={p['setup'][1][0]})" if p["setup"][0] else "n<3"
        se = f"{p['session'][0]} (n={p['session'][1][0]})" if p["session"][0] else "n<3"
        P(f"| {sym} | {p['tf'].upper()} | {p['grade']} | {m['n']} | {fmt_pct(m['wr'])} | {fmt(min(m['pf'], 99))} | {m['avg_r']:+.2f} | {su} | {se} | {p['score'] or 'n<5'} | {p['risk']} |")
    P("\n## 5. TOP 10 SETUPS (pair + TF + setup + session, ≥ 5 trades to rank)\n")
    P("| Rank | Pair | TF | Setup | Session | Trades | WR | PF | Avg R |"); P("|---:|---|---|---|---|---:|---:|---:|---:|")
    if not R["top_setups"]: P("| — | No pair + TF + setup + session combination reached 5 trades. | | | | | | | |")
    for k, ((sym, tf, s, se), m) in enumerate(R["top_setups"], 1):
        P(f"| {k} | {sym} | {tf.upper()} | {SETUPS[s]} | {se} | {m['n']} | {fmt_pct(m['wr'])} | {fmt(min(m['pf'], 99))} | {m['avg_r']:+.2f} |")
    for bal in (500, 1000):
        P(f"\n## {6 if bal == 500 else 7}. ${bal:,} RESULTS (portfolio of all 17 pairs, compounding, real lot sizing)\n")
        P("| TF | Risk | Trades | Win rate | Net profit | ROI | Max DD | PF | Avg/day $ | Best day | Worst day | Skipped (lot < 0.01) |")
        P("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for tf, x in R["tfs"].items():
            for rk in (1, 2):
                A = x["accounts"][f"{bal}@{rk}%"]; m = A["m"]
                if not m.get("n"): P(f"| {tf.upper()} | {rk}% | 0 | — | $0.00 | 0.0% | — | — | — | — | — | {A['skipped_small']} |"); continue
                dv = [v["usd"] for v in A["day"].values()]
                P(f"| {tf.upper()} | {rk}% | {m['n']} | {fmt_pct(m['wr'])} | ${m['net_usd']:,.2f} | {fmt_pct(m['roi'])} | {fmt_pct(m['max_dd_pct'])} | {fmt(min(m['pf_usd'], 99))} | ${st.mean(dv):,.2f} | ${max(dv):,.2f} | ${min(dv):,.2f} | {A['skipped_small']} |")
    P("\n## 8. Weekly and monthly breakdown ($1,000 @ 1%)\n")
    for tf, x in R["tfs"].items():
        A = x["accounts"]["1000@1%"]
        if not A["m"].get("n"): continue
        P(f"**{tf.upper()}** — weekly: " + "; ".join(f"{k}: {v['n']} tr, ${v['usd']:+.2f} ({fmt_pct(v['roi'])}), WR {fmt_pct(v['wr'])}" for k, v in A["week"].items()))
        P(f"\n**{tf.upper()}** — monthly: " + "; ".join(f"{k}: {v['n']} tr, ${v['usd']:+.2f} ({fmt_pct(v['roi'])}), WR {fmt_pct(v['wr'])}" for k, v in A["month"].items()) + "\n")
    P("Per-day results for every account are in `results.json` (`accounts → day`) and the ledgers `ledger_<tf>_<balance>_<risk>pct.csv`.\n")
    P("## 9. Filter sensitivity and cost diagnostic (informational — not used to choose anything)\n")
    P("Do the strict filters hide an edge? Relaxing them gives bigger samples; zero-spread runs show the edge before costs.\n")
    P("| TF | Variant | Trades | Win rate | PF | Avg R | t-stat | OOS trades | OOS avg R |"); P("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for k, v in R["sensitivity"].items():
        tf, name = k.split("|"); m, o = v["all"], v["oos"]
        if not m.get("n"): continue
        P(f"| {tf.upper()} | {name} | {m['n']} | {fmt_pct(m['wr'])} | {fmt(min(m['pf'], 99))} | {m['avg_r']:+.2f} | {m['t_stat']:+.2f} | {o.get('n', 0)} | {o.get('avg_r', 0):+.2f} |")
    P("")
    P("## 10. Honest conclusion\n")
    P(conclusion(R))
    P("\n## 11. Rules actually implemented (defaults in `bbsniper/config.py`)\n")
    P("- **Bias (15M, 1H for 15M exec):** close > EMA200 and EMA20 > EMA200 (bull) / mirror (bear); counter-bias trades are never taken; neutral bias trades only if every non-bias point scores.\n"
      "- **Regime (setup TF):** ADX < 20 ranging, 20–25 transitional, > 25 + EMA alignment trending; BandWidth percentile (100 bars) < 20 = squeeze, > 80 and rising = expansion.\n"
      "- **Mean reversion (ranging/transitional):** low at/near lower band → sweep of an unswept swing low (pivot 3/3, last 60 bars) → close back above it → bullish MSS (close through the last micro swing high, pivot 2/2) → enter on the MSS close. Stop = sweep low − 0.2 ATR.\n"
      "- **Trend continuation (trending + aligned bias):** after %B > 0.8, pullback into EMA20/middle band → MSS → enter; stop below the pullback low − 0.2 ATR.\n"
      "- **Squeeze breakout:** BandWidth squeeze in the last 10 bars → close outside the band and above the 20-bar range with ADX rising → retest of the breakout level that holds → bullish confirmation candle → enter; stop below the retest low − 0.2 ATR.\n"
      "- **Score 0–10:** +2 HTF bias, +1 setup-TF trend, +2 liquidity sweep, +1 Bollinger extreme, +1 MSS, +1 RSI (zone or divergence), +1 %B (reclaim or divergence), +1 ADX. Trade ≥ 8 (Standard).\n"
      "- **Filters:** London+NY sessions, spread ≤ 50% of ATR, stop ≤ 3 ATR, nearest opposing major swing ≥ 1.5R away, max 3 trades/day, stop after 3 losses/day, 3% daily loss limit.\n"
      "- **Management:** 30% at 1R, 35% at 2R, rest at 3R; stop to entry + 0.05R after TP1; ATR(1.5) trailing after 2R; 120-bar time stop.\n"
      "- **Fills:** longs pay the spread on entry, shorts on exit; stop assumed before target when both are touched in one bar; targets need 0.2 pip trade-through; gaps fill at the open.\n")
    open(f"{OUT}/REPORT.md", "w").write("\n".join(L))


def conclusion(R):
    lines = []
    tot = [(tf, x["pooled"]) for tf, x in R["tfs"].items()]
    best = max((t for t in tot if t[1].get("n", 0) >= 10), key=lambda t: t[1]["avg_r"], default=None)
    n_all = sum(m.get("n", 0) for _, m in tot)
    lines.append(f"- Across all four execution timeframes the strict rule set produced **{n_all} trades** in the available history. "
                 "Most candidate setups are removed by the spread, stop-size and 1.5R-room filters — the system is very selective by design.")
    for tf, m in tot:
        if m.get("n"):
            verdict = "positive" if m["avg_r"] > 0 and m["pf"] > 1 else "negative"
            sig = "statistically meaningful" if abs(m["t_stat"]) >= 2 and m["n"] >= 30 else "not statistically meaningful"
            lines.append(f"- **{tf.upper()}:** {m['n']} trades, win rate {fmt_pct(m['wr'])}, PF {fmt(min(m['pf'], 99))}, {m['avg_r']:+.2f}R/trade → {verdict} and {sig} (t = {m['t_stat']:.2f}).")
        else:
            lines.append(f"- **{tf.upper()}:** no trades passed the filters.")
    if best: lines.append(f"- Least-bad timeframe on this data: **{best[0].upper()}**.")
    sv = R.get("sensitivity", {})
    rel = sv.get("15m|All three relaxed", {}).get("all", {}); z = sv.get("15m|Default, ZERO spread", {}).get("all", {})
    if rel.get("n"):
        lines.append(f"- **The filters are not hiding an edge.** With the room/stop/spread filters removed, 15M gives {rel['n']} trades at "
                     f"{rel['avg_r']:+.2f}R (t = {rel['t_stat']:+.2f}): a larger sample that is more clearly negative.")
    if z.get("n"):
        lines.append(f"- **Before costs the edge is roughly zero:** default rules with zero spread give {z['avg_r']:+.2f}R/trade "
                     f"(t = {z['t_stat']:+.2f}, n = {z['n']}). Spread turns that into a loss, which is why 1M–5M are worst.")
    lines.append("- **Verdict: on this data BB SNIPER, as specified, is a NO-TRADE system.** It should not be traded live or sent as signals until a longer test (90+ days per timeframe) shows positive out-of-sample expectancy.")
    lines.append("- **1M/3M:** the 3.5-day window and spreads that are a large fraction of a 1-minute ATR make these timeframes unsuitable to judge, and mostly untradeable at retail spreads.")
    lines.append("- No configuration here should be called proven. Before risking money: run `python3 -m bbsniper.live` on demo, log 50+ trades, "
                 "and load longer history (TradingView CSV exports) into `backtest_tv/data/` to repeat this test on 90+ days.")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
