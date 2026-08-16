#!/usr/bin/env python3
"""Assemble ``Bot_Performance_90d.xlsx`` from ``reports/v5_100k/``.

The owner was explicit about the columns: **Date, Pair, Trades, Profit, ROI**
and nothing else. So that is what every data sheet carries. Both risk levels
live in the same sheets behind a Risk % column rather than in parallel
workbooks, so a reader can sort one column and see both.

    Trades    one row per trade
    Daily     continuous calendar, flat days included
    Weekly
    Monthly
    Summary   start/end balance, profit, ROI, WR, PF, max DD, trades, per-day

Every piece of validation detail -- splits, walk-forward, matched-R control,
perturbation, the audit -- stays in the skill doc and in
``SMC_Sniper_Backtest.xlsx``. This file is the money view.

    python3 build_v5_workbook.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "reports", "v5_100k")
DEST = os.path.join(REPO, "Bot_Performance_90d.xlsx")

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14)
NOTE_FONT = Font(italic=True, size=9, color="595959")
BOLD = Font(bold=True)
WIN_FILL = PatternFill("solid", fgColor="E2EFDA")
LOSS_FILL = PatternFill("solid", fgColor="FCE4E4")
FLAT_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

MONEY = '#,##0.00;[Red]-#,##0.00'
PCT = '0.00"%";[Red]-0.00"%"'

DISPLAY = {"risk_pct": "Risk %", "date": "Date", "week_ending": "Date (week ending)",
           "month": "Date (month)", "pair": "Pair", "pairs": "Pair",
           "trades": "Trades", "profit": "Profit ($)", "roi_pct": "ROI (%)"}


def _headers(ws, columns, row: int = 1) -> None:
    for j, col in enumerate(columns, start=1):
        cell = ws.cell(row=row, column=j, value=DISPLAY.get(str(col), str(col)))
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = BORDER


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
            elif col == "roi_pct":
                cell.number_format = PCT
            elif col == "risk_pct":
                cell.number_format = '0.0"%"'
            if flat:
                cell.fill = FLAT_FILL
            elif col in ("profit", "roi_pct") and isinstance(val, (int, float)):
                cell.fill = WIN_FILL if val > 0 else (LOSS_FILL if val < 0 else FLAT_FILL)
    for j, col in enumerate(frame.columns, start=1):
        sample = frame[col].astype(str).head(400)
        width = max([len(DISPLAY.get(str(col), str(col)))] + [len(v) for v in sample]) + 3
        ws.column_dimensions[get_column_letter(j)].width = min(max(width, 11), 40)
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _summary_sheet(ws, summary: pd.DataFrame, notes: list[str]) -> None:
    ws.cell(row=1, column=1, value="Summary -- 90 days, $100,000, compounding").font = TITLE_FONT
    row = 3
    labels = [
        ("start_balance", "Starting balance ($)", MONEY),
        ("end_balance", "Ending balance ($)", MONEY),
        ("total_profit", "Total profit ($)", MONEY),
        ("total_roi_pct", "Total ROI (%)", PCT),
        ("trades", "Trades", "0"),
        ("win_rate_pct", "Win rate (%)", PCT),
        ("win_rate_ci", "Win rate 95% CI", None),
        ("profit_factor", "Profit factor", "0.000"),
        ("expectancy_r", "Expectancy (R/trade)", "+0.0000;[Red]-0.0000"),
        ("expectancy_ci", "Expectancy 95% CI", None),
        ("ci_clears_zero", "Does the CI clear zero?", None),
        ("max_drawdown_pct", "Max drawdown (%)", PCT),
        ("max_consecutive_losses", "Longest losing streak", "0"),
        ("trades_per_day_calendar", "Trades per calendar day", "0.000"),
        ("trades_per_weekday", "Trades per weekday", "0.000"),
        ("active_days", "Days with at least one trade", "0"),
        ("window_days", "Window (days)", "0"),
    ]
    risks = list(summary["risk_pct"])
    header = ["Metric"] + [f"{r:g}% risk" for r in risks]
    _headers(ws, header, row)
    for key, label, fmt in labels:
        row += 1
        c = ws.cell(row=row, column=1, value=label)
        c.font = BOLD
        c.border = BORDER
        for j, (_, rec) in enumerate(summary.iterrows(), start=2):
            val = rec[key]
            if hasattr(val, "item"):
                val = val.item()
            cell = ws.cell(row=row, column=j, value=val)
            cell.border = BORDER
            if fmt:
                cell.number_format = fmt
    row += 2
    for line in notes:
        ws.cell(row=row, column=1, value=line).font = NOTE_FONT
        row += 1
    ws.column_dimensions["A"].width = 34
    for j in range(2, 2 + len(risks)):
        ws.column_dimensions[get_column_letter(j)].width = 26


def main() -> int:
    need = ["trades.csv", "summary.csv"]
    for f in need:
        if not os.path.exists(os.path.join(SRC, f)):
            print(f"missing {SRC}/{f} -- run: python3 run_v5_100k.py")
            return 1
    trades = pd.read_csv(os.path.join(SRC, "trades.csv"))
    summary = pd.read_csv(os.path.join(SRC, "summary.csv"))

    def stack(kind: str) -> pd.DataFrame:
        parts = []
        for r in summary["risk_pct"]:
            tag = f"{r:g}pct".replace(".", "_")
            p = os.path.join(SRC, f"{kind}_{tag}.csv")
            if os.path.exists(p):
                parts.append(pd.read_csv(p))
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    daily, weekly, monthly = stack("daily"), stack("weekly"), stack("monthly")

    wb = Workbook()
    wb.remove(wb.active)

    _write(wb.create_sheet("Trades"), trades,
           "Trades -- one row per closed trade",
           "Date is the exit date. Profit is that trade's realised P/L in dollars.\n"
           "ROI is that trade's contribution measured against the balance it was\n"
           "actually sized from, so the column reflects the compounded path.\n"
           "Both risk levels are here; filter the Risk % column for one of them.")

    _write(wb.create_sheet("Daily"), daily,
           "Daily -- continuous calendar",
           "Every day in the window has a row. Grey rows are days with no trade,\n"
           "including weekends when the venue is shut. They are the product, not\n"
           "missing data. ROI is the day's change against that day's opening balance.")

    _write(wb.create_sheet("Weekly"), weekly, "Weekly",
           "Week ending Sunday. ROI is the week's change against its opening balance.")

    _write(wb.create_sheet("Monthly"), monthly, "Monthly",
           "ROI is the month's change against its opening balance.")

    notes = [
        "90 days is a shape check, not a performance claim. Read the multi-year",
        "validation and the confidence intervals in the skill doc before quoting",
        "any of this. A configuration whose expectancy CI still spans zero has not",
        "been shown to make money, and 2% risk on such a configuration compounds",
        "the uncertainty rather than the edge.",
        "",
        "Data: TradeLocker broker bars (BID), read-only. Honest fills throughout --",
        "trade-through only, spread and slippage paid, same-bar TP+SL scores as a",
        "loss. No order was ever placed.",
    ]
    _summary_sheet(wb.create_sheet("Summary"), summary, notes)
    wb.move_sheet("Summary", offset=-4)

    wb.save(DEST)
    print(f"wrote {DEST}")
    for ws in wb.worksheets:
        print(f"  {ws.title:10s} {ws.max_row - 4:5d} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
