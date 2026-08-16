#!/usr/bin/env python3
"""Assemble ``Uploaded_Bot_Backtest.xlsx`` from ``uploaded_bot/results.json``.

Sheets:
    Summary                    two runs side by side, money numbers first
    Trade Results (Honest)     full ledger, Run B  <- the real one
    Trade Results (As Uploaded) full ledger, Run A
    Daily / Weekly / Monthly ROI   continuous timeline for Run B, flat periods included
    Bug Impact                 per-bug measured cost, isolated where isolable

    python3 build_uploaded_bot_workbook.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "uploaded_bot", "results.json")
DEST = os.path.join(REPO, "Uploaded_Bot_Backtest.xlsx")

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14)
NOTE_FONT = Font(italic=True, size=9, color="595959")
BOLD = Font(bold=True)
WIN_FILL = PatternFill("solid", fgColor="E2EFDA")
LOSS_FILL = PatternFill("solid", fgColor="FCE4E4")
SCR_FILL = PatternFill("solid", fgColor="FFF2CC")
BAD_FONT = Font(bold=True, color="C00000")
GOOD_FONT = Font(bold=True, color="1E7145")

MONEY = '#,##0.00;[Red]-#,##0.00'
PCT = '0.00"%"'
PIPS = '#,##0.0;[Red]-#,##0.0'


def head(ws, row, cols, widths=None):
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=j, value=c)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def title(ws, text, note=None, span=8):
    ws.cell(row=1, column=1, value=text).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    if note:
        ws.cell(row=2, column=1, value=note).font = NOTE_FONT
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=span)


# --------------------------------------------------------------------------
def sheet_summary(wb, d):
    A = d["runs"]["as_uploaded"]; B = d["runs"]["honest"]
    A2 = d["runs"]["as_uploaded_shipdefaults"]; B2 = d["runs"]["honest_shipdefaults"]
    ws = wb.create_sheet("Summary")
    title(ws, "Uploaded SMC Sniper bot — 90-day backtest on real TradeLocker data",
          f"{d['window']['from']} to {d['window']['to']} UTC   |   pairs: "
          f"{', '.join(d['pairs'])}   |   basis ${d['start_balance']:,.0f}, "
          f"{d['risk_per_trade']:.0%} risk/trade (smc_sniper/config.py RISK_PER_TRADE), "
          f"compounding trade by trade.", span=5)

    r = 4
    ws.cell(row=r, column=1, value="READ THIS FIRST").font = BAD_FONT
    r += 1
    for line in [
        "Run B (honest fills) is the bot's real performance. Run A is what the uploaded engine "
        "reports about itself, and it is inflated by four fill bugs.",
        "Both runs use the SAME strategy, SAME parameters and SAME broker bars. Only the four "
        "fill bugs differ. Nothing was retuned.",
        "The package ships two parameter sets. Config 1 is the one its docstrings call validated "
        "(OTE + prime killzones, disp 1.1, TP 2.5R) — it produces only 7-8 trades in 90 days, far too "
        "few to conclude anything. Config 2 is what `python3 sniper_backtest.py` actually executes "
        "(disp 0.6, TP 2.0R, no OTE gate, wider sessions) — 70-72 trades, a usable sample.",
    ]:
        ws.cell(row=r, column=1, value=line).font = NOTE_FONT
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
        r += 1

    def block(r, label, ra, rb, note):
        ws.cell(row=r, column=1, value=label).font = TITLE_FONT
        r += 1
        ws.cell(row=r, column=1, value=note).font = NOTE_FONT
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
        r += 1
        head(ws, r, ["Metric", "Run A — as uploaded (bugs intact)",
                     "Run B — honest fills (THE REAL ONE)", "Difference"],
             [34, 30, 30, 20])
        ws.freeze_panes = None
        rows = [
            ("Start balance", f"${d['start_balance']:,.2f}", f"${d['start_balance']:,.2f}", ""),
            ("End balance", f"${ra['end_balance']:,.2f}", f"${rb['end_balance']:,.2f}",
             f"${rb['end_balance'] - ra['end_balance']:,.2f}"),
            ("Profit $", f"${ra['profit']:,.2f}", f"${rb['profit']:,.2f}",
             f"${rb['profit'] - ra['profit']:,.2f}"),
            ("ROI %", f"{ra['roi_pct']:+.2f}%", f"{rb['roi_pct']:+.2f}%",
             f"{rb['roi_pct'] - ra['roi_pct']:+.2f} pp"),
            ("Total pips", f"{ra['total_pips']:+,.1f}", f"{rb['total_pips']:+,.1f}",
             f"{rb['total_pips'] - ra['total_pips']:+,.1f}"),
            ("Win rate", f"{ra['WR']:.1f}%", f"{rb['WR']:.1f}%",
             f"{rb['WR'] - ra['WR']:+.1f} pp"),
            ("Profit factor", f"{ra['PF']:.2f}", f"{rb['PF']:.2f}",
             f"{rb['PF'] - ra['PF']:+.2f}"),
            ("Expectancy (R/trade)", f"{ra['expR']:+.3f}R", f"{rb['expR']:+.3f}R",
             f"{rb['expR'] - ra['expR']:+.3f}R"),
            ("Bootstrap 95% CI on expectancy",
             f"[{ra['ci95'][0]:+.3f}R, {ra['ci95'][1]:+.3f}R]",
             f"[{rb['ci95'][0]:+.3f}R, {rb['ci95'][1]:+.3f}R]", ""),
            ("Max drawdown %", f"{ra['max_dd_pct']:.2f}%", f"{rb['max_dd_pct']:.2f}%",
             f"{rb['max_dd_pct'] - ra['max_dd_pct']:+.2f} pp"),
            ("Trades", ra["n"], rb["n"], rb["n"] - ra["n"]),
            ("Trades / day", f"{ra['trades_per_day']:.2f}", f"{rb['trades_per_day']:.2f}", ""),
            ("Wins / losses / scratches",
             f"{ra['wins']} / {ra['losses']} / {ra['scratches']}",
             f"{rb['wins']} / {rb['losses']} / {rb['scratches']}", ""),
        ]
        for lbl, a, b, diff in rows:
            r += 1
            ws.cell(row=r, column=1, value=lbl).font = BOLD
            ws.cell(row=r, column=2, value=a)
            ws.cell(row=r, column=3, value=b)
            ws.cell(row=r, column=4, value=diff)
            if lbl in ("Profit $", "ROI %", "Profit factor", "Expectancy (R/trade)"):
                ws.cell(row=r, column=3).font = (
                    GOOD_FONT if (rb["expR"] > 0 and rb["ci95"][0] > 0) else BAD_FONT)
        return r + 3

    r += 1
    r = block(r, "CONFIG 1 — the package's stated 'validated' config (OTE + prime KZ, disp 1.1, TP 2.5R)",
              A, B,
              "Sample far too small to decide anything: Run B's 95% CI on expectancy spans zero. "
              "The claimed 70.0% WR / PF 2.17 is not reproduced by either run.")
    r = block(r, "CONFIG 2 — the parameter set `sniper_backtest.py` actually runs (disp 0.6, TP 2.0R, no OTE)",
              A2, B2,
              "This is the usable sample (70-72 trades). Run B's 95% CI on expectancy lies entirely "
              "BELOW zero — a statistically significant losing strategy.")

    ws.cell(row=r, column=1, value="VERDICT").font = BAD_FONT
    r += 1
    for line in [
        "NOT FIT TO TRADE. On the only sample large enough to measure (Config 2, 72 trades), the "
        "honest-fill result is PF 0.59, -0.239R per trade, -30.05% ROI, with a 95% CI of "
        "[-0.454R, -0.015R] — entirely below zero.",
        "On Config 1 the honest-fill result is nominally positive (+0.80% ROI) but rests on 8 trades "
        "with a CI of [-0.625R, +0.674R]. That is noise, not an edge.",
        "The published 70.0% WR / PF 2.17 is a fill artifact. It does not survive honest fills on this "
        "broker's own bars.",
    ]:
        ws.cell(row=r, column=1, value=line).font = NOTE_FONT
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="A note on 'total pips'").font = BOLD
    r += 1
    ws.cell(row=r, column=1, value=(
        "Pips are position-weighted (R x risk_pips) so partial closes are counted correctly. Pips and "
        "dollars can disagree in sign across a mixed universe: NAS100 risk is measured in index points "
        "at $1.00/point while FX pips are worth $6.70-$12.50, so NAS100 dominates the pip total while "
        "position sizing normalises its dollar impact. Dollars and ROI are the meaningful figures.")
    ).font = NOTE_FONT
    ws.merge_cells(start_row=r, start_column=1, end_row=r + 1, end_column=5)


def sheet_ledger(wb, name, run, note):
    ws = wb.create_sheet(name)
    title(ws, name, note, span=17)
    cols = ["#", "Entry time (UTC)", "Exit time (UTC)", "Pair", "Direction", "Lots",
            "Entry price", "Stop", "Target (TP2)", "Exit price", "Risk (pips)",
            "Pips", "Profit $", "R multiple", "Result", "Exit reason", "Running balance $"]
    head(ws, 4, cols,
         [5, 18, 18, 10, 10, 8, 13, 13, 13, 13, 11, 10, 13, 11, 10, 20, 17])
    r = 5
    for i, t in enumerate(run["ledger"], 1):
        vals = [i, t["entry_time"], t["exit_time"], t["pair"], t["direction"], t["lots"],
                t["entry_price"], t["stop"], t["target"], t["exit_price"], t["risk_pips"],
                t["pips"], t["profit"], t["R"], t["result"], t["reason"], t["balance"]]
        for j, v in enumerate(vals, 1):
            ws.cell(row=r, column=j, value=v)
        fill = {"WIN": WIN_FILL, "LOSS": LOSS_FILL}.get(t["result"], SCR_FILL)
        ws.cell(row=r, column=15).fill = fill
        for col in (12,):
            ws.cell(row=r, column=col).number_format = PIPS
        for col in (13, 17):
            ws.cell(row=r, column=col).number_format = MONEY
        r += 1
    ws.cell(row=r + 1, column=1, value="TOTAL").font = BOLD
    ws.cell(row=r + 1, column=12, value=round(run["total_pips"], 1)).font = BOLD
    ws.cell(row=r + 1, column=12).number_format = PIPS
    ws.cell(row=r + 1, column=13, value=round(run["profit"], 2)).font = BOLD
    ws.cell(row=r + 1, column=13).number_format = MONEY
    ws.cell(row=r + 1, column=17, value=round(run["end_balance"], 2)).font = BOLD
    ws.cell(row=r + 1, column=17).number_format = MONEY


def periods(run, start_ms, end_ms, kind):
    """Continuous timeline including flat periods."""
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
    if kind == "weekly":
        start -= timedelta(days=start.weekday())
    elif kind == "monthly":
        start = start.replace(day=1)

    def nxt(dt):
        if kind == "daily":
            return dt + timedelta(days=1)
        if kind == "weekly":
            return dt + timedelta(days=7)
        return (dt.replace(day=28) + timedelta(days=4)).replace(day=1)

    buckets = []
    cur = start
    while cur <= end:
        buckets.append((cur, nxt(cur)))
        cur = nxt(cur)

    rows = []
    bal = float(run["ledger"][0]["balance"]) - float(run["ledger"][0]["profit"]) \
        if run["ledger"] else 100_000.0
    trades = run["ledger"]
    idx = 0
    cum_start = bal
    for a, b in buckets:
        open_bal = bal
        n = 0
        while idx < len(trades) and \
                datetime.fromtimestamp(trades[idx]["entry_ms"] / 1000, tz=timezone.utc) < b:
            bal = trades[idx]["balance"]
            n += 1
            idx += 1
        rows.append({
            "start": a.strftime("%Y-%m-%d"),
            "end": (b - timedelta(days=1)).strftime("%Y-%m-%d"),
            "open": open_bal, "close": bal, "profit": bal - open_bal,
            "roi": (bal - open_bal) / open_bal * 100 if open_bal else 0.0,
            "cum": (bal - cum_start) / cum_start * 100 if cum_start else 0.0,
            "n": n,
        })
    return rows


def sheet_roi(wb, name, rows, note):
    ws = wb.create_sheet(name)
    title(ws, name, note, span=7)
    head(ws, 4, ["Period start", "Period end", "Open balance $", "Close balance $",
                 "Profit $", "Period ROI %", "Cumulative ROI %", "Trades"],
         [14, 14, 16, 16, 14, 13, 17, 9])
    r = 5
    for row in rows:
        ws.cell(row=r, column=1, value=row["start"])
        ws.cell(row=r, column=2, value=row["end"])
        ws.cell(row=r, column=3, value=round(row["open"], 2)).number_format = MONEY
        ws.cell(row=r, column=4, value=round(row["close"], 2)).number_format = MONEY
        ws.cell(row=r, column=5, value=round(row["profit"], 2)).number_format = MONEY
        ws.cell(row=r, column=6, value=round(row["roi"], 3)).number_format = PCT
        ws.cell(row=r, column=7, value=round(row["cum"], 3)).number_format = PCT
        ws.cell(row=r, column=8, value=row["n"])
        if row["profit"] < -1e-9:
            for j in range(1, 9):
                ws.cell(row=r, column=j).fill = LOSS_FILL
        elif row["profit"] > 1e-9:
            for j in range(1, 9):
                ws.cell(row=r, column=j).fill = WIN_FILL
        r += 1


def sheet_bugs(wb, d):
    ws = wb.create_sheet("Bug Impact")
    title(ws, "The four fill bugs — measured cost",
          "Each row toggles ONE fix on the as-uploaded engine, everything else held identical. "
          "Deltas are (single fix applied) minus (as uploaded). The combined row applies all four. "
          "Config 2 (70-72 trades) is the sample to read; Config 1 (7-8 trades) is shown for "
          "completeness only.", span=9)

    effect = {
        "fill": "Fills trades that never actually filled — inventing entries at prices the "
                "market only grazed, always at the most favourable point of the bar.",
        "spread": "Books every trade at the mid price. Targets sit one spread closer than they "
                  "really are and stops one spread further, so winners are overstated and losers "
                  "understated on every single trade.",
        "sameber": "Turns full losses into partial wins. Any bar volatile enough to sweep both the "
                   "target and the stop is scored +0.5R instead of -1R.",
        "denom": "Inflates the reported win rate by removing break-even trades from the "
                 "denominator, so the headline WR is computed over a smaller, friendlier base.",
    }
    bugs = [
        ("fill", "Bug 1 — touch-fill, not trade-through",
         "sniper_backtest.py ~L114: `if swept==\"bull\" and ck[\"l\"]<=zone_mid: entry=zone_mid`. "
         "A resting limit order needs price to trade THROUGH the level; a bar whose low merely "
         "equals it is not a guaranteed fill.",
         "ISOLATED"),
        ("spread", "Bug 2 — spread computed then discarded",
         "sniper_backtest.py ~L124: `entry_eff = entry + sign*sp  # pay spread on entry`. "
         "`entry_eff` appears exactly ONCE in the whole file — tp1, tp2, the stop comparison and "
         "the final realised R all use raw `entry`. Every trade is booked spread-free.",
         "ISOLATED"),
        ("sameber", "Bug 3 — TP1 booked before the same-bar stop check",
         "sniper_backtest.py ~L129-132: the TP1/partial-close branch runs before the stop branch "
         "inside the same bar, so a bar that traded through BOTH the target and the stop is scored "
         "as a partial win instead of a loss.",
         "ISOLATED"),
        ("denom", "Bug 4 — scratches dropped from the win-rate denominator",
         "sniper_backtest.py ~L148: `dec=wins+losses; wr=wins/dec*100` excludes `be_ct`, so "
         "break-even trades are removed from the denominator and the win rate is inflated.",
         "ISOLATED"),
    ]

    r = 4
    for cfg_label, base_key, pref in [
        ("CONFIG 2 — sniper_backtest.py's own defaults (70-72 trades; READ THIS ONE)",
         "as_uploaded_shipdefaults", "shipdefaults_only_"),
        ("CONFIG 1 — the package's stated 'validated' config (7-8 trades; too few to mean anything)",
         "as_uploaded", "only_"),
    ]:
        base = d["runs"][base_key]
        ws.cell(row=r, column=1, value=cfg_label).font = TITLE_FONT
        r += 1
        head(ws, r, ["Bug", "What it does", "Where / why it is wrong", "Isolated?",
                     "WR delta", "PF delta", "Expectancy delta", "ROI delta", "Trades"],
             [42, 46, 62, 12, 12, 12, 17, 12, 9])
        ws.freeze_panes = None
        r += 1
        for key, nm, desc, iso in bugs:
            run = d["runs"][pref + key]
            ws.cell(row=r, column=1, value=nm).font = BOLD
            ws.cell(row=r, column=2, value=effect[key]).alignment = Alignment(
                wrap_text=True, vertical="top")
            ws.cell(row=r, column=3, value=desc)
            ws.cell(row=r, column=4, value=iso)
            ws.cell(row=r, column=5, value=f"{run['WR'] - base['WR']:+.1f} pp")
            ws.cell(row=r, column=6, value=f"{run['PF'] - base['PF']:+.2f}")
            ws.cell(row=r, column=7, value=f"{run['expR'] - base['expR']:+.3f}R")
            ws.cell(row=r, column=8, value=f"{run['roi_pct'] - base['roi_pct']:+.2f} pp")
            ws.cell(row=r, column=9, value=run["n"])
            for j in range(5, 9):
                ws.cell(row=r, column=j).alignment = Alignment(horizontal="center")
            ws.cell(row=r, column=3).alignment = Alignment(wrap_text=True, vertical="top")
            r += 1
        comb = d["runs"]["honest_shipdefaults" if pref.startswith("ship") else "honest"]
        ws.cell(row=r, column=1, value="ALL FOUR COMBINED (= Run B)").font = BAD_FONT
        ws.cell(row=r, column=2, value="Run B, honest fills")
        ws.cell(row=r, column=3, value="Not additive: the fill and spread fixes change which "
                                        "setups clear the minimum-risk gate, which shifts the "
                                        "non-overlap sequencing downstream.")
        ws.cell(row=r, column=3).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r, column=4, value="COMBINED")
        ws.cell(row=r, column=5, value=f"{comb['WR'] - base['WR']:+.1f} pp").font = BAD_FONT
        ws.cell(row=r, column=6, value=f"{comb['PF'] - base['PF']:+.2f}").font = BAD_FONT
        ws.cell(row=r, column=7, value=f"{comb['expR'] - base['expR']:+.3f}R").font = BAD_FONT
        ws.cell(row=r, column=8, value=f"{comb['roi_pct'] - base['roi_pct']:+.2f} pp").font = BAD_FONT
        ws.cell(row=r, column=9, value=comb["n"])
        r += 3

    # ---- a fifth defect, found while reading the ledger. Disclosed, NOT fixed:
    # fixing it would change the strategy, which is out of scope for this A/B.
    ws.cell(row=r, column=1, value="A FIFTH DEFECT — found in the ledger, disclosed but NOT fixed").font = BAD_FONT
    r += 1
    inv = {}
    for k in ("as_uploaded", "honest", "as_uploaded_shipdefaults", "honest_shipdefaults"):
        run = d["runs"][k]
        bad = [t for t in run["trades"]
               if (t["direction"] == "long" and t["sl_initial"] >= t["entry"])
               or (t["direction"] == "short" and t["sl_initial"] <= t["entry"])]
        inv[k] = (len(bad), sum(t["R"] for t in bad), sum(t["R"] for t in run["trades"]))
    for line in [
        "The engine never checks that the stop is on the LOSING side of the entry. SL is placed at "
        "`sweep_ext -/+ sl_buf*ATR` while entry is the FVG midpoint, and risk is taken as "
        "`abs(entry-sl)` — which hides the sign. When a deep retrace puts the zone midpoint beyond the "
        "sweep extreme, a long is opened with its stop ABOVE the entry and its targets above it too. "
        "Such a trade is stopped out on its own fill bar: a structurally guaranteed -1R.",
        f"Config 1 (honest): {inv['honest'][0]} of {d['runs']['honest']['n']} trades "
        f"({inv['honest'][0] / max(d['runs']['honest']['n'], 1) * 100:.0f}%), contributing "
        f"{inv['honest'][1]:+.2f}R of a {inv['honest'][2]:+.2f}R total. Those two trades are the whole "
        "difference between Run B reading positive and negative on that config.",
        f"Config 2 (honest): {inv['honest_shipdefaults'][0]} of {d['runs']['honest_shipdefaults']['n']} "
        f"trades ({inv['honest_shipdefaults'][0] / max(d['runs']['honest_shipdefaults']['n'], 1) * 100:.0f}%), "
        f"contributing {inv['honest_shipdefaults'][1]:+.2f}R of a {inv['honest_shipdefaults'][2]:+.2f}R total — "
        "a small part of the damage there. Config 2 loses on its own merits.",
        "This was left in deliberately. The brief was to correct four fill bugs and change nothing else; "
        "adding an entry-validity gate would be a strategy change and would break the A/B comparison.",
        "",
    ]:
        ws.cell(row=r, column=1, value=line).font = NOTE_FONT
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=9)
        r += 1

    for line in [
        "Why 'fill' and 'denom' measure zero on this data:",
        "  fill  — an exact touch (bar extreme equal to the zone midpoint to float precision) does "
        "occur in this data: 1,336 times across 409,112 bar/zone pairs, about 0.33%. It simply never "
        "landed on the FIRST qualifying retrace bar of an actual signal. At ~70 trades x 8 retrace "
        "bars the expected number of affected trades is only 1-2, so measuring zero here is the luck "
        "of the draw, NOT evidence the bug is harmless. On a tick-quantised feed or around round "
        "numbers it would bite. Treat this row as 'not measurable on this sample', not 'costless'.",
        "  denom — the engine books a break-even stop as +0.5R (the TP1 partial was already taken), "
        "not 0.0R, so `be_ct` was 0 in every run and the denominator never actually dropped a trade. "
        "The deeper problem is the same line: scoring a BE exit as a +0.5R WIN is what lets the "
        "reported win rate sit near 56% while the profit factor sits at 1.03.",
        "The two bugs that carry the damage are the discarded spread and the same-bar TP-before-stop "
        "ordering. Together with the sequencing they induce, they turn PF 1.03 into PF 0.59.",
    ]:
        ws.cell(row=r, column=1, value=line).font = NOTE_FONT
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=9)
        r += 1


def main() -> int:
    with open(SRC) as fh:
        d = json.load(fh)

    wb = Workbook()
    wb.remove(wb.active)

    sheet_summary(wb, d)
    B = d["runs"]["honest"]; A = d["runs"]["as_uploaded"]
    sheet_ledger(wb, "Trade Results (Honest)", B,
                 "Run B — the four fill bugs corrected. THIS IS THE BOT'S REAL PERFORMANCE. "
                 "Config 1 (the package's stated validated parameters).")
    sheet_ledger(wb, "Trade Results (As Uploaded)", A,
                 "Run A — the engine exactly as shipped, fill bugs intact. This is what the package "
                 "claims about itself. Do not read these as the bot's performance.")

    import calendar as _cal
    def _ms(s):
        return _cal.timegm(datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple()) * 1000
    win_start, win_end = _ms(d["window"]["from"]), _ms(d["window"]["to"])
    for kind, nm in [("daily", "Daily ROI"), ("weekly", "Weekly ROI"), ("monthly", "Monthly ROI")]:
        sheet_roi(wb, nm, periods(B, win_start, win_end, kind),
                  "Run B (honest fills), Config 1. Continuous timeline — flat periods with no "
                  "trades are included and shown at 0.00%.")

    sheet_bugs(wb, d)

    wb.save(DEST)
    print(f"wrote {DEST}")
    print("sheets:", wb.sheetnames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
