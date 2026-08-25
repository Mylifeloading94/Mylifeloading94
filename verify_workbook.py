"""Cross-check every total in the workbook against the source trade data.

Stands in for the LibreOffice recalculation, which is unavailable here: rather
than proving the formulas evaluate, this proves the written numbers agree with
the trades they claim to summarise.
"""
import numpy as np, pandas as pd
from openpyxl import load_workbook

START = 10_000.0
CT = "America/Chicago"


def load(path):
    d = pd.read_csv(path)
    for c in ("entry_time", "exit_time"):
        d[c] = pd.to_datetime(d[c], utc=True)
    d["exit_ct"] = d["exit_time"].dt.tz_convert(CT)
    return d


tr1, tr2 = load("sniper87_trades_1pct.csv"), load("sniper87_trades_2pct.csv")
wb = load_workbook("XAUUSD_Sniper87_Backtest.xlsx")
fails = []


def chk(label, got, want, tol=0.02):
    ok = (got is not None) and abs(float(got) - float(want)) <= tol
    print(f"  {'OK ' if ok else 'FAIL'}  {label:44s} sheet={got}  source={want:.4f}")
    if not ok:
        fails.append(label)


print("=== Summary ===")
ws = wb["Summary"]
for row, tr, lbl in ((5, tr1, "1%"), (6, tr2, "2%")):
    gain = tr.loc[tr.pnl > 0, "pnl"].sum(); loss = tr.loc[tr.pnl <= 0, "pnl"].sum()
    chk(f"{lbl} trades", ws.cell(row, 3).value, len(tr), 0)
    chk(f"{lbl} gain", ws.cell(row, 4).value, gain)
    chk(f"{lbl} loss", ws.cell(row, 5).value, loss)
    chk(f"{lbl} net", ws.cell(row, 6).value, gain + loss)
    chk(f"{lbl} ROI", ws.cell(row, 7).value, (gain + loss) / START, 1e-6)
    chk(f"{lbl} end balance", ws.cell(row, 8).value, START + gain + loss)

print("\n=== Trade logs ===")
for sheet, tr, lbl in (("Trades 1pct", tr1, "1%"), ("Trades 2pct", tr2, "2%")):
    ws = wb[sheet]
    n = len(tr)
    tot = ws.cell(4 + n, 12).value
    chk(f"{lbl} log P/L total", tot, tr.pnl.sum())
    chk(f"{lbl} log pips total", ws.cell(4 + n, 11).value, tr.pips.sum(), 0.2)
    # spot-check the last row's balance against the running balance
    chk(f"{lbl} final balance row", ws.cell(3 + n, 16).value, tr.balance.iloc[-1])

print("\n=== Period tables (1% run) ===")
d = tr1.copy(); d["day"] = d.exit_ct.dt.tz_localize(None).dt.normalize()
for sheet, grouper in (
        ("Daily", d.groupby("day")),
        ("Weekly", d.groupby(d.day - pd.to_timedelta(d.day.dt.weekday, unit="D"))),
        ("Monthly", d.groupby(d.day.dt.to_period("M")))):
    ws = wb[sheet]
    nrows = len(grouper)
    chk(f"{sheet} total P/L", ws.cell(4 + nrows, 5).value, tr1.pnl.sum())
    chk(f"{sheet} total trades", ws.cell(4 + nrows, 2).value, len(tr1), 0)
    chk(f"{sheet} total ROI", ws.cell(4 + nrows, 6).value, tr1.pnl.sum() / START, 1e-6)

print("\n=== Cross-table consistency ===")
for sheet in ("Daily", "Weekly", "Monthly"):
    ws = wb[sheet]
    n = sum(1 for r in range(4, ws.max_row + 1) if ws.cell(r, 1).value not in (None, "TOTAL"))
    s = sum(ws.cell(r, 5).value or 0 for r in range(4, 4 + n))
    chk(f"{sheet} rows sum to net", s, tr1.pnl.sum())

print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}"))
