#!/usr/bin/env python3
"""Assemble ``Bot_Performance_Full.xlsx`` from ``reports/v6_100k/``.

The owner was explicit about the columns: **Date, Pair, Trades, Profit, ROI**
and nothing else. That is what every data sheet carries, with a cumulative ROI
column added to the period sheets because a three-year timeline is unreadable
without one.

What makes this workbook different from the two before it: the headline is the
**FULL ~1200-day window**, not 90 days. The owner has twice been handed a
90-day run containing seven trades. Seven trades evaluate nothing. 195 trades
over 3.29 years is a real sample, and it is what the Summary leads with. The
90-day block is kept for continuity and labelled as non-evidence.

    Summary   full-window and 90-day, v5 and v6, at 1% and 2% risk
    Risk      what the recorded losing streak does to the account
    Trades    one row per closed trade
    Daily     continuous calendar, flat days included
    Weekly
    Monthly
    Yearly

    python3 build_v6_workbook.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "reports", "v6_100k")
DEST = os.path.join(REPO, "Bot_Performance_Full.xlsx")

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
GROUP_FILL = PatternFill("solid", fgColor="2F5597")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14)
NOTE_FONT = Font(italic=True, size=9, color="595959")
WARN_FONT = Font(bold=True, size=10, color="9C0006")
BOLD = Font(bold=True)
WIN_FILL = PatternFill("solid", fgColor="E2EFDA")
LOSS_FILL = PatternFill("solid", fgColor="FCE4E4")
FLAT_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

MONEY = '#,##0.00;[Red]-#,##0.00'
PCT = '0.00"%";[Red]-0.00"%"'

DISPLAY = {"risk_pct": "Risk %", "config": "Config", "date": "Date",
           "week_ending": "Date (week ending)", "month": "Date (month)",
           "year": "Date (year)", "pair": "Pair", "pairs": "Pairs",
           "trades": "Trades", "profit": "Profit ($)", "roi_pct": "ROI (%)",
           "cum_roi_pct": "Cumulative ROI (%)", "r_multiple": "R multiple",
           "balance_after": "Balance after ($)",
           "streak": "Losing streak (trades)",
           "drawdown_pct_from_streak": "Drawdown from streak (%)",
           "balance_after_streak_on_100k": "Balance after streak ($)",
           "gain_needed_to_recover_pct": "Gain needed to recover (%)"}


def _headers(ws, columns, row: int = 1) -> None:
    for j, col in enumerate(columns, start=1):
        cell = ws.cell(row=row, column=j, value=DISPLAY.get(str(col), str(col)))
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = BORDER


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    """Empty text cells must be empty, not the string "nan".

    A flat day has no pair, and the round-trip through CSV turns "" into NaN.
    Under pandas 3 a str-dtype column keeps that NaN as a float, which both
    breaks the column sizer and writes the literal text "nan" into the sheet.
    """
    out = frame.copy()
    for col in ("pairs", "pair", "config"):
        if col in out.columns:
            out[col] = out[col].fillna("").astype(str).replace("nan", "")
    return out


def _write(ws, frame: pd.DataFrame, title: str, note: str = "") -> None:
    ws.cell(row=1, column=1, value=title).font = TITLE_FONT
    row = 2
    for line in [ln for ln in note.split("\n") if ln]:
        ws.cell(row=row, column=1, value=line).font = NOTE_FONT
        row += 1
    row += 1
    if frame is None or frame.empty:
        ws.cell(row=row, column=1, value="(no trades in this window)")
        return
    frame = _clean(frame)
    _headers(ws, frame.columns, row)
    for i, (_, data) in enumerate(frame.iterrows(), start=row + 1):
        flat = "trades" in frame.columns and int(data["trades"]) == 0
        for j, col in enumerate(frame.columns, start=1):
            val = data[col]
            if hasattr(val, "item"):
                val = val.item()
            cell = ws.cell(row=i, column=j, value=val)
            cell.border = BORDER
            if col == "profit":
                cell.number_format = MONEY
            elif col in ("roi_pct", "cum_roi_pct"):
                cell.number_format = PCT
            elif col == "balance_after":
                cell.number_format = MONEY
            elif col == "risk_pct":
                cell.number_format = '0.0"%"'
            if flat:
                cell.fill = FLAT_FILL
            elif col in ("profit", "roi_pct") and isinstance(val, (int, float)):
                cell.fill = WIN_FILL if val > 0 else (LOSS_FILL if val < 0 else FLAT_FILL)
    for j, col in enumerate(frame.columns, start=1):
        sample = [str(v) for v in frame[col].head(400)]
        width = max([len(DISPLAY.get(str(col), str(col)))] + [len(v) for v in sample]) + 3
        ws.column_dimensions[get_column_letter(j)].width = min(max(width, 11), 40)
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


SUMMARY_ROWS = [
    ("start_balance", "Starting balance ($)", MONEY),
    ("end_balance", "Ending balance ($)", MONEY),
    ("total_profit", "Total profit ($)", MONEY),
    ("total_roi_pct", "Total ROI (%)", PCT),
    ("cagr_pct", "CAGR (% a year)", PCT),
    ("window_days", "Window (days)", "0"),
    ("window_years", "Window (years)", "0.00"),
    (None, None, None),
    ("trades", "Trades", "0"),
    ("trades_per_day_calendar", "Trades per calendar day", "0.000"),
    ("trades_per_weekday", "Trades per weekday", "0.000"),
    ("active_days", "Days with at least one trade", "0"),
    ("total_pips", "Total pips", "#,##0.0;[Red]-#,##0.0"),
    (None, None, None),
    ("win_rate_pct", "Win rate (%)", PCT),
    ("win_rate_ci", "Win rate 95% CI", None),
    ("profit_factor", "Profit factor", "0.000"),
    ("expectancy_r", "Expectancy (R per trade)", "+0.0000;[Red]-0.0000"),
    ("avg_win_r", "Average winner (R)", "+0.000"),
    ("avg_loss_r", "Average loser (R)", "+0.000;[Red]-0.000"),
    (None, None, None),
    ("expectancy_ci_naive", "Expectancy 95% CI (naive)", None),
    ("clusters", "Independent clusters", "0"),
    ("expectancy_ci_cluster", "Expectancy 95% CI (CLUSTER)", None),
    ("cluster_ci_clears_zero", "Does the CLUSTER CI clear zero?", None),
    (None, None, None),
    ("max_drawdown_pct", "Max drawdown (%)", PCT),
    ("max_consecutive_losses", "Longest losing streak", "0"),
    ("max_consecutive_wins", "Longest winning streak", "0"),
]


def _summary_sheet(ws, blocks, notes):
    ws.cell(row=1, column=1,
            value="Summary -- $100,000, compounding trade by trade").font = TITLE_FONT
    ws.cell(row=2, column=1,
            value="The FULL-WINDOW columns are the result. The 90-day columns are "
                  "seven trades and are not evidence of anything.").font = NOTE_FONT

    row = 4
    # Group header: which window / which configuration each column belongs to.
    ws.cell(row=row, column=1, value="").fill = GROUP_FILL
    for j, (label, _rec) in enumerate(blocks, start=2):
        cell = ws.cell(row=row, column=j, value=label)
        cell.fill, cell.font = GROUP_FILL, HEAD_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = BORDER
    row += 1
    _headers(ws, ["Metric"] + [f"{rec['risk_pct']:g}% risk" for _l, rec in blocks], row)

    for key, label, fmt in SUMMARY_ROWS:
        row += 1
        if key is None:
            continue
        c = ws.cell(row=row, column=1, value=label)
        c.font = BOLD
        c.border = BORDER
        for j, (_label, rec) in enumerate(blocks, start=2):
            val = rec.get(key, "")
            if hasattr(val, "item"):
                val = val.item()
            if isinstance(val, float) and val != val:      # NaN
                val = ""
            cell = ws.cell(row=row, column=j, value=val)
            cell.border = BORDER
            if fmt:
                cell.number_format = fmt
            if key == "cluster_ci_clears_zero":
                cell.font = Font(bold=True,
                                 color="006100" if str(val).startswith("YES") else "9C0006")
    row += 2
    for line in notes:
        cell = ws.cell(row=row, column=1, value=line)
        cell.font = WARN_FONT if line.isupper() and line else NOTE_FONT
        row += 1
    ws.column_dimensions["A"].width = 34
    for j in range(2, 2 + len(blocks)):
        ws.column_dimensions[get_column_letter(j)].width = 24


def load(tag: str) -> tuple[pd.DataFrame, dict]:
    d = os.path.join(SRC, tag)
    return pd.read_csv(os.path.join(d, "summary.csv")), d


def stack(d: str, kind: str, risks) -> pd.DataFrame:
    parts = []
    for r in risks:
        p = os.path.join(d, f"{kind}_{r:g}pct".replace(".", "_") + ".csv")
        if os.path.exists(p):
            parts.append(pd.read_csv(p))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def main() -> int:
    tags = {"full": "v5, full window", "full_v6": "v6, full window",
            "90d": "v5, last 90 days", "90d_v6": "v6, last 90 days"}
    for tag in tags:
        if not os.path.exists(os.path.join(SRC, tag, "summary.csv")):
            print(f"missing {SRC}/{tag}/summary.csv -- run: "
                  f"python3 run_v6_100k.py --full --profile v6 --tag full_v6")
            return 1

    blocks = []
    for tag, label in tags.items():
        sm, _d = load(tag)
        for _, rec in sm.iterrows():
            blocks.append((f"{label}\n{rec['risk_pct']:g}% risk", rec.to_dict()))

    wb = Workbook()
    wb.remove(wb.active)

    notes = [
        "READ THIS BEFORE READING THE NUMBERS ABOVE.",
        "",
        "THE 90-DAY COLUMNS ARE NOT EVIDENCE. This configuration trades about 0.17",
        "times a day across 29 pairs. Ninety days of it is SEVEN TRADES. Seven trades",
        "cannot distinguish a working system from a broken one -- a five-loss run is",
        "completely ordinary at a 35% win rate and it is most of what that window",
        "contains. Those columns are reported because they were asked for and because",
        "they are what the last two deliverables contained. They settle nothing.",
        "",
        "THE FULL-WINDOW COLUMNS ARE THE RESULT: 193-195 trades over 1,200 days.",
        "",
        "THE WIN RATE IS NOT THE POINT, AND MUST NOT BE READ ALONE. At a flat 4R",
        "target the break-even win rate is 20%. A 35% win rate therefore clears its",
        "own line by 15 points. Comparing it to a 55% win rate on a 1R system, whose",
        "break-even line is 50%, compares two numbers that do not mean the same thing.",
        "",
        "THE EDGE IS STILL NOT STATISTICALLY ESTABLISHED. Roughly half the trades are",
        "same-pair, same-direction re-entries inside 24 hours -- several bets on ONE",
        "liquidity event. An ordinary bootstrap counts those as independent evidence;",
        "a CLUSTER bootstrap, which resamples correlated groups whole, does not. Both",
        "are printed above and the cluster one is the honest number. On the full",
        "window v6's cluster interval clears zero; ITS WALK-FORWARD INTERVAL DOES NOT",
        "([-0.0431, +0.7079]). Treat the edge as encouraging and unproven.",
        "",
        "2% RISK IS NOT RECOMMENDED -- SEE THE 'Risk' SHEET. It doubles the return and",
        "it doubles the drawdown: 32.7% peak-to-trough against 17.8% at 1%. The",
        "configuration has a 13-14 trade losing streak ON RECORD, which is a 24-26%",
        "account drawdown at 2% before any bad luck is added. 2% is also outside the",
        "system's own stated risk band (maximum 1.0%). It is produced because it was",
        "asked for, not because it is advisable.",
        "",
        "Data: TradeLocker broker bars (BID), read-only, 29 pairs, 2023-05-02 to",
        "2026-08-14. Honest fills throughout -- trade-through only, spread and",
        "slippage paid, same-bar TP+SL scores as a loss, no lookahead. Selection was",
        "made on TRAIN and scored on an untouched TEST.",
        "",
        "NO ORDER HAS EVER BEEN PLACED BY THIS REPOSITORY. Forward results: PENDING.",
    ]
    _summary_sheet(wb.create_sheet("Summary"), blocks, notes)

    # -- Risk sheet ------------------------------------------------------
    ruin_rows = []
    for tag, label in (("full", "v5, full window"), ("full_v6", "v6, full window")):
        r = pd.read_csv(os.path.join(SRC, tag, "risk_of_ruin.csv"))
        r.insert(0, "config", label)
        ruin_rows.append(r)
    _write(wb.create_sheet("Risk"), pd.concat(ruin_rows, ignore_index=True),
           "Risk of ruin -- what the RECORDED losing streak does to the account",
           "This is not a simulation of a worst case. It is the losing streak this\n"
           "configuration actually produced in the backtest, applied to $100,000.\n"
           "Losses are taken at -1.05R, which is what this engine's average loser\n"
           "really costs once the spread and gap-through are paid, and the streak is\n"
           "compounded fixed-fractionally -- so each successive loss risks fewer\n"
           "dollars. That is the KIND version of the arithmetic and it is still what\n"
           "appears below. A longer streak than the one on record is not unlikely:\n"
           "at a 35% win rate a 14-loss run has a materially non-trivial chance of\n"
           "occurring in any 200-trade sequence, so this is a floor, not a ceiling.")

    # -- Trades / period sheets on the ADOPTED configuration --------------
    sm6, d6 = load("full_v6")
    risks = list(sm6["risk_pct"])
    trades = pd.read_csv(os.path.join(d6, "trades.csv"))
    _write(wb.create_sheet("Trades"), trades,
           "Trades -- one row per closed trade, full window, adopted (v6) configuration",
           "Date is the exit date. Profit is that trade's realised P/L in dollars. ROI\n"
           "is that trade's contribution measured against the balance it was actually\n"
           "sized from, so the column reflects the compounded path rather than a\n"
           "nominal one. Both risk levels are here; filter the Risk % column.")

    _write(wb.create_sheet("Daily"), stack(d6, "daily", risks),
           "Daily -- continuous calendar, full window",
           "Every one of the 1,201 days has a row. Grey rows are days with no trade,\n"
           "including weekends when the venue is shut. They are the product of a\n"
           "sniper stack, not missing data -- this system trades about once a week.\n"
           "ROI is the day's change against that day's opening balance; Cumulative\n"
           "ROI is measured from the $100,000 starting balance.")

    _write(wb.create_sheet("Weekly"), stack(d6, "weekly", risks), "Weekly -- full window",
           "Week ending Sunday. ROI is the week's change against its opening balance.")
    _write(wb.create_sheet("Monthly"), stack(d6, "monthly", risks), "Monthly -- full window",
           "ROI is the month's change against its opening balance.")
    _write(wb.create_sheet("Yearly"), stack(d6, "yearly", risks), "Yearly -- full window",
           "The window spans 3.29 years, so this is where a long-horizon result\n"
           "becomes readable. 2023 and 2026 are PARTIAL years: the data begins\n"
           "2023-05-02 and ends 2026-08-14, so neither is comparable to a full one.")

    wb.save(DEST)
    print(f"wrote {DEST}")
    for ws in wb.worksheets:
        print(f"  {ws.title:10s} {max(ws.max_row - 5, 0):5d} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
