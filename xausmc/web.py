"""
HTML dashboard + a tiny built-in web server (spec §2 / §13 / §14 / §15).

The page refreshes itself every 60 seconds, in step with the scanner, and each
render is produced from a fresh scan — the browser never shows a price the
engine has not just re-derived.
"""
from __future__ import annotations

import html
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .chart import (C_ENTRY, C_INVALID, C_STOP, C_TARGET, svg_chart, tradingview_widget)
from .engine import Engine, ScanResult
from .performance import Report, build as build_report
from .setups import Setup
from .stats import DISCLAIMER, StatsStore


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _ts(ts) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else "—"


CSS = f"""
:root {{
  --bg:#0d1117; --panel:#161b22; --line:#232838; --text:#c9d1d9; --dim:#7d8590;
  --entry:{C_ENTRY}; --stop:{C_STOP}; --target:{C_TARGET}; --invalid:{C_INVALID};
  --up:#26a69a; --down:#ef5350; --warn:#f0b429;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
  font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
a {{ color:var(--entry); }}
.wrap {{ max-width:1240px; margin:0 auto; padding:18px 16px 64px; }}
h1 {{ font-size:19px; margin:0 0 2px; letter-spacing:.06em; }}
h2 {{ font-size:12px; letter-spacing:.16em; color:var(--dim); text-transform:uppercase;
  margin:26px 0 10px; font-weight:600; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
.grid {{ display:grid; gap:14px; }}
.g2 {{ grid-template-columns:1fr 1fr; }}
.g3 {{ grid-template-columns:repeat(3,1fr); }}
@media(max-width:900px){{ .g2,.g3 {{ grid-template-columns:1fr; }} }}
.badge {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:11px;
  font-weight:700; letter-spacing:.08em; }}
.b-live {{ background:rgba(34,197,94,.16); color:var(--target); }}
.b-warn {{ background:rgba(240,180,41,.16); color:var(--warn); }}
.b-dead {{ background:rgba(255,77,77,.16); color:var(--stop); }}
.b-grey {{ background:rgba(154,164,178,.16); color:var(--invalid); }}
.price {{ font-size:34px; font-weight:700; letter-spacing:-.02em; }}
.dim {{ color:var(--dim); }}
.rowline {{ display:flex; justify-content:space-between; gap:12px; padding:5px 0;
  border-bottom:1px solid var(--line); }}
.rowline:last-child {{ border-bottom:0; }}
.k {{ color:var(--dim); }}
.v {{ font-weight:600; }}
.entry {{ color:var(--entry); }} .stop {{ color:var(--stop); }}
.target {{ color:var(--target); }} .invalid {{ color:var(--invalid); }}
.dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:7px;
  vertical-align:middle; }}
.d-entry{{background:var(--entry)}} .d-stop{{background:var(--stop)}}
.d-target{{background:var(--target)}} .d-invalid{{background:var(--invalid)}}
table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
th {{ text-align:left; color:var(--dim); font-weight:600; padding:6px 8px;
  border-bottom:1px solid var(--line); text-transform:uppercase; font-size:10.5px;
  letter-spacing:.1em; }}
td {{ padding:6px 8px; border-bottom:1px solid var(--line); }}
tr:last-child td {{ border-bottom:0; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.bar {{ height:6px; background:var(--line); border-radius:3px; overflow:hidden; min-width:90px; }}
.bar > i {{ display:block; height:100%; background:var(--target); }}
.smcchart {{ display:block; border-radius:6px; }}
.tvwrap {{ border-radius:6px; overflow:hidden; border:1px solid var(--line); }}
.empty {{ color:var(--dim); padding:26px; text-align:center; }}
.notice {{ border-left:3px solid var(--warn); padding:9px 12px; background:rgba(240,180,41,.07);
  border-radius:0 6px 6px 0; margin:10px 0; font-size:12.5px; }}
.notice.bad {{ border-color:var(--stop); background:rgba(255,77,77,.07); }}
.notice.ok {{ border-color:var(--target); background:rgba(34,197,94,.07); }}
.big {{ font-size:26px; font-weight:700; }}
.pill {{ font-size:11px; padding:2px 7px; border-radius:4px; background:var(--line);
  color:var(--dim); margin-left:6px; }}
footer {{ margin-top:34px; color:var(--dim); font-size:11.5px; line-height:1.7; }}
"""


