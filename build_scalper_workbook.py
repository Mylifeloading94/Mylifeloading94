#!/usr/bin/env python3
"""Assemble ``SMC_Scalper_Results.xlsx`` from ``reports/scalp100k/``.

The owner asked for a CLEAN workbook -- "only ROI and profit" -- so this is
deliberately five sheets and nothing else:

    Summary       the headline money numbers, nothing else
    Trade Results one row per trade, money and pips up front
    Daily ROI     continuous calendar, flat days included
    Weekly ROI
    Monthly ROI

Every piece of validation detail (splits, walk-forward, matched-R control,
perturbation, per-pair breakdowns) stays in ``SMC_Sniper_Backtest.xlsx`` and
the skill doc, which is where it was asked to live. This file is the money
view.

    python3 build_scalper_workbook.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "reports", "scalp100k")
DEST = os.path.join(REPO, "SMC_Scalper_Results.xlsx")

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14)
NOTE_FONT = Font(italic=True, size=9, color="595959")
BOLD = Font(bold=True)
WIN_FILL = PatternFill("solid", fgColor="E2EFDA")
LOSS_FILL = PatternFill("solid", fgColor="FCE4E4")
CLOSED_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

MONEY = '#,##0.00;[Red]-#,##0.00'
PCT = '0.00"%";[Red]-0.00"%"'
PIPS = '0.0;[Red]-0.0'


def _headers(ws, columns, row: int = 1) -> None:
    for j, col in enumerate(columns, start=1):
        cell = ws.cell(row=row, column=j, value=str(col))
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = BORDER


def _autosize(ws, frame: pd.DataFrame, offset: int = 0) -> None:
    for j, col in enumerate(frame.columns, start=1 + offset):
        sample = frame[col].astype(str).head(300)
        width = max([len(str(col))] + [len(v) for v in sample]) + 3
        ws.column_dimensions[get_column_letter(j)].width = min(max(width, 10), 24)


NUMBER_FORMATS = {
    "profit_usd": MONEY, "running_balance": MONEY, "start_balance": MONEY,
    "end_balance": MONEY, "gain_usd": MONEY,
    "period_roi_pct": PCT, "cumulative_roi_pct": PCT,
    "pips": PIPS, "r_multiple": "0.000",
    "entry_price": "0.00000", "stop_price": "0.00000",
    "target_price": "0.00000", "exit_price": "0.00000",
    "position_size_lots": "0.0000",
}


def _write_table(ws, frame: pd.DataFrame, title: str, note: str = "") -> None:
    ws.cell(row=1, column=1, value=title).font = TITLE_FONT
    row = 2
    if note:
        ws.cell(row=row, column=1, value=note).font = NOTE_FONT
        row += 1
    row += 1
    if frame is None or frame.empty:
        ws.cell(row=row, column=1, value="(no trades in this window)")
        return
    _headers(ws, frame.columns, row)
    for i, (_, data) in enumerate(frame.iterrows(), start=row + 1):
        for j, col in enumerate(frame.columns, start=1):
            val = data[col]
            if hasattr(val, "item"):
                try:
                    val = val.item()
                except (ValueError, AttributeError):
                    val = str(val)
            cell = ws.cell(row=i, column=j, value=val)
            cell.border = BORDER
            if col in NUMBER_FORMATS:
                cell.number_format = NUMBER_FORMATS[col]
        if "result" in frame.columns:
            fill = WIN_FILL if data["result"] == "WIN" else LOSS_FILL
            ws.cell(row=i, column=list(frame.columns).index("result") + 1).fill = fill
        elif data.get("market_open") == "closed":
            for j in range(1, len(frame.columns) + 1):
                ws.cell(row=i, column=j).fill = CLOSED_FILL
    _autosize(ws, frame)
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _num(value):
    """Coerce a summary value to a real number where it is one.

    ``summary.csv`` carries dates and numbers in one column, so pandas types it
    as ``object`` and every figure arrives as a string. Excel then stores the
    headline money numbers as TEXT -- right-aligned formats ignored, no
    arithmetic, a little green triangle in the corner of every cell. Silently
    shipping the owner's ROI as a string is a bad way to fail.
    """
    if value is None or isinstance(value, (int, float)):
        return value
    try:
        text = str(value).strip()
        return int(text) if text.lstrip("-").isdigit() else float(text)
    except (TypeError, ValueError):
        return value


def build_summary_sheet(ws, summary: pd.DataFrame) -> None:
    val = {r["metric"]: _num(r["value"]) for _, r in summary.iterrows()}
    ws.cell(row=1, column=1, value="SMC Scalper -- Results Summary").font = TITLE_FONT
    raw = {r["metric"]: r["value"] for _, r in summary.iterrows()}
    ws.cell(row=2, column=1,
            value=(f"{raw.get('window_start')} to {raw.get('window_end')}  ·  "
                   f"{val.get('window_days')} days  ·  "
                   f"{val.get('risk_per_trade_pct')}% risk per trade  ·  "
                   f"compounding")).font = NOTE_FONT

    blocks = [
        ("THE MONEY", [
            ("Starting balance", val.get("starting_balance_usd"), MONEY),
            ("Ending balance", val.get("ending_balance_usd"), MONEY),
            ("Total profit ($)", val.get("total_profit_usd"), MONEY),
            ("Total ROI (%)", val.get("total_roi_pct"), PCT),
        ]),
        ("THE RECORD", [
            ("Win rate (%)", val.get("win_rate_pct"), PCT),
            ("Profit factor", val.get("profit_factor"), "0.000"),
            ("Max drawdown (%)", val.get("max_drawdown_pct"), PCT),
            ("Trades", val.get("trades"), "#,##0"),
            ("Trades per day", val.get("trades_per_day"), "0.00"),
        ]),
    ]
    row = 4
    for header, items in blocks:
        cell = ws.cell(row=row, column=1, value=header)
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
        ws.cell(row=row, column=2).fill = HEAD_FILL
        row += 1
        for label, value, fmt in items:
            ws.cell(row=row, column=1, value=label).font = BOLD
            cell = ws.cell(row=row, column=2, value=value)
            cell.number_format = fmt
            cell.alignment = Alignment(horizontal="right")
            for col in (1, 2):
                ws.cell(row=row, column=col).border = BORDER
            row += 1
        row += 1

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 18


def main() -> int:
    if not os.path.exists(os.path.join(SRC, "summary.csv")):
        raise SystemExit(f"{SRC}/summary.csv missing -- run run_scalp_100k.py first")

    summary = pd.read_csv(os.path.join(SRC, "summary.csv"))
    trades = pd.read_csv(os.path.join(SRC, "trade_results.csv"))
    daily = pd.read_csv(os.path.join(SRC, "daily.csv"))
    weekly = pd.read_csv(os.path.join(SRC, "weekly.csv"))
    monthly = pd.read_csv(os.path.join(SRC, "monthly.csv"))

    wb = Workbook()
    build_summary_sheet(wb.active, summary)
    wb.active.title = "Summary"

    _write_table(wb.create_sheet("Trade Results"), trades,
                 "Trade Results -- every trade, in order",
                 "Pips and profit are net of spread, slippage and commission. "
                 "Times are UTC.")
    _write_table(wb.create_sheet("Daily ROI"), daily,
                 "Daily ROI -- continuous calendar",
                 "Every day in the window appears. Weekend rows are shaded: the "
                 "market is shut, so those flat rows are structural.")
    _write_table(wb.create_sheet("Weekly ROI"), weekly, "Weekly ROI")
    _write_table(wb.create_sheet("Monthly ROI"), monthly, "Monthly ROI")

    wb.save(DEST)
    print(f"wrote {DEST}")
    print(f"  sheets: {', '.join(wb.sheetnames)}")
    print(f"  {len(trades)} trades, {len(daily)} daily rows, "
          f"{len(weekly)} weekly rows, {len(monthly)} monthly rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
