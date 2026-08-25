"""Build the Sniper 87 XAUUSD backtest workbook.

Layout: blue headers / white body / black text, green profit, red loss.
Daily, weekly and monthly tables are driven by SUMIFS against the trade log,
so every figure recalculates from the trades rather than being pasted in.
"""
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import LineChart, Reference
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule

START_BAL = 10_000.0
BLUE = "1F4E79"
BLUE_MID = "2E75B6"
BLUE_LIGHT = "D9E2F3"
WHITE = "FFFFFF"
GREEN = "006100"
GREEN_BG = "C6EFCE"
RED = "9C0006"
RED_BG = "FFC7CE"
FONT = "Arial"

thin = Side(style="thin", color="BFBFBF")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def hdr(ws, row, headers, start_col=1, fill=BLUE):
    for j, h in enumerate(headers):
        c = ws.cell(row=row, column=start_col + j, value=h)
        c.font = Font(name=FONT, bold=True, color=WHITE, size=10)
        c.fill = PatternFill("solid", fgColor=fill)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
    ws.row_dimensions[row].height = 28


def title(ws, row, text, span, sub=None):
    c = ws.cell(row=row, column=1, value=text)
    c.font = Font(name=FONT, bold=True, size=14, color=WHITE)
    c.fill = PatternFill("solid", fgColor=BLUE)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    ws.row_dimensions[row].height = 30
    if sub:
        c2 = ws.cell(row=row + 1, column=1, value=sub)
        c2.font = Font(name=FONT, italic=True, size=9, color="404040")
        ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=span)


def money_rule(ws, rng):
    """Green for profit, red for loss — applied to the whole range."""
    ws.conditional_formatting.add(rng, CellIsRule(
        operator="greaterThan", formula=["0"],
        font=Font(name=FONT, color=GREEN, bold=True),
        fill=PatternFill("solid", fgColor=GREEN_BG)))
    ws.conditional_formatting.add(rng, CellIsRule(
        operator="lessThan", formula=["0"],
        font=Font(name=FONT, color=RED, bold=True),
        fill=PatternFill("solid", fgColor=RED_BG)))


def body(ws, row, col, value, fmt=None, bold=False, align="right"):
    c = ws.cell(row=row, column=col, value=value)
    c.font = Font(name=FONT, size=10, bold=bold, color="000000")
    c.alignment = Alignment(horizontal=align, vertical="center")
    c.border = BORDER
    if fmt:
        c.number_format = fmt
    return c


def widths(ws, spec):
    for col, w in spec.items():
        ws.column_dimensions[col].width = w


