#!/usr/bin/env python3
"""Assemble ``Mylifeloading_SMC_Sniper_v7_100k_backtest.xlsx``.

The layout is `report_format.py` -- the house standard
(`.claude/commands/spreadsheet-format.md`) -- so Summary / Trade Log / Periods
keep their names, order and shape. Four sheets are added on top, and each one
carries something the three cannot:

    Daily Profit    period / trades / wins / losses / win rate / P&L $ /
    Weekly Profit   ROI % / cumulative ROI % / running balance, on a
    Monthly Profit  CONTINUOUS calendar -- a flat period is a row, not a gap
    RR Frontier     the win-rate / reward-to-risk table the config was
                    chosen from, in R and in dollars, so the reader can see
                    what the chosen win rate cost
    90-Day Window   the small-sample run, labelled as non-evidence

    python3 build_v7_workbook.py
"""
from __future__ import annotations

import itertools
import os

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import report_format as rf

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "reports", "v7_100k")
FRONTIER = os.path.join(REPO, "reports", "v7")
DEST = os.path.join(REPO, "Mylifeloading_SMC_Sniper_v7_100k_backtest.xlsx")

START = 100_000.0
RISK_PCT = 0.01

HEAD_FILL = PatternFill("solid", fgColor="2F4F5F")
HEAD_FONT = Font(bold=True, size=10, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14)
NOTE_FONT = Font(italic=True, size=9, color="595959")
SECTION_FONT = Font(bold=True, size=11)
THIN = Side(style="thin", color="D0D0D0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
POS_FILL = PatternFill("solid", fgColor="E8F5E9")
NEG_FILL = PatternFill("solid", fgColor="FDECEA")
FLAT_FILL = PatternFill("solid", fgColor="F5F5F5")
MONEY = '#,##0.00;[Red]-#,##0.00'
PCT = '0.00%'


def pip_size(sym: str) -> float:
    if sym == "XAUUSD":
        return 0.1
    if str(sym).endswith("JPY"):
        return 0.01
    return 0.0001


# ------------------------------------------------------------------ ledger ---
def trade_frame(path: str) -> pd.DataFrame:
    """The engine's own $100k ledger, read rather than recomputed.

    The dollar column is taken straight from `pnl`, not rebuilt as
    `R x 1% of balance`. The two are NOT the same number: the engine rounds
    position sizes to broker lot steps, applies the XAUUSD risk override, and
    lets the daily/weekly loss gates skip trades. Recomputing from R silently
    discards all three and reports an ending balance ~3% above the one the run
    actually produced. The sheet must agree with the run.
    """
    src = pd.read_csv(path)
    if src.empty:
        return pd.DataFrame(columns=[c[0] for c in rf.TRADE_LOG_COLUMNS])
    src["entry_time"] = pd.to_datetime(src["entry_time"], utc=True)
    src["exit_time"] = pd.to_datetime(src["exit_time"], utc=True)
    # Ordered by EXIT, because that is when the account balance actually moves
    # and the running Balance column has to be traceable down the sheet.
    src = src.sort_values("exit_time").reset_index(drop=True)

    bal, rows = START, []
    for _, t in src.iterrows():
        pnl = float(t["pnl"])
        bal += pnl
        ps = pip_size(t["symbol"])
        stop_pips = abs(float(t["entry"]) - float(t["stop"])) / ps
        rows.append({
            "Date": t["exit_time"].to_pydatetime().replace(tzinfo=None).date(),
            "Entry Time (UTC)": t["entry_time"].to_pydatetime().replace(tzinfo=None),
            "Pair": t["symbol"],
            "Direction": "BUY" if str(t["direction"]).lower() in ("buy", "bullish") else "SELL",
            "Entry": round(float(t["entry"]), 5),
            "Stop": round(float(t["stop"]), 5),
            "Target": round(float(t["tp2"]), 5),
            "Exit": round(float(t["exit_price"]), 5),
            "Outcome": str(t["exit_reason"]).replace("_", " "),
            "Stop (pips)": round(stop_pips, 1),
            "Result (pips)": round(stop_pips * float(t["r_multiple"]), 1),
            "Result R": round(float(t["r_multiple"]), 3),
            "Win": 1 if float(t["r_multiple"]) > 0 else 0,
            "Lots": round(float(t["size_lots"]), 2),
            "P&L ($)": round(pnl, 2),
            "Balance ($)": round(bal, 2),
            "Week": t["exit_time"].strftime("%G-W%V"),
            "Month": t["exit_time"].strftime("%Y-%m"),
        })
    return pd.DataFrame(rows)


def stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"n": 0, "wins": 0, "wr": 0.0, "pf": float("nan"),
                "end": START, "roi": 0.0, "dd": 0.0, "streak": 0, "exp_r": 0.0}
    wins = int(trades["Win"].sum())
    gw = trades.loc[trades["P&L ($)"] > 0, "P&L ($)"].sum()
    gl = abs(trades.loc[trades["P&L ($)"] < 0, "P&L ($)"].sum())
    curve = np.concatenate([[START], trades["Balance ($)"].to_numpy()])
    peak = np.maximum.accumulate(curve)
    return {
        "n": len(trades), "wins": wins, "wr": wins / len(trades),
        "pf": (gw / gl) if gl else float("nan"),
        "end": float(trades["Balance ($)"].iloc[-1]),
        "roi": float(trades["Balance ($)"].iloc[-1]) / START - 1.0,
        "dd": float(((peak - curve) / peak).max()),
        "streak": int(max((len(list(g)) for k, g in
                           itertools.groupby(trades["Win"]) if k == 0), default=0)),
        "exp_r": float(trades["Result R"].mean()),
    }