def _grade_class(g: str) -> str:
    return {"A+": "b-live", "A": "b-live", "B": "b-warn", "C": "b-grey"}.get(g, "b-dead")


def _feed_block(res: ScanResult) -> str:
    st = res.feed
    if st.state == "LIVE":
        cls, txt = ("b-live", "LIVE MARKET DATA") if st.is_true_xauusd else \
                   ("b-warn", "LIVE MARKET DATA — PROXY FEED")
    elif st.state == "MARKET_CLOSED":
        cls, txt = "b-grey", "MARKET CLOSED"
    else:
        cls, txt = "b-dead", "LIVE DATA UNAVAILABLE"
    out = [f'<span class="badge {cls}">{_e(txt)}</span>']
    out.append(f'<div class="dim" style="margin-top:6px">{_e(st.banner)}</div>')
    if st.state == "LIVE" and not st.is_true_xauusd:
        out.append(f'<div class="notice">⚠ <b>This is not a broker XAUUSD feed.</b> '
                   f'{_e(st.kind_label)} Structure and levels are computed from it faithfully, '
                   f'but absolute prices will differ from your broker. Set '
                   f'<code>TL_EMAIL</code>/<code>TL_PASSWORD</code> to use true XAUUSD spot.</div>')
    if st.state == "LIVE" and st.delayed:
        out.append(f'<div class="notice">⚠ <b>Delayed feed</b> — the publisher lags real time by '
                   f'about {st.delayed_by_sec // 60} minutes. Not a real-time quote.</div>')
    for err in st.errors[:3]:
        out.append(f'<div class="notice bad">provider error — {_e(err)}</div>')
    return "".join(out)


def _setup_card(s: Setup, lots=None, risk_usd=None) -> str:
    valid = s.status == "VALID"
    if not valid:
        return (f'<div class="card"><span class="badge b-dead">🔴 INVALID</span>'
                f'<span class="pill">{_e(s.mode)}</span>'
                f'<div class="big invalid" style="margin-top:8px">{_e(s.direction)} '
                f'{_e(s.pattern.replace("_", " ").title())}</div>'
                f'<div class="notice bad">INVALID — {_e(s.invalid_reason)}</div></div>')

    prob = (f'<span class="v">{s.probability:.1f}%</span> '
            f'<span class="dim">n={s.sample_size} · PF {s.profit_factor} · avg R:R 1:{s.avg_rr}</span>'
            if s.probability is not None else
            f'<span class="invalid">INSUFFICIENT SAMPLE</span> '
            f'<span class="dim">(n={s.sample_size}) — {_e(s.prob_note)}</span>')
    dcol = "target" if s.direction == "BUY" else "stop"
    rows = [
        ("<span class='dot d-entry'></span>Entry", f'<span class="entry">{s.entry:,.2f}</span>', ""),
        ("Entry zone", f'<span class="entry">{s.entry_low:,.2f} – {s.entry_high:,.2f}</span>',
         f"{s.entry_type} / {s.entry_state}"),
        ("<span class='dot d-stop'></span>Stop Loss", f'<span class="stop">{s.sl:,.2f}</span>',
         f"{s.sl_pips:.1f} pips"),
        ("<span class='dot d-target'></span>Target 1", f'<span class="target">{s.tp1:,.2f}</span>',
         f"{s.tp1_pips:.1f} pips · 1:{s.rr_tp1}"),
        ("<span class='dot d-target'></span>Target 2", f'<span class="target">{s.tp2:,.2f}</span>',
         f"{s.tp2_pips:.1f} pips · 1:{s.rr}"),
        ("<span class='dot d-target'></span>Target 3",
         f'<span class="target">{s.tp3:,.2f}</span>' if s.tp3 else '<span class="dim">n/a</span>',
         f"{s.tp3_pips:.1f} pips · 1:{s.rr_tp3}" if s.tp3 else "no supporting draw on liquidity"),
        ("Risk / Reward", f"1:{s.rr}", "to Target 2"),
        ("Estimated win probability", prob, ""),
        ("Current price", f"{s.price_at_signal:,.2f}", "at signal"),
    ]
    if lots:
        rows.append(("Position size", f"{lots} lots", f"${risk_usd} at risk"))
    body = "".join(f'<div class="rowline"><span class="k">{k}</span>'
                   f'<span class="v">{v} <span class="dim">{_e(n)}</span></span></div>'
                   for k, v, n in rows)
    return (f'<div class="card">'
            f'<span class="badge b-live">🟢 VALID</span>'
            f'<span class="badge {_grade_class(s.grade)}" style="margin-left:6px">GRADE {_e(s.grade)}</span>'
            f'<span class="pill">{_e(s.mode)}</span>'
            f'<span class="pill">score {s.score}/100</span>'
            f'<div class="big {dcol}" style="margin:9px 0 2px">{_e(s.direction)} XAUUSD</div>'
            f'<div class="dim" style="margin-bottom:12px">'
            f'{_e(s.pattern.replace("_", " ").title())} · {_e(s.anchors.get("ltf_tf", ""))} execution · '
            f'{_e(s.session)}{" / " + _e(s.killzone) if s.killzone else ""} · '
            f'{_e(s.history_flag.replace("_", " ").lower())}</div>'
            f'{body}</div>')