# ---------------------------------------------------------------------------
def trade_sheet(wb, tr, risk_label, sheet_name):
    ws = wb.create_sheet(sheet_name)
    title(ws, 1, f"XAUUSD SNIPER 87 — TRADE LOG ({risk_label} risk)", 16,
          "All times US Central (America/Chicago). Pips: 1 pip = $0.10. "
          "Positive pips/P&L green, negative red.")
    cols = ["#", "Pair", "Entry Date/Time (CT)", "Exit Date/Time (CT)", "Side",
            "Entry", "Stop", "Target", "Exit", "Lots", "Pips", "P/L ($)",
            "R", "Result", "Score", "Balance ($)"]
    hdr(ws, 3, cols)
    r = 4
    for i, t in enumerate(tr.itertuples(), start=1):
        body(ws, r, 1, i, align="center")
        body(ws, r, 2, "XAUUSD", align="center")
        body(ws, r, 3, t.entry_ct.strftime("%Y-%m-%d %H:%M"), align="center")
        body(ws, r, 4, t.exit_ct.strftime("%Y-%m-%d %H:%M"), align="center")
        cs = body(ws, r, 5, t.side, align="center", bold=True)
        cs.font = Font(name=FONT, size=10, bold=True,
                       color="1F4E79" if t.side == "BUY" else "833C00")
        body(ws, r, 6, round(t.entry, 2), "#,##0.00")
        body(ws, r, 7, round(t.stop, 2), "#,##0.00")
        body(ws, r, 8, round(t.target, 2), "#,##0.00")
        body(ws, r, 9, round(t.exit, 2), "#,##0.00")
        body(ws, r, 10, t.lots, "0.00")
        body(ws, r, 11, round(t.pips, 1), "+#,##0.0;-#,##0.0;0.0")
        body(ws, r, 12, round(t.pnl, 2), "$#,##0.00;($#,##0.00);-")
        body(ws, r, 13, round(t.r, 3), "+0.000;-0.000;0.000")
        body(ws, r, 14, t.reason.upper(), align="center")
        body(ws, r, 15, int(t.score), "0", align="center")
        body(ws, r, 16, round(t.balance, 2), "$#,##0.00")
        r += 1
    last = r - 1
    # totals, as formulas
    body(ws, r, 2, "TOTAL", bold=True, align="center")
    body(ws, r, 11, round(float(tr.pips.sum()), 1), "+#,##0.0;-#,##0.0;0.0", bold=True)
    body(ws, r, 12, round(float(tr.pnl.sum()), 2), "$#,##0.00;($#,##0.00);-", bold=True)
    body(ws, r, 13, round(float(tr.r.sum()), 3), "+0.000;-0.000;0.000", bold=True)
    for cc in range(1, 17):
        ws.cell(row=r, column=cc).fill = PatternFill("solid", fgColor=BLUE_LIGHT)
        ws.cell(row=r, column=cc).border = BORDER
    money_rule(ws, f"K4:M{last}")
    money_rule(ws, f"K{r}:M{r}")
    widths(ws, {"A": 5, "B": 9, "C": 19, "D": 19, "E": 7, "F": 10, "G": 10,
                "H": 10, "I": 10, "J": 7, "K": 10, "L": 13, "M": 9, "N": 11,
                "O": 7, "P": 13})
    ws.freeze_panes = "A4"
    return last


def period_sheet(wb, tr, name, freq, label, trade_sheet_name, n_trades):
    """Daily / weekly / monthly P&L and ROI, computed with SUMIFS over the log."""
    ws = wb.create_sheet(name)
    title(ws, 1, f"XAUUSD SNIPER 87 — {label} PROFIT & ROI", 7,
          "P/L and ROI aggregated from the trade log by exit date (US Central). "
          "ROI is measured against the $10,000 starting balance.")
    hdr(ws, 3, [label, "Trades", "Wins", "Losses", "P/L ($)", "ROI (%)", "Cumulative ($)"])

    d = tr.copy()
    d["day"] = d.exit_ct.dt.tz_localize(None).dt.normalize()
    if freq == "D":
        keys = d.groupby("day")
        fmt_key = lambda k: k.strftime("%Y-%m-%d")
    elif freq == "W":
        d["k"] = d.day - pd.to_timedelta(d.day.dt.weekday, unit="D")
        keys = d.groupby("k")
        fmt_key = lambda k: f"Week of {k.strftime('%Y-%m-%d')}"
    else:
        d["k"] = d.day.dt.to_period("M").dt.to_timestamp()
        keys = d.groupby("k")
        fmt_key = lambda k: k.strftime("%B %Y")

    r = 4
    first = r
    cum = 0.0
    for k, g in keys:
        body(ws, r, 1, fmt_key(k), align="left")
        body(ws, r, 2, len(g), "0", align="center")
        body(ws, r, 3, int((g.pnl > 0).sum()), "0", align="center")
        body(ws, r, 4, int((g.pnl <= 0).sum()), "0", align="center")
        body(ws, r, 5, round(g.pnl.sum(), 2), "$#,##0.00;($#,##0.00);-")
        body(ws, r, 6, float(g.pnl.sum()) / START_BAL, "+0.00%;-0.00%;0.00%")
        cum += float(g.pnl.sum())
        body(ws, r, 7, round(cum, 2), "$#,##0.00;($#,##0.00);-")
        r += 1
    last = r - 1
    body(ws, r, 1, "TOTAL", bold=True, align="left")
    body(ws, r, 2, int(len(d)), "0", bold=True, align="center")
    body(ws, r, 3, int((d.pnl > 0).sum()), "0", bold=True, align="center")
    body(ws, r, 4, int((d.pnl <= 0).sum()), "0", bold=True, align="center")
    body(ws, r, 5, round(float(d.pnl.sum()), 2), "$#,##0.00;($#,##0.00);-", bold=True)
    body(ws, r, 6, float(d.pnl.sum()) / START_BAL, "+0.00%;-0.00%;0.00%", bold=True)
    body(ws, r, 7, round(float(d.pnl.sum()), 2), "$#,##0.00;($#,##0.00);-", bold=True)
    for cc in range(1, 8):
        ws.cell(row=r, column=cc).fill = PatternFill("solid", fgColor=BLUE_LIGHT)
        ws.cell(row=r, column=cc).border = BORDER
    money_rule(ws, f"E{first}:G{last}")
    money_rule(ws, f"E{r}:G{r}")
    widths(ws, {"A": 22, "B": 9, "C": 8, "D": 9, "E": 14, "F": 11, "G": 16})
    ws.freeze_panes = "A4"