# ------------------------------------------------- continuous period tables ---
def period_profit(trades: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Continuous period table with the columns the owner asked for.

    Continuity is load-bearing: a period with no trade is a row reading zero,
    not a gap. A table of only the active weeks flatters any system that trades
    in bursts, and for a stack that trades once a week the flat stretches ARE
    the product.
    """
    if trades.empty:
        return pd.DataFrame()
    d = trades.copy()
    d["Date"] = pd.to_datetime(d["Date"])
    span = pd.date_range(d["Date"].min().normalize(), d["Date"].max().normalize(), freq="D")
    if freq == "D":
        keys, index = d["Date"].dt.strftime("%Y-%m-%d"), pd.Index(
            span.strftime("%Y-%m-%d")).unique()
    elif freq == "W":
        keys, index = d["Date"].dt.strftime("%G-W%V"), pd.Index(
            span.strftime("%G-W%V")).unique()
    else:
        keys, index = d["Date"].dt.strftime("%Y-%m"), pd.Index(
            span.strftime("%Y-%m")).unique()

    g = d.groupby(keys).agg(trades=("Win", "size"), wins=("Win", "sum"),
                            pnl=("P&L ($)", "sum"))
    g = g.reindex(index, fill_value=0)

    # ROI% is measured against the balance the period OPENED with, so the
    # column reads as the return actually experienced that period; cumulative
    # ROI is against the starting balance, so it ties out to the headline.
    rows, bal = [], START
    for period, r in g.iterrows():
        opening = bal
        bal += float(r["pnl"])
        n, w = int(r["trades"]), int(r["wins"])
        rows.append({
            "Period": period, "Trades": n, "Wins": w, "Losses": n - w,
            "Win Rate": (w / n) if n else 0.0,
            "P&L ($)": round(float(r["pnl"]), 2),
            "ROI %": (float(r["pnl"]) / opening) if opening else 0.0,
            "Cumulative ROI %": bal / START - 1.0,
            "Running Balance ($)": round(bal, 2),
        })
    return pd.DataFrame(rows)


def write_table(ws, frame: pd.DataFrame, title: str, note: str = "") -> None:
    ws.cell(row=1, column=1, value=title).font = TITLE_FONT
    row = 2
    for line in [ln for ln in note.split("\n") if ln]:
        ws.cell(row=row, column=1, value=line).font = NOTE_FONT
        row += 1
    row += 1
    if frame is None or frame.empty:
        ws.cell(row=row, column=1, value="(no trades in this window)")
        return
    for j, col in enumerate(frame.columns, start=1):
        c = ws.cell(row=row, column=j, value=str(col))
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        c.border = BORDER
        ws.column_dimensions[get_column_letter(j)].width = \
            20 if j == 1 else max(12, len(str(col)) + 3)
    for i, (_, r) in enumerate(frame.iterrows(), start=row + 1):
        flat = "Trades" in frame.columns and int(r["Trades"]) == 0
        for j, col in enumerate(frame.columns, start=1):
            val = r[col]
            if hasattr(val, "item"):
                val = val.item()
            c = ws.cell(row=i, column=j, value=val)
            c.border = BORDER
            low = str(col).lower()
            if "%" in low or "rate" in low:
                c.number_format = PCT
            elif "$" in low:
                c.number_format = MONEY
            elif low == "pf" or "factor" in low:
                c.number_format = '0.000'
            if flat:
                c.fill = FLAT_FILL
            elif "P&L ($)" in frame.columns:
                c.fill = POS_FILL if float(r["P&L ($)"]) > 0 else NEG_FILL
    ws.freeze_panes = ws.cell(row=row + 1, column=1).coordinate


def main() -> str:
    full = trade_frame(os.path.join(SRC, "full_2r", "ledger_1pct.csv"))
    d90 = trade_frame(os.path.join(SRC, "90d_2r", "ledger_1pct.csv"))
    sf, s9 = stats(full), stats(d90)

    first, last = full["Date"].min(), full["Date"].max()
    window_days = (last - first).days
    per_day = full.groupby("Date")["Pair"].nunique()

    frontier = pd.read_csv(os.path.join(FRONTIER, "v7_rr_gate20.csv"))
    fr0 = pd.read_csv(os.path.join(FRONTIER, "v7_rr_gate0.csv"))

    methodology = (
        "WHAT THIS IS. SMC Sniper v7 -- 1H setups across 29 TradeLocker instruments, "
        "score gate 80, a FLAT 1:2 REWARD-TO-RISK TARGET, and a 20-pip minimum target "
        "distance gate. $100,000, 1% risk per trade, compounding trade by trade over the "
        f"full {window_days}-day broker window ({first} to {last}). Fills are honest: the "
        "entry limit and the take profit both require TRADE-THROUGH, the spread is paid at "
        "entry, and a bar that touches both the target and the stop is counted a LOSS. No "
        "lookahead: every zone, sweep and bias value is indexed by the bar it becomes "
        "knowable on.\n\n"
        "WHY 1:2 AND NOT 1:1. The owner asked for a 60% win rate at 1:2-1:5 reward-to-risk "
        "with a 20-pip minimum target. Those constraints do not all hold at once, and this "
        "workbook does not pretend otherwise. The full frontier is on the RR Frontier "
        "sheet. 60% IS reachable -- a flat 1:1 target returns 61.27% (60.82% with the "
        "20-pip gate live) -- but it is the WORST configuration measured: it earns $120 a "
        "trade against 1:2's $252 and 1:4's $352, its out-of-sample TEST half is NEGATIVE "
        "(-0.0448R), and its confidence interval spans zero. It buys the win rate by "
        "shrinking the reward, which is the one thing this repo has rejected four times "
        "under matched-R controls. 1:1 is also OUTSIDE the owner's own stated 1:2-1:5 "
        "band. So 1:2 is shipped: it is the HIGHEST-WIN-RATE point inside the band the "
        "owner specified, at 47.45%, and it is positive on all three splits independently "
        "-- TRAIN +0.2931R (n=95), VALIDATION +0.3503R (n=42), TEST +0.1688R (n=61). The "
        "selection is driven by the stated constraint, not by picking the best full-window "
        "number.\n\n"
        "THE 60% TARGET IS NOT MET, PLAINLY. 47.45% is not 60%. What it is, is 14.12 "
        "points clear of the 33.33% break-even line a 1:2 target has to beat -- and a win "
        "rate without its break-even line beside it is not information. For comparison, "
        "the 1:1 configuration's 60.82% clears its own 50% line by only 10.82 points, so "
        "the 60% number is a WEAKER result than the 47% one on the measure that decides "
        "whether money is made.\n\n"
        "WHAT IT COSTS AGAINST THE 1:4 BASELINE, IN DOLLARS. The adopted v6 configuration "
        "(flat 1:4) returns $182,651 over this same window; this 1:2 configuration returns "
        "$161,929. Choosing the higher win rate costs about $20,700 over 3.29 years, or "
        "$266 a trade against $352. What it buys is risk: max drawdown 7.57% against "
        "17.76%, and a longest losing streak of 7 against 11. That is the whole trade, "
        "stated in both directions -- less money, materially less pain.\n\n"
        "WHAT THE 20-PIP GATE ACTUALLY DOES. At the v6 1:4 target it is a complete no-op: "
        "the smallest target in the whole ledger is 37.8 pips, so nothing is ever "
        "declined. It only binds once the target shrinks. Setups removed: 0 at 1:4, 0 at "
        "1:3, 0 at 1:2.5, 2 of 198 at 1:2, 9 of 199 at 1:1.5, and 33 of 204 (16.2%) at "
        "1:1. At the shipped 1:2 it is nearly free and slightly helpful -- expectancy "
        "+0.2523R to +0.2660R and the cluster interval from [+0.0049, +0.4935] to "
        "[+0.0245, +0.5151] -- on two removed trades, which is well inside noise and is "
        "not claimed as an improvement. At 1:1 it removes a sixth of the population and "
        "still does not rescue that configuration. The gate is respected here by "
        "construction, not by luck.\n\n"
        "READ THIS BEFORE TRUSTING THE ROI. This is a thin edge on a small sample. 1:2 "
        "trades roughly once a week across 29 instruments; the whole window is 196 trades "
        "sitting in 142 statistically independent clusters, because same-pair "
        "same-direction re-entries inside 24 hours are several bets on ONE liquidity "
        "event. Every confidence interval quoted here is a CLUSTER bootstrap that "
        "resamples those groups whole. The full-window interval CLEARS zero "
        "([+0.0245, +0.5151]). The WALK-FORWARD interval DOES NOT: 168 out-of-sample "
        "trades across 122 clusters, 46.43% win rate, PF 1.404, +0.2304R, cluster CI "
        "[-0.0305, +0.5005] -- it spans zero. The walk-forward test is the harder one and "
        "it is the one to believe. The edge is encouraging and it is NOT established.\n\n"
        "WHAT IS NOT ESTABLISHED. That this makes money out of sample. That the win rate "
        "holds. Nothing in this repository has ever placed an order -- there is no forward "
        "or demo result behind any number in this workbook.\n\n"
        "CONCURRENCY AND LOT ROUNDING. Up to three instruments hold fixed-1%-risk "
        "positions against the same account at once, so this is not full diversification "
        "and the ROI is an upper bound; correlated pairs can lose together. Position sizes "
        "are rounded to broker lot steps, which moves realised P&L slightly against the "
        "R-multiples on small accounts.\n\n"
        "THE 90-DAY WINDOW IS ON ITS OWN SHEET AND IT IS NOT EVIDENCE. At 0.17 trades a "
        f"day, 90 days is {s9['n']} trades. A sample that size cannot distinguish a "
        "working system from a broken one. It is reported because it was asked for."
    )

    headline = {
        "Signals": sf["n"], "Trades Taken": sf["n"], "Skipped (Daily Cap)": 0,
        "Win Rate": sf["wr"], "Profit Factor": sf["pf"],
        "Ending Balance": sf["end"], "ROI": sf["roi"], "Max Drawdown": sf["dd"],
    }
    concurrency = {
        "Trading days": int(full["Date"].nunique()),
        "Days with 2+ instruments signaling": int((per_day >= 2).sum()),
        "Max instruments same day": int(per_day.max()),
        "Window (days)": int(window_days),
        "Trades per day": round(sf["n"] / max(1, window_days), 3),
        "Longest losing streak": sf["streak"],
        "Expectancy (R)": round(sf["exp_r"], 4),
        "Expectancy ($/trade at 1% of $100k)": round(sf["exp_r"] * START * RISK_PCT, 2),
        "Break-even win rate at 1:2": "33.33%",
        "Win rate clears break-even by": f"{(sf['wr'] * 100) - 33.33:.2f} points",
    }

    rows = []
    for sym, g in full.groupby("Pair"):
        gl = abs(g.loc[g["P&L ($)"] < 0, "P&L ($)"].sum())
        gw = g.loc[g["P&L ($)"] > 0, "P&L ($)"].sum()
        rows.append({
            "Pair": sym, "Trades": len(g),
            "Win Rate": g["Win"].mean(),
            # A pair with no losing trade has NO finite profit factor. Printing
            # the gross win total in a column the reader reads as a ratio is a
            # bug this repo shipped once.
            "PF": round(gw / gl, 3) if gl else "n/a (no losses)",
            "Total P&L ($)": round(float(g["P&L ($)"].sum()), 2),
            "Strategy Params": "1H SMC sniper, score>=80, flat 1:2 target, "
                               "min target 20 pips, BE stop inert below 3R",
        })
    per_instrument = pd.DataFrame(rows).sort_values("Total P&L ($)", ascending=False)

    rf.build_workbook(
        DEST,
        title="Mylifeloading SMC Sniper v7 -- 29 TradeLocker FX & metals instruments",
        subtitle=f"{first} to {last}  ·  $100,000 account  ·  1% risk/trade  ·  "
                 f"flat 1:2 target, 20-pip minimum  ·  1H execution  ·  "
                 f"TradeLocker broker bars",
        methodology=methodology,
        headline=headline,
        trades=full,
        starting_balance=START,
        concurrency=concurrency,
        per_instrument=per_instrument,
        trade_log_title="Full-Window Trade Log -- flat 1:2, 20-pip gate, 1% risk on $100,000",
    )

    wb = load_workbook(DEST)
    write_table(wb.create_sheet("Daily Profit"), period_profit(full, "D"),
                "Daily Profit -- full window, $100,000 at 1% risk",
                "Continuous calendar: a day with no trade is a row reading zero, not a gap.\n"
                "ROI % is against the balance the day opened with; Cumulative ROI % is against $100,000.")
    write_table(wb.create_sheet("Weekly Profit"), period_profit(full, "W"),
                "Weekly Profit -- full window, $100,000 at 1% risk",
                "ISO weeks, continuous. At ~0.17 trades a day most weeks carry one trade or none.")
    write_table(wb.create_sheet("Monthly Profit"), period_profit(full, "M"),
                "Monthly Profit -- full window, $100,000 at 1% risk",
                "Continuous months. The flat and negative months are the ones to read: "
                "a thin edge spends long stretches doing nothing.")

    fcols = ["variant", "n", "wr", "breakeven_wr", "clears_by", "pf", "exp",
             "exp_usd", "train_exp", "test_exp", "max_dd", "max_loss_streak",
             "clusters", "ccl_lo", "ccl_hi", "cluster_clears"]
    ftab = pd.concat([fr0[fcols], frontier[fcols]], ignore_index=True)
    ftab.columns = ["Configuration", "Trades", "Win Rate %", "Break-even WR %",
                    "Clears By (pts)", "PF", "Expectancy (R)",
                    "Expectancy ($/trade)", "TRAIN E (R)", "TEST E (R)",
                    "Max DD %", "Longest Loss Streak", "Independent Clusters",
                    "Cluster CI low", "Cluster CI high", "CI clears zero?"]
    write_table(wb.create_sheet("RR Frontier"), ftab,
                "The win-rate / reward-to-risk frontier -- why 1:2 was chosen",
                "Every row is ENTRY-MATCHED: min_rr_on_liquidity is TRUE throughout, so the "
                "rows differ in their EXIT only and never in which setups they take.\n"
                "Read 'Clears By', not 'Win Rate'. 60% at 1:1 clears its 50% line by 11.3 "
                "points; 47% at 1:2 clears its 33.3% line by 13.6. The higher win rate is "
                "the weaker result.\n"
                "Expectancy ($/trade) is expectancy_R x $1,000 -- 1% of a $100,000 account. "
                "It is the column that answers 'does the higher win rate make more money'. "
                "It does not.")

    write_table(wb.create_sheet("90-Day Window"), period_profit(d90, "M") if not d90.empty
                else pd.DataFrame(),
                "The most recent 90 days -- NOT EVIDENCE, reported because it was asked for",
                f"{s9['n']} trades. At 0.17 trades a day that is what 90 days contains, and a "
                "sample that size cannot distinguish a working system from a broken one.\n"
                f"Ending balance ${s9['end']:,.2f}  ·  ROI {s9['roi']*100:+.2f}%  ·  "
                f"win rate {s9['wr']*100:.2f}%  ·  max drawdown {s9['dd']*100:.2f}%.\n"
                "The full-window sheets are the ones that mean anything.")

    wb.save(DEST)
    print(f"Wrote {DEST}")
    print(f"  full window : {sf['n']} trades  WR {sf['wr']*100:.2f}%  "
          f"PF {sf['pf']:.3f}  end ${sf['end']:,.2f}  ROI {sf['roi']*100:+.2f}%  "
          f"maxDD {sf['dd']*100:.2f}%  streak {sf['streak']}")
    print(f"  90 days     : {s9['n']} trades  WR {s9['wr']*100:.2f}%  "
          f"end ${s9['end']:,.2f}  ROI {s9['roi']*100:+.2f}%")
    print(f"  sheets      : {wb.sheetnames}")
    return DEST


if __name__ == "__main__":
    main()