def _confluence_card(s: Setup) -> str:
    rows = []
    for name, d in s.component_scores.items():
        pct = int(round(d["fraction"] * 100))
        col = "var(--target)" if d["fraction"] >= .75 else (
            "var(--warn)" if d["fraction"] >= .5 else "var(--invalid)")
        rows.append(f'<tr><td>{_e(name.replace("_", " ").title())}</td>'
                    f'<td style="width:110px"><div class="bar"><i style="width:{pct}%;'
                    f'background:{col}"></i></div></td>'
                    f'<td class="num">{d["points"]:.1f}/{d["max"]:.0f}</td>'
                    f'<td class="dim">{_e(d["note"])}</td></tr>')
    return (f'<div class="card"><table><thead><tr><th>Confluence</th><th></th>'
            f'<th class="num">Points</th><th>Measured</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _stats_card(store: StatsStore) -> str:
    if store.empty:
        return ('<div class="card"><div class="notice">No backtest on file. Run '
                '<code>python3 xau_bot.py backtest</code>. Until then the engine publishes '
                '<b>no</b> win probabilities at all.</div></div>')
    m = store.meta
    rows = []
    for b in sorted((b for b in store.buckets.values() if b.n >= 5),
                    key=lambda b: (-b.n, b.key))[:18]:
        col = "target" if b.profit_factor >= 1.3 else ("" if b.profit_factor >= 1 else "stop")
        rows.append(f'<tr><td>{_e(b.key.replace("|", " · "))}</td>'
                    f'<td class="num">{b.n}</td><td class="num">{b.win_rate:.1f}%</td>'
                    f'<td class="num {col}">{b.profit_factor:.2f}</td>'
                    f'<td class="num">1:{b.target_rr:.2f}</td>'
                    f'<td class="num">{b.expectancy_r:+.2f}R</td>'
                    f'<td class="num">{b.max_drawdown_r:+.2f}R</td></tr>')
    return (f'<div class="card">'
            f'<span class="badge b-grey">HISTORICAL / BACKTEST DATA</span>'
            f'<div class="dim" style="margin:8px 0 12px">{_e(m.get("instrument", "?"))} · '
            f'{_ts(m.get("history_from"))} → {_ts(m.get("history_to"))} · '
            f'{m.get("trades", 0)} resolved trades<br>Fill model: {_e(m.get("fill_model", ""))}</div>'
            f'<table><thead><tr><th>Configuration (pattern · mode · grade · direction)</th>'
            f'<th class="num">N</th><th class="num">Win %</th><th class="num">PF</th>'
            f'<th class="num">Avg R:R</th><th class="num">Expectancy</th>'
            f'<th class="num">Max DD</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
            f'<div class="notice">{_e(DISCLAIMER)}</div></div>')


def _perf_card(rep: Report) -> str:
    rows = []
    for name in ("today", "week", "month"):
        p = rep.periods.get(name)
        if not p:
            continue
        s = p.stats
        rows.append(f'<tr><td>{name.upper()}</td><td class="num">{p.setups}</td>'
                    f'<td class="num">{p.open}</td><td class="num">{p.invalidated}</td>'
                    f'<td class="num">{s.wins}</td><td class="num">{s.losses}</td>'
                    f'<td class="num">{s.win_rate:.1f}%</td>'
                    f'<td class="num">{s.profit_factor:.2f}</td>'
                    f'<td class="num">{s.expectancy_r:+.2f}R</td>'
                    f'<td class="num">{s.max_drawdown_r:+.2f}R</td></tr>')
    extra = []
    for name, title in (("by_mode", "By mode"), ("by_pattern", "By setup type"),
                        ("by_direction", "By direction"), ("by_session", "By session"),
                        ("by_grade", "By grade"), ("by_timeframe", "By timeframe")):
        b = rep.breakdowns.get(name) or {}
        if not b:
            continue
        cells = " · ".join(f'{_e(k)} <span class="dim">n={v.n} {v.win_rate:.0f}% '
                           f'PF {v.profit_factor:.2f}</span>' for k, v in b.items())
        extra.append(f'<div class="rowline"><span class="k">{title}</span>'
                     f'<span style="text-align:right">{cells}</span></div>')
    empty = ('<div class="notice">No published signal has resolved yet, so there is nothing to '
             'report. This panel stays empty rather than borrowing the backtest\'s numbers.</div>'
             if rep.resolved == 0 else "")
    return (f'<div class="card"><span class="badge b-live">LIVE-TRACKED DATA</span>'
            f'<div class="dim" style="margin:8px 0 12px">Results of signals this bot actually '
            f'published, tracked bar by bar. Paper only — the bot places no orders.</div>'
            f'<table><thead><tr><th>Period</th><th class="num">Setups</th><th class="num">Open</th>'
            f'<th class="num">Invalid</th><th class="num">Wins</th><th class="num">Losses</th>'
            f'<th class="num">Win %</th><th class="num">PF</th><th class="num">Expectancy</th>'
            f'<th class="num">Max DD</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
            f'{"".join(extra)}{empty}</div>')


def _history_card(engine: Engine, limit: int = 20) -> str:
    recs = sorted(engine.journal.records.values(), key=lambda r: r.created_at, reverse=True)[:limit]
    if not recs:
        return '<div class="card"><div class="empty">no signals recorded yet</div></div>'
    rows = []
    for r in recs:
        cls = {"WIN": "target", "LOSS": "stop"}.get(r.outcome, "invalid")
        rows.append(f'<tr><td class="dim">{_ts(r.created_at)}</td><td>{_e(r.mode)}</td>'
                    f'<td>{_e(r.pattern.replace("_", " ").title())}</td>'
                    f'<td>{_e(r.direction)}</td><td>{_e(r.grade)}</td>'
                    f'<td class="num">{r.probability if r.probability is not None else "—"}</td>'
                    f'<td class="num entry">{r.entry:,.2f}</td>'
                    f'<td class="num stop">{r.sl:,.2f}</td>'
                    f'<td class="num target">{r.tp2:,.2f}</td>'
                    f'<td class="num">{r.target_rr}</td>'
                    f'<td class="{cls}">{_e(r.outcome or r.state)}</td>'
                    f'<td class="num">{r.r_multiple:+.2f}R</td>'
                    f'<td class="num">{r.mfe_r:+.2f}</td><td class="num">{r.mae_r:+.2f}</td>'
                    f'<td>{_e(r.session)}</td><td>{_e(r.exec_tf)}</td></tr>')
    return (f'<div class="card" style="overflow-x:auto"><table><thead><tr>'
            f'<th>Timestamp</th><th>Mode</th><th>Setup</th><th>Dir</th><th>Grade</th>'
            f'<th class="num">Prob</th><th class="num">Entry</th><th class="num">SL</th>'
            f'<th class="num">TP2</th><th class="num">R:R</th><th>Result</th>'
            f'<th class="num">R</th><th class="num">MFE</th><th class="num">MAE</th>'
            f'<th>Session</th><th>TF</th></tr></thead><tbody>{"".join(rows)}</tbody>'
            f'</table></div>')


def render_page(engine: Engine, res: ScanResult, tv_symbol: str = "OANDA:XAUUSD",
                refresh: int = 60) -> str:
    best = res.best
    ctx = engine._contexts.get(best.mode) if best else \
        (engine._contexts.get("INTRADAY") or next(iter(engine._contexts.values()), None))
    chart = ""
    if ctx is not None:
        chart = svg_chart(ctx.ltf.series, ctx, best)

    price = f"{res.price:,.2f}" if res.price else "——"
    mode_rows = "".join(
        f'<tr><td>{_e(m)}</td><td>{_e(v.htf_bias)}</td><td>{_e(v.htf_trend)}</td>'
        f'<td>{_e(v.mtf_trend)}</td><td>{_e(v.ltf_trend)}</td><td>{_e(v.regime)}</td>'
        f'<td>{_e(v.volatility)}</td><td>{_e(v.pd_zone)} <span class="dim">{v.pd_position:.2f}'
        f'</span></td><td class="num">{v.range_low:,.2f} – {v.range_high:,.2f}</td>'
        f'<td class="num">{v.unswept_pools}/{v.open_fvgs}/{v.fresh_obs}</td></tr>'
        if not v.note else f'<tr><td>{_e(m)}</td><td colspan="9" class="dim">{_e(v.note)}</td></tr>'
        for m, v in res.modes.items())

    rejected = "".join(
        f'<div class="rowline"><span class="k">{_e(s.direction)} {_e(s.mode)} '
        f'{_e(s.pattern.replace("_", " ").title())}</span>'
        f'<span class="dim">score {s.score:.1f} — {_e(s.invalid_reason)}</span></div>'
        for s in res.rejected[:8]) or '<div class="dim">nothing was detected and discarded</div>'

    tracked = "".join(
        f'<div class="rowline"><span><b class="{"target" if r.direction == "BUY" else "stop"}">'
        f'{_e(r.direction)}</b> {_e(r.mode)} {_e(r.grade)} '
        f'<span class="dim">{_e(r.state)}</span></span>'
        f'<span><span class="entry">{r.entry:,.2f}</span> / <span class="stop">{r.sl:,.2f}</span>'
        f' / <span class="target">{r.tp2:,.2f}</span> '
        f'<span class="dim">MFE {r.mfe_r:+.2f}R · MAE {r.mae_r:+.2f}R</span></span></div>'
        for r in res.active) or '<div class="dim">nothing open</div>'
    invalidated = "".join(
        f'<div class="notice bad">🔴 INVALID — {_e(r.direction)} {_e(r.mode)} '
        f'[{_e(r.id)}] — {_e(reason)}</div>' for r, reason in res.invalidated)

    g = res.guard
    guard_cls = "bad" if g.blocked else "ok"
    guard = (f'<div class="notice {guard_cls}"><b>Risk guard: '
             f'{"STOOD DOWN" if g.blocked else "CLEAR"}</b> — setups today '
             f'{g.setups_today}/{g.max_setups} · open {g.open_trades}/{g.max_open} · '
             f'consecutive losses {g.consecutive_losses}/{g.max_consecutive} · '
             f'today {g.realised_r_today:+.2f}R of -{g.daily_loss_limit_r:.1f}R limit'
             + ("<br>" + "<br>".join(_e(r) for r in g.reasons) if g.reasons else "") + '</div>')
    if res.news is not None:
        news_cls = "bad" if res.news.blocked else ("" if res.news.configured else "")
        guard += (f'<div class="notice {news_cls}">{_e(res.news.label)}'
                  + (f' · next: {_e(res.news.next_event)}' if res.news.next_event else '') + '</div>')

    confluence_html = (f'<h2>Confluence score — {best.score}/100 → grade {_e(best.grade)}</h2>'
                       f'{_confluence_card(best)}') if best else ""
    setup_html = (_setup_card(best, *engine.position_size(best)) if best else
                  '<div class="card"><span class="badge b-grey">NO VALID SETUP</span>'
                  '<div class="big invalid" style="margin:10px 0 4px">NO VALID SETUP</div>'
                  '<div class="dim">The engine publishes a setup only when the full SMC '
                  'sequence and the confluence minimum are both met. Two to three genuine '
                  'opportunities a day is the target; manufacturing a fourth is not.</div></div>')
    extra_setups = "".join(f'<h2>Also valid — {_e(s.mode)}</h2>{_setup_card(s)}'
                           for s in res.setups[1:3])

    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>XAUUSD — SMC Sniper Engine</title><style>{CSS}</style></head><body><div class="wrap">

<h1>XAUUSD — SMC SNIPER ENGINE</h1>
<div class="dim">{_ts(res.ts)} · scan {res.scan_ms} ms · auto-refresh {refresh}s</div>

<div class="grid g2" style="margin-top:14px">
  <div class="card">
    <div class="price">{price}</div>
    {_feed_block(res)}
  </div>
  <div class="card">
    <div class="rowline"><span class="k">Market bias</span><span class="v">{_e(res.bias)}</span></div>
    <div class="rowline"><span class="k">Market regime</span><span class="v">{_e(res.regime)}</span></div>
    <div class="rowline"><span class="k">Session</span><span class="v">{_e(res.session)}
      {(" / " + _e(res.killzone)) if res.killzone else ""}</span></div>
    <div class="rowline"><span class="k">Status</span><span class="v">{_e(res.headline)}</span></div>
  </div>
</div>

<h2>Active setup</h2>
{setup_html}
{confluence_html}
{extra_setups}

<h2>SMC chart — engine annotations</h2>
<div class="card">{chart or '<div class="empty">no chart available</div>'}
<div class="dim" style="margin-top:10px">
<span class="dot d-entry"></span>Entry &nbsp; <span class="dot d-stop"></span>Stop loss &nbsp;
<span class="dot d-target"></span>Targets &nbsp; <span class="dot d-invalid"></span>Invalid &nbsp;
· shaded boxes are FVGs and order blocks · dashed amber lines are unswept liquidity pools
· BOS / MSS labels mark structure breaks · the red/green wash is premium / discount.
</div></div>

<h2>TradingView live chart</h2>
<div class="card">{tradingview_widget(tv_symbol)}
<div class="dim" style="margin-top:10px">TradingView's own embedded Advanced Chart widget
(<code>{_e(tv_symbol)}</code>), rendered by TradingView. This bot reads no data from it —
the analysis above comes from {_e(res.feed.source or "the configured feed")}.</div></div>

<h2>Multi-timeframe structure</h2>
<div class="card"><table><thead><tr><th>Mode</th><th>Bias</th><th>HTF</th><th>MTF</th>
<th>Exec</th><th>Regime</th><th>Volatility</th><th>Premium/Discount</th>
<th class="num">Dealing range</th><th class="num">Pools/FVG/OB</th></tr></thead>
<tbody>{mode_rows}</tbody></table></div>

<h2>Rejected this scan — why there is no trade</h2>
<div class="card">{rejected}</div>

<h2>Tracked setups</h2>
<div class="card">{tracked}</div>{invalidated}

<h2>Risk management</h2>
{guard}

<h2>Validated historical performance</h2>
{_stats_card(engine.stats)}

<h2>Live-tracked performance</h2>
{_perf_card(build_report(engine.journal))}

<h2>Signal history</h2>
{_history_card(engine)}

<footer>
<b>Data provenance.</b> Sections badged <span class="badge b-live">LIVE</span> are computed from
the feed named above, re-fetched on every scan. Sections badged
<span class="badge b-grey">HISTORICAL / BACKTEST DATA</span> come from a walk-forward simulation
over past bars. The two are never averaged together.<br>
<b>Probabilities.</b> Every win rate shown is the measured frequency of that exact configuration in
the backtest, always printed with its sample size. Where the sample is too small, the engine prints
INSUFFICIENT SAMPLE instead of a number. {_e(DISCLAIMER)}<br>
<b>Not advice.</b> This is analysis software, not investment advice, and it places no orders.
Trading XAUUSD with leverage can lose more than your deposit.
</footer>
</div></body></html>"""


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------
class _State:
    def __init__(self, engine: Engine, interval: int, tv_symbol: str):
        self.engine = engine
        self.interval = interval
        self.tv_symbol = tv_symbol
        self.result: ScanResult | None = None
        self.lock = threading.Lock()
        self.last = 0.0

    def refresh(self, force: bool = False) -> ScanResult:
        with self.lock:
            if force or self.result is None or (time.time() - self.last) >= self.interval:
                self.result = self.engine.scan()
                self.last = time.time()
            return self.result


def _handler(state: _State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            try:
                res = state.refresh()
                if path == "/api/scan":
                    payload = {
                        "generated_at": res.ts, "feed": res.feed.__dict__,
                        "price": res.price, "bias": res.bias, "regime": res.regime,
                        "session": res.session, "killzone": res.killzone,
                        "headline": res.headline,
                        "setups": [s.as_dict() for s in res.setups],
                        "rejected": [{"mode": s.mode, "pattern": s.pattern,
                                      "direction": s.direction, "score": s.score,
                                      "reason": s.invalid_reason} for s in res.rejected],
                        "invalidated": [{"id": r.id, "reason": why}
                                        for r, why in res.invalidated],
                        "guard": res.guard.__dict__, "notes": res.notes,
                    }
                    self._send(json.dumps(payload, default=str).encode(), "application/json")
                elif path == "/api/stats":
                    self._send(json.dumps(
                        {"meta": state.engine.stats.meta,
                         "buckets": {k: v.as_dict() for k, v in state.engine.stats.buckets.items()}},
                        default=str).encode(), "application/json")
                elif path == "/api/performance":
                    self._send(json.dumps(build_report(state.engine.journal).as_dict(),
                                          default=str).encode(), "application/json")
                else:
                    self._send(render_page(state.engine, res, state.tv_symbol,
                                           state.interval).encode(), "text/html; charset=utf-8")
            except Exception as exc:                      # noqa: BLE001 - surface, don't crash
                body = f"<pre>scan failed: {html.escape(repr(exc))}</pre>".encode()
                self._send(body, "text/html; charset=utf-8")
    return H


def serve(engine: Engine, host: str = "127.0.0.1", port: int = 8787,
          interval: int = 60, tv_symbol: str = "OANDA:XAUUSD"):
    state = _State(engine, interval, tv_symbol)
    print(f"  first scan ...", flush=True)
    state.refresh(force=True)
    srv = ThreadingHTTPServer((host, port), _handler(state))
    print(f"  dashboard on http://{host}:{port}/   "
          f"(JSON: /api/scan, /api/stats, /api/performance)", flush=True)
    print(f"  rescans every {interval}s; Ctrl-C to stop", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        srv.server_close()