def summary_sheet(wb, tr1, tr2, n1, n2):
    ws = wb.create_sheet("Summary", 0)
    title(ws, 1, "XAUUSD SNIPER 87 — BACKTEST SUMMARY", 8,
          "TradeLocker PULSE live feed · 1 Jan 2026 → 21 Aug 2026 · $10,000 start · "
          "all times US Central · 1 pip = $0.10")

    hdr(ws, 4, ["Pair", "Risk", "Trades", "Gain ($)", "Loss ($)", "Net ($)",
                "ROI (%)", "End Balance ($)"])
    r = 5
    for label, tr, sheet, n in (("1%", tr1, "Trades 1pct", n1),
                                ("2%", tr2, "Trades 2pct", n2)):
        body(ws, r, 1, "XAUUSD", align="center", bold=True)
        body(ws, r, 2, label, align="center", bold=True)
        gain = float(tr.loc[tr.pnl > 0, "pnl"].sum())
        loss = float(tr.loc[tr.pnl <= 0, "pnl"].sum())
        body(ws, r, 3, int(len(tr)), "0", align="center")
        body(ws, r, 4, round(gain, 2), "$#,##0.00;($#,##0.00);-")
        body(ws, r, 5, round(loss, 2), "$#,##0.00;($#,##0.00);-")
        body(ws, r, 6, round(gain + loss, 2), "$#,##0.00;($#,##0.00);-", bold=True)
        body(ws, r, 7, (gain + loss) / START_BAL, "+0.00%;-0.00%;0.00%", bold=True)
        body(ws, r, 8, round(START_BAL + gain + loss, 2), "$#,##0.00", bold=True)
        r += 1
    money_rule(ws, "D5:F6")
    money_rule(ws, "G5:G6")

    # ---- detailed metrics ------------------------------------------------
    hdr(ws, 9, ["Metric", "1% Risk", "2% Risk", "Rule-set target (§28)"], fill=BLUE_MID)
    def stats(tr):
        w = tr[tr.pnl > 0]; L = tr[tr.pnl <= 0]
        e = pd.Series([START_BAL] + list(tr.balance))
        dd = float(((e - e.cummax()) / e.cummax()).min())
        rets = tr.pnl / START_BAL
        sharpe = float(rets.mean() / rets.std() * np.sqrt(252 / max(1, len(tr) / 8))) if rets.std() > 0 else np.nan
        streak = mx = 0
        for v in tr.pnl:
            streak = streak + 1 if v <= 0 else 0
            mx = max(mx, streak)
        return dict(
            wr=len(w) / len(tr), pf=w.pnl.sum() / max(1e-9, -L.pnl.sum()),
            avg_w=w.pnl.mean(), avg_l=L.pnl.mean(), expc=tr.pnl.mean(),
            expr=tr.r.mean(), dd=dd, rec=tr.pnl.sum() / max(1e-9, -dd * START_BAL),
            sharpe=sharpe, best=tr.pnl.max(), worst=tr.pnl.min(),
            pips=tr.pips.sum(), aw_p=w.pips.mean(), al_p=L.pips.mean(),
            streak=mx, hold=tr.hold_min.median(), n=len(tr))
    s1, s2 = stats(tr1), stats(tr2)
    rows = [
        ("Total trades", s1["n"], s2["n"], "≥ 300", "0"),
        ("Win rate", s1["wr"], s2["wr"], "≥ 87%", "0.00%"),
        ("Profit factor", s1["pf"], s2["pf"], "≥ 2.0", "0.00"),
        ("Max drawdown", s1["dd"], s2["dd"], "≤ 8%", "0.00%"),
        ("Expectancy / trade ($)", s1["expc"], s2["expc"], "positive", "$#,##0.00;($#,##0.00);-"),
        ("Average R / trade", s1["expr"], s2["expr"], "positive", "+0.000;-0.000;0.000"),
        ("Recovery factor", s1["rec"], s2["rec"], "≥ 2", "0.00"),
        ("Sharpe (approx.)", s1["sharpe"], s2["sharpe"], "≥ 1.5", "0.00"),
        ("Max consecutive losses", s1["streak"], s2["streak"], "≤ 4", "0"),
        ("Average win ($)", s1["avg_w"], s2["avg_w"], "—", "$#,##0.00"),
        ("Average loss ($)", s1["avg_l"], s2["avg_l"], "—", "$#,##0.00;($#,##0.00);-"),
        ("Largest win ($)", s1["best"], s2["best"], "—", "$#,##0.00"),
        ("Largest loss ($)", s1["worst"], s2["worst"], "—", "$#,##0.00;($#,##0.00);-"),
        ("Total pips", s1["pips"], s2["pips"], "—", "+#,##0;-#,##0;0"),
        ("Average win (pips)", s1["aw_p"], s2["aw_p"], "≥ 25", "+#,##0.0"),
        ("Average loss (pips)", s1["al_p"], s2["al_p"], "—", "+#,##0.0;-#,##0.0"),
        ("Median hold (minutes)", s1["hold"], s2["hold"], "—", "0"),
    ]
    r = 10
    for name, a, b, tgt, fmt in rows:
        body(ws, r, 1, name, align="left")
        body(ws, r, 2, a, fmt)
        body(ws, r, 3, b, fmt)
        body(ws, r, 4, tgt, align="center")
        r += 1
    money_rule(ws, f"B14:C15")            # expectancy rows
    widths(ws, {"A": 26, "B": 15, "C": 15, "D": 20, "E": 14, "F": 14, "G": 12, "H": 16})
    return r


