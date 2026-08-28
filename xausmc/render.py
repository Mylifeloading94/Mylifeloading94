"""
Terminal rendering (spec §1 / §13).

Chart colour system, used identically here and in the HTML dashboard:
    Entry      BLUE
    Stop Loss  RED
    Take Profit / targets  GREEN
    Invalid setup          GREY, labelled INVALID
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone

from .candles import Series
from .engine import ScanResult
from .journal import Journal
from .performance import Report
from .setups import Setup
from .stats import DISCLAIMER, StatsStore

# -- colour ---------------------------------------------------------------
_NO_COLOR = bool(os.environ.get("NO_COLOR")) or os.environ.get("TERM") == "dumb"


def _c(code: str) -> str:
    return "" if _NO_COLOR else code


RESET = _c("\033[0m")
BOLD = _c("\033[1m")
DIM = _c("\033[2m")
BLUE = _c("\033[38;5;39m")        # entry
RED = _c("\033[38;5;203m")        # stop loss
GREEN = _c("\033[38;5;77m")       # targets
GREY = _c("\033[38;5;245m")       # invalid
WHITE = _c("\033[38;5;255m")
YELLOW = _c("\033[38;5;221m")
CYAN = _c("\033[38;5;80m")
MAGENTA = _c("\033[38;5;176m")

GRADE_COLOR = {"A+": GREEN + BOLD, "A": GREEN, "B": YELLOW, "C": GREY, "INVALID": GREY}


def width() -> int:
    return max(72, min(shutil.get_terminal_size((100, 30)).columns, 120))


def rule(ch: str = "─", title: str = "") -> str:
    w = width()
    if not title:
        return DIM + ch * w + RESET
    t = f" {title} "
    left = 3
    return DIM + ch * left + RESET + BOLD + t + RESET + DIM + ch * max(0, w - left - len(t)) + RESET


def _ts(ts: float | int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _pct(v: float | None) -> str:
    return f"{v:.1f}%" if v is not None else "—"


# --------------------------------------------------------------------------
# Panels
# --------------------------------------------------------------------------
def header(res: ScanResult) -> str:
    st = res.feed
    if st.state == "LIVE":
        badge = f"{GREEN}● LIVE{RESET}" if st.is_true_xauusd else f"{YELLOW}● LIVE (PROXY){RESET}"
    elif st.state == "MARKET_CLOSED":
        badge = f"{GREY}● MARKET CLOSED{RESET}"
    else:
        badge = f"{RED}● LIVE DATA UNAVAILABLE{RESET}"
    price = f"{WHITE}{BOLD}{res.price:,.2f}{RESET}" if res.price else f"{GREY}——{RESET}"
    lines = [
        rule("═", "XAUUSD — SMC SNIPER ENGINE"),
        f"  {badge}   Price: {price}   {DIM}{_ts(res.ts)}{RESET}",
        f"  {DIM}Feed:{RESET} {st.banner}",
    ]
    if st.state == "LIVE" and not st.is_true_xauusd:
        lines.append(f"  {YELLOW}⚠ PROXY FEED{RESET} {DIM}{st.kind_label}. "
                     f"Levels are not broker-identical — verify on your own XAUUSD chart.{RESET}")
    if st.state == "LIVE" and st.delayed:
        lines.append(f"  {YELLOW}⚠ DELAYED FEED{RESET} {DIM}publisher lag ~{st.delayed_by_sec // 60} "
                     f"min; this is not a real-time quote.{RESET}")
    lines.append(f"  Bias: {_bias(res.bias)}   Regime: {CYAN}{res.regime}{RESET}   "
                 f"Session: {CYAN}{res.session}{RESET}"
                 f"{'  KZ: ' + CYAN + res.killzone + RESET if res.killzone else ''}")
    return "\n".join(lines)


def _bias(b: str) -> str:
    return {"BULLISH": GREEN + "BULLISH" + RESET, "BEARISH": RED + "BEARISH" + RESET,
            "RANGING": GREY + "RANGING" + RESET}.get(b, GREY + b + RESET)


def market_panel(res: ScanResult) -> str:
    out = [rule("─", "MULTI-TIMEFRAME STRUCTURE")]
    out.append(f"  {DIM}{'MODE':9} {'BIAS':11} {'HTF':9} {'MTF':9} {'EXEC':9} {'REGIME':9} "
               f"{'VOL':9} {'PD ZONE':12} {'P/F/OB':9} {'STRUCTURE HI/LO'}{RESET}")
    for m, v in res.modes.items():
        if v.note:
            out.append(f"  {m:9} {GREY}{v.note}{RESET}")
            continue
        sh = f"{v.struct_high:,.2f}" if v.struct_high else "—"
        sl_ = f"{v.struct_low:,.2f}" if v.struct_low else "—"
        out.append(f"  {m:9} {v.htf_bias:11} {v.htf_trend:9} {v.mtf_trend:9} {v.ltf_trend:9} "
                   f"{v.regime:9} {v.volatility:9} {v.pd_zone:>9}{v.pd_position:5.2f}   "
                   f"{v.unswept_pools:>2}/{v.open_fvgs:>2}/{v.fresh_obs:<3} {sh:>9} / {sl_:<9}")
    v = next((x for x in res.modes.values() if not x.note), None)
    if v:
        out.append(f"  {DIM}Dealing range {v.range_low:,.2f} — {v.range_high:,.2f}   "
                   f"equilibrium {v.equilibrium:,.2f}{RESET}")
    return "\n".join(out)


def setup_panel(setup: Setup, lots: float | None = None, risk_usd: float | None = None) -> str:
    valid = setup.status == "VALID"
    gc = GRADE_COLOR.get(setup.grade, GREY)
    dcol = GREEN if setup.direction == "BUY" else RED
    status = f"{GREEN}🟢 VALID{RESET}" if valid else f"{RED}🔴 INVALID{RESET}"
    head = (f"  {dcol}{BOLD}{setup.direction}{RESET}  {setup.mode}  "
            f"{gc}GRADE {setup.grade}{RESET}  {DIM}score {setup.score}/100{RESET}   {status}\n"
            f"  {gc}{setup.advice}{RESET}")
    if not valid:
        return "\n".join([
            head,
            f"  {GREY}{setup.pattern.replace('_', ' ').title()}{RESET}",
            f"  {RED}INVALID — {setup.invalid_reason}{RESET}",
        ])

    prob = (f"{_pct(setup.probability)}  {DIM}(n={setup.sample_size}, "
            f"PF {setup.profit_factor}, avg R:R 1:{setup.avg_rr}){RESET}"
            if setup.probability is not None
            else f"{GREY}INSUFFICIENT SAMPLE{RESET} {DIM}(n={setup.sample_size}) — "
                 f"{setup.prob_note}{RESET}")
    tp3 = (f"{GREEN}{setup.tp3:>10,.2f}{RESET}  {DIM}{setup.tp3_pips:>6.1f} pips   "
           f"1:{setup.rr_tp3}{RESET}" if setup.tp3 else f"{GREY}{'n/a':>10}{RESET}")
    lot_line = (f"  {DIM}Position at {setup.sl_pips:.1f} pips risk:{RESET} {lots} lots "
                f"{DIM}(${risk_usd} at risk){RESET}" if lots else "")
    zone = (f"  {BLUE}Entry zone{RESET}     {BLUE}{setup.entry_low:,.2f} – {setup.entry_high:,.2f}{RESET}"
            f"   {DIM}{setup.entry_type} / {setup.entry_state}{RESET}")
    return "\n".join(x for x in [
        head,
        f"  {DIM}{setup.pattern.replace('_', ' ').title()} · {setup.anchors.get('ltf_tf', '')} execution "
        f"· {setup.session}{' / ' + setup.killzone if setup.killzone else ''}{RESET}",
        "",
        f"  {BLUE}● Entry{RESET}        {BLUE}{setup.entry:>10,.2f}{RESET}",
        zone,
        f"  {RED}● Stop Loss{RESET}    {RED}{setup.sl:>10,.2f}{RESET}  {DIM}{setup.sl_pips:>6.1f} pips{RESET}",
        f"  {GREEN}● Target 1{RESET}     {GREEN}{setup.tp1:>10,.2f}{RESET}  {DIM}{setup.tp1_pips:>6.1f} pips   1:{setup.rr_tp1}{RESET}",
        f"  {GREEN}● Target 2{RESET}     {GREEN}{setup.tp2:>10,.2f}{RESET}  {DIM}{setup.tp2_pips:>6.1f} pips   1:{setup.rr}{RESET}",
        f"  {GREEN}● Target 3{RESET}     {tp3}",
        "",
        f"  Risk/Reward   {BOLD}1:{setup.rr}{RESET} {DIM}(to TP2){RESET}",
        f"  Probability   {prob}",
        lot_line,
    ] if x is not None)


def confluence_panel(setup: Setup) -> str:
    out = [rule("─", f"CONFLUENCE SCORE — {setup.score}/100 → {setup.grade}")]
    for name, d in setup.component_scores.items():
        frac = d["fraction"]
        col = GREEN if frac >= 0.75 else (YELLOW if frac >= 0.5 else GREY)
        bar_len = 14
        filled = int(round(frac * bar_len))
        bar = col + "█" * filled + RESET + DIM + "·" * (bar_len - filled) + RESET
        out.append(f"  {name.replace('_', ' '):18} {bar} {d['points']:>5.1f}/{d['max']:<4.0f} "
                   f"{DIM}{d['note']}{RESET}")
    return "\n".join(out)


def active_panel(res: ScanResult) -> str:
    out = [rule("─", "TRACKED SETUPS")]
    if not res.active:
        out.append(f"  {DIM}nothing open{RESET}")
    for r in res.active:
        col = GREEN if r.direction == "BUY" else RED
        out.append(f"  {col}{r.direction:4}{RESET} {r.mode:9} {GRADE_COLOR.get(r.grade, GREY)}{r.grade:3}{RESET} "
                   f"{r.state:8} entry {BLUE}{r.entry:,.2f}{RESET} sl {RED}{r.sl:,.2f}{RESET} "
                   f"tp2 {GREEN}{r.tp2:,.2f}{RESET}  {DIM}MFE {r.mfe_r:+.2f}R / MAE {r.mae_r:+.2f}R  "
                   f"[{r.id}]{RESET}")
    for rec, reason in res.invalidated:
        out.append(f"  {RED}🔴 INVALID{RESET} {rec.direction} {rec.mode} [{rec.id}] "
                   f"{GREY}— {reason}{RESET}")
    return "\n".join(out)


def rejected_panel(res: ScanResult, limit: int = 6) -> str:
    if not res.rejected:
        return ""
    out = [rule("─", "REJECTED THIS SCAN (why there is no trade)")]
    for s in res.rejected[:limit]:
        out.append(f"  {GREY}{'INVALID':8}{RESET} {s.direction:4} {s.mode:9} "
                   f"{s.pattern.replace('_', ' ').title():28} {DIM}score {s.score:5.1f} — "
                   f"{s.invalid_reason}{RESET}")
    return "\n".join(out)


def guard_panel(res: ScanResult) -> str:
    g = res.guard
    out = [rule("─", "RISK GUARD")]
    state = f"{RED}STOOD DOWN{RESET}" if g.blocked else f"{GREEN}CLEAR{RESET}"
    out.append(f"  {state}   setups today {g.setups_today}/{g.max_setups}   "
               f"open {g.open_trades}/{g.max_open}   consecutive losses "
               f"{g.consecutive_losses}/{g.max_consecutive}   today {g.realised_r_today:+.2f}R "
               f"(limit -{g.daily_loss_limit_r:.1f}R)")
    for r in g.reasons:
        out.append(f"  {RED}·{RESET} {r}")
    if res.news is not None:
        col = RED if res.news.blocked else (GREY if not res.news.configured else GREEN)
        out.append(f"  {col}{res.news.label}{RESET}"
                   + (f"  {DIM}next: {res.news.next_event}{RESET}" if res.news.next_event else ""))
    return "\n".join(out)


def stats_panel(store: StatsStore, limit: int = 12) -> str:
    out = [rule("─", "VALIDATED HISTORICAL PERFORMANCE (BACKTEST DATA)")]
    if store.empty:
        out.append(f"  {GREY}No backtest on file. Run `python3 xau_bot.py backtest` — until then "
                   f"the engine publishes NO probabilities.{RESET}")
        return "\n".join(out)
    m = store.meta
    out.append(f"  {DIM}{m.get('instrument', '?')} · {m.get('fill_model', '')}{RESET}")
    out.append(f"  {DIM}{_ts(m.get('history_from'))} → {_ts(m.get('history_to'))} · "
               f"{m.get('trades', 0)} resolved trades{RESET}")
    out.append("")
    out.append(f"  {DIM}{'CONFIGURATION':44} {'N':>5} {'WIN%':>7} {'PF':>7} {'AVG R':>7} "
               f"{'EXPECT':>8}{RESET}")
    rows = sorted((b for k, b in store.buckets.items() if b.n >= 5),
                  key=lambda b: (-b.n, b.key))[:limit]
    for b in rows:
        col = GREEN if b.profit_factor >= 1.3 else (YELLOW if b.profit_factor >= 1.0 else RED)
        out.append(f"  {b.key.replace('|', ' · ')[:44]:44} {b.n:>5} {b.win_rate:>6.1f}% "
                   f"{col}{b.profit_factor:>7.2f}{RESET} {b.target_rr:>7.2f} "
                   f"{b.expectancy_r:>+7.2f}R")
    out.append(f"  {DIM}{DISCLAIMER}{RESET}")
    return "\n".join(out)


def performance_panel(rep: Report) -> str:
    out = [rule("─", "LIVE-TRACKED PERFORMANCE (this bot's own published signals)")]
    out.append(f"  {DIM}{'PERIOD':8} {'SETUPS':>7} {'OPEN':>5} {'INVAL':>6} {'WINS':>5} "
               f"{'LOSS':>5} {'WIN%':>7} {'PF':>7} {'EXPECT':>8} {'MAXDD':>8}{RESET}")
    for name in ("today", "week", "month"):
        p = rep.periods.get(name)
        if p is None:
            continue
        s = p.stats
        out.append(f"  {name.upper():8} {p.setups:>7} {p.open:>5} {p.invalidated:>6} "
                   f"{s.wins:>5} {s.losses:>5} {s.win_rate:>6.1f}% {s.profit_factor:>7.2f} "
                   f"{s.expectancy_r:>+7.2f}R {s.max_drawdown_r:>+7.2f}R")
    for name, title in (("by_mode", "BY MODE"), ("by_pattern", "BY SETUP TYPE"),
                        ("by_direction", "BY DIRECTION"), ("by_session", "BY SESSION"),
                        ("by_grade", "BY GRADE")):
        b = rep.breakdowns.get(name) or {}
        if not b:
            continue
        out.append(f"  {DIM}{title}{RESET}")
        for k, v in b.items():
            out.append(f"    {k:26} n={v.n:<4} {v.win_rate:>5.1f}%  PF {v.profit_factor:>5.2f}  "
                       f"{v.expectancy_r:+.2f}R")
    if rep.resolved == 0:
        out.append(f"  {GREY}No signals have resolved yet — nothing to report. "
                   f"This panel stays empty rather than showing borrowed numbers.{RESET}")
    return "\n".join(out)


def history_panel(journal: Journal, limit: int = 10) -> str:
    out = [rule("─", "SIGNAL HISTORY")]
    recs = sorted(journal.records.values(), key=lambda r: r.created_at, reverse=True)[:limit]
    if not recs:
        out.append(f"  {DIM}no signals recorded yet{RESET}")
        return "\n".join(out)
    out.append(f"  {DIM}{'WHEN':20} {'MODE':9} {'DIR':4} {'GR':3} {'ENTRY':>9} {'SL':>9} "
               f"{'TP2':>9} {'STATE':11} {'R':>7} {'MFE':>6} {'MAE':>6}{RESET}")
    for r in recs:
        col = {"WIN": GREEN, "LOSS": RED}.get(r.outcome, GREY)
        out.append(f"  {_ts(r.created_at)[:19]:20} {r.mode:9} {r.direction:4} {r.grade:3} "
                   f"{BLUE}{r.entry:>9,.2f}{RESET} {RED}{r.sl:>9,.2f}{RESET} "
                   f"{GREEN}{r.tp2:>9,.2f}{RESET} {col}{(r.outcome or r.state):11}{RESET} "
                   f"{r.r_multiple:>+6.2f}R {r.mfe_r:>+5.2f} {r.mae_r:>+5.2f}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# ASCII price chart with the spec's colour layout
# --------------------------------------------------------------------------
def ascii_chart(series: Series, setup: Setup | None = None, bars: int = 90,
                height: int = 22) -> str:
    win = series.bars[-bars:]
    if len(win) < 5:
        return f"  {GREY}not enough bars to draw{RESET}"
    levels: list[tuple[float, str, str]] = []
    if setup is not None:
        invalid = setup.status != "VALID"
        ecol, scol, tcol = (GREY, GREY, GREY) if invalid else (BLUE, RED, GREEN)
        levels = [(setup.entry, ecol, "ENTRY"), (setup.sl, scol, "STOP"),
                  (setup.tp1, tcol, "TP1"), (setup.tp2, tcol, "TP2")]
        if setup.tp3:
            levels.append((setup.tp3, tcol, "TP3"))

    lo = min([b.l for b in win] + [lv for lv, _, _ in levels])
    hi = max([b.h for b in win] + [lv for lv, _, _ in levels])
    pad = (hi - lo) * 0.04 or 1.0
    lo, hi = lo - pad, hi + pad
    step = (hi - lo) / height

    def row_of(p: float) -> int:
        return max(0, min(height - 1, int((hi - p) / step)))

    grid = [[" "] * len(win) for _ in range(height)]
    colr = [[""] * len(win) for _ in range(height)]
    for x, b in enumerate(win):
        c = GREEN if b.c >= b.o else RED
        top, bot = row_of(b.h), row_of(b.l)
        bt, bb = row_of(max(b.o, b.c)), row_of(min(b.o, b.c))
        for y in range(top, bot + 1):
            grid[y][x] = "█" if bt <= y <= bb else "│"
            colr[y][x] = c

    level_rows: dict[int, tuple[str, str, float]] = {}
    for lv, col, name in levels:
        level_rows[row_of(lv)] = (col, name, lv)

    lines = []
    for y in range(height):
        if y in level_rows:
            col, name, lv = level_rows[y]
            row = "".join((colr[y][x] + grid[y][x] + RESET) if grid[y][x] != " "
                          else col + "─" + RESET for x in range(len(win)))
            lines.append(f"{col}{lv:>10,.2f}{RESET} {row} {col}◄ {name}{RESET}")
        else:
            axis = f"{hi - y * step:10,.2f}" if y % 5 == 0 else " " * 10
            row = "".join((colr[y][x] + grid[y][x] + RESET) if grid[y][x] != " " else " "
                          for x in range(len(win)))
            lines.append(f"{DIM}{axis}{RESET} {row}")
    span = f"{_ts(win[0].ts)[:16]} → {_ts(win[-1].ts)[:16]}"
    lines.append(f"{' ' * 11}{DIM}{series.tf} · {len(win)} bars · {span}{RESET}")
    if setup is not None and setup.status != "VALID":
        lines.append(f"{' ' * 11}{GREY}{BOLD}INVALID{RESET} {GREY}— {setup.invalid_reason}{RESET}")
    return "\n".join(lines)


def dashboard(res: ScanResult, engine=None, chart_series: Series | None = None,
              show_confluence: bool = True) -> str:
    parts = [header(res)]
    if not res.live:
        parts.append("")
        for n in res.notes:
            parts.append(f"  {GREY}{n}{RESET}")
        parts.append(active_panel(res))
        parts.append(rule("═"))
        return "\n".join(parts)

    parts.append(market_panel(res))
    parts.append(rule("─", "ACTIVE SETUP"))
    if res.setups:
        best = res.setups[0]
        lots = risk = None
        if engine is not None:
            lots, risk = engine.position_size(best)
        parts.append(setup_panel(best, lots, risk))
        if chart_series is not None:
            parts.append("")
            parts.append(ascii_chart(chart_series, best))
        if show_confluence:
            parts.append(confluence_panel(best))
        for extra in res.setups[1:3]:
            parts.append(rule("─", f"ALSO VALID — {extra.mode}"))
            parts.append(setup_panel(extra))
    else:
        parts.append(f"  {GREY}{BOLD}NO VALID SETUP{RESET}")
        parts.append(f"  {DIM}The engine only publishes a setup when the full SMC sequence and "
                     f"the confluence minimum are both met. Waiting is the position.{RESET}")
        if chart_series is not None:
            parts.append("")
            parts.append(ascii_chart(chart_series, None))
    parts.append(rejected_panel(res))
    parts.append(active_panel(res))
    parts.append(guard_panel(res))
    parts.append(rule("═"))
    parts.append(f"  {DIM}scan {res.scan_ms} ms · every figure above was re-derived in "
                 f"this pass · probabilities are historical, not guarantees{RESET}")
    return "\n".join(p for p in parts if p)