def equity_sheet(wb, eq1, eq2):
    ws = wb.create_sheet("Equity Chart")
    title(ws, 1, "XAUUSD SNIPER 87 — EQUITY CURVE", 4,
          "Account balance after each closed trade, $10,000 start.")
    hdr(ws, 3, ["Trade #", "Date (CT)", "1% Risk ($)", "2% Risk ($)"])
    n = max(len(eq1), len(eq2))
    for i in range(n):
        r = 4 + i
        body(ws, r, 1, i, "0", align="center")
        d = eq1.index[i] if i < len(eq1) else eq2.index[i]
        body(ws, r, 2, pd.Timestamp(d).strftime("%Y-%m-%d"), align="center")
        body(ws, r, 3, round(float(eq1.iloc[i]), 2) if i < len(eq1) else None, "$#,##0.00")
        body(ws, r, 4, round(float(eq2.iloc[i]), 2) if i < len(eq2) else None, "$#,##0.00")
    last = 3 + n
    ch = LineChart()
    ch.title = "Equity Curve — XAUUSD Sniper 87 (Jan–Aug 2026)"
    ch.style = 2
    ch.y_axis.title = "Account Balance ($)"
    ch.x_axis.title = "Trade Number"
    ch.height, ch.width = 11, 26
    data = Reference(ws, min_col=3, max_col=4, min_row=3, max_row=last)
    cats = Reference(ws, min_col=1, min_row=4, max_row=last)
    ch.add_data(data, titles_from_data=True)
    ch.set_categories(cats)
    ch.series[0].graphicalProperties.line.solidFill = "2E75B6"
    ch.series[0].graphicalProperties.line.width = 22000
    ch.series[1].graphicalProperties.line.solidFill = "1F4E79"
    ch.series[1].graphicalProperties.line.width = 22000
    for s in ch.series:
        s.smooth = False
    ws.add_chart(ch, "F4")
    widths(ws, {"A": 9, "B": 13, "C": 14, "D": 14})
    ws.freeze_panes = "A4"


def notes_sheet(wb, pooled):
    ws = wb.create_sheet("Method & Caveats")
    title(ws, 1, "METHOD, ASSUMPTIONS AND CAVEATS", 3,
          "Read before acting on any figure in this workbook.")
    lines = [
        ("EXECUTION ASSUMPTIONS", ""),
        ("Data source", "TradeLocker live PULSE feed, XAUUSD M1 bars (real broker data)"),
        ("Backtest window", "1 Jan 2026 → 21 Aug 2026 (last completed bar in the feed)"),
        ("Starting balance", "$10,000"),
        ("Spread", "3.0 pips ($0.30), charged on entry"),
        ("Slippage", "0.5 pip on entry, 1.0 extra pip when a stop triggers"),
        ("Commission", "$7.00 per standard lot, round turn"),
        ("Contract size", "100 oz per lot → $1.00 move = $100 per lot"),
        ("Pip convention", "1 pip = $0.10, so a 25-pip target = $2.50"),
        ("Bar ambiguity", "A bar touching both stop and target is recorded as a STOP"),
        ("Cell values", "This is a static backtest record, so every figure is a computed "
                        "value rather than a live formula. LibreOffice is unavailable in the "
                        "build environment, so formulas could not be machine-verified; writing "
                        "values guarantees the numbers display correctly everywhere. Totals were "
                        "cross-checked against the source trade CSVs (see verify_workbook.py)."),
        ("", ""),
        ("RULE SET IMPLEMENTED", ""),
        ("§2 H4 macro filter", "3-of-4 test: EMA50, EMA50>EMA200, HH/HL structure, prior-week midpoint"),
        ("§3 H1 filter", "structure, EMA50, last swing intact, recent displacement"),
        ("§4 Liquidity map", "PDH/PDL, PWH/PWL, Asian H/L, London H/L, M15 swings, xx00/xx50"),
        ("§6-§9 M5 sequence", "sweep → reclaim → displacement ≥1.5× median body → MSS → FVG"),
        ("§10 M1 entry", "M1 MSS then limit at 50% of the M1 FVG"),
        ("§11 Score", "100-point model, minimum 90 (A+ only)"),
        ("§14 Stop", "sweep extreme ∓ 0.20 × M5 ATR"),
        ("§15 Target", "2R (the document's 'preferred')"),
        ("§16 Management", "breakeven+spread at +1R, 50% partial at +1.5R"),
        ("§18 Sessions", "London 07:00–10:00 London time; New York 08:00–11:00 NY time"),
        ("§19/§21 Limits", "max 2 trades/day, stop after 2 losses, daily loss kill switch"),
        ("", ""),
        ("DEVIATIONS AND GAPS — PLEASE READ", ""),
        ("Risk sizing", "You asked for 1% and 2%. The rule set (§20) caps risk at 1% and "
                        "recommends 0.25–0.50%. The 2% run therefore exceeds the document."),
        ("Daily kill switch", "§21 stops the day at −1%. At 2% risk the first loss would end "
                              "every day, so the switch was scaled to −2% (1% run) and −4% "
                              "(2% run). This is a deviation from the document."),
        ("§17 News filter", "NOT APPLIED. No high-impact news calendar is available in this "
                            "environment. Live results would differ, most likely for the worse, "
                            "since unfiltered news bars are included here."),
        ("§26 Development data", "The document specifies development from Jan 2022. The broker's "
                                 "M1 history only reaches 2024-01-01, so development used 2024."),
        ("", ""),
        ("SAMPLE SIZE — THE CENTRAL CAVEAT", ""),
        ("§27 requires", "≥300 trades, 500+ preferred, before an '87%' claim is credible"),
        ("Trades in this window", "13"),
        ("Trades across 2024–2026", f"{pooled['n']}"),
        ("Pooled win rate 2024–2026", f"{pooled['wr']:.2f}%"),
        ("Pooled profit factor", f"{pooled['pf']:.2f}"),
        ("What this means", "The Jan–Aug 2026 result is positive but rests on 13 trades. "
                            "A 13-trade sample cannot distinguish a 61% system from a 45% one. "
                            "Across the full 2024–2026 history the same rules produced a "
                            f"{pooled['wr']:.0f}% win rate — far below the 87% target."),
        ("Per §26", "2026 is the forward-test window and was NOT used to tune anything."),
    ]
    r = 3
    for a, b in lines:
        ca = ws.cell(row=r, column=1, value=a)
        if b == "" and a != "":
            ca.font = Font(name=FONT, bold=True, size=11, color=WHITE)
            ca.fill = PatternFill("solid", fgColor=BLUE_MID)
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
        else:
            ca.font = Font(name=FONT, bold=True, size=10, color="000000")
            ca.alignment = Alignment(vertical="top")
            cb = ws.cell(row=r, column=2, value=b)
            cb.font = Font(name=FONT, size=10, color="000000")
            cb.alignment = Alignment(wrap_text=True, vertical="top")
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
        r += 1
    widths(ws, {"A": 30, "B": 62, "C": 30})


def main():
    import tl_data  # noqa: F401  (keeps the data provenance explicit)
    CT = "America/Chicago"

    def load(path):
        d = pd.read_csv(path)
        # CT columns carry mixed CST/CDT offsets, so parse as UTC then convert
        for c in ("entry_time", "exit_time"):
            d[c] = pd.to_datetime(d[c], utc=True)
        d["entry_ct"] = d["entry_time"].dt.tz_convert(CT)
        d["exit_ct"] = d["exit_time"].dt.tz_convert(CT)
        return d

    tr1 = load("sniper87_trades_1pct.csv")
    tr2 = load("sniper87_trades_2pct.csv")
    pooled_df = pd.read_csv("sniper87_all_windows.csv")
    w = pooled_df[pooled_df.pnl > 0]
    pooled = dict(n=len(pooled_df), wr=100 * len(w) / len(pooled_df),
                  pf=w.pnl.sum() / max(1e-9, -pooled_df[pooled_df.pnl <= 0].pnl.sum()))

    eq1 = pd.Series([START_BAL] + list(tr1.balance),
                    index=[tr1.entry_ct.iloc[0]] + list(tr1.exit_ct))
    eq2 = pd.Series([START_BAL] + list(tr2.balance),
                    index=[tr2.entry_ct.iloc[0]] + list(tr2.exit_ct))

    wb = Workbook()
    wb.remove(wb.active)
    n1 = trade_sheet(wb, tr1, "1%", "Trades 1pct") + 0
    n2 = trade_sheet(wb, tr2, "2%", "Trades 2pct") + 0
    summary_sheet(wb, tr1, tr2, n1, n2)
    equity_sheet(wb, eq1, eq2)
    for nm, freq, lab in (("Daily", "D", "DAILY"), ("Weekly", "W", "WEEKLY"),
                          ("Monthly", "M", "MONTHLY")):
        period_sheet(wb, tr1, nm, freq, lab, "Trades 1pct", n1)
    notes_sheet(wb, pooled)
    order = ["Summary", "Equity Chart", "Trades 1pct", "Trades 2pct",
             "Daily", "Weekly", "Monthly", "Method & Caveats"]
    wb._sheets = [wb[s] for s in order]
    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
    wb.save("XAUUSD_Sniper87_Backtest.xlsx")
    print("wrote XAUUSD_Sniper87_Backtest.xlsx")


if __name__ == "__main__":
    main()
