"""
Rebuild the current adopted configuration's deliverable in the house format
(`report_format.py`). Run after any backtest whose ledger lands in reports/.

    python3 build_house_report.py
"""
import numpy as np
import pandas as pd

import report_format as rf

LEDGER = "reports/v6/v6_adopted_ledger.csv"
OUT = "Mylifeloading_SMC_Sniper_100k_backtest.xlsx"
START = 100_000.0
RISK_PCT = 0.01

def pip_size(sym: str) -> float:
    if sym == "XAUUSD":
        return 0.1
    if sym.endswith("JPY"):
        return 0.01
    return 0.0001


def main():
    src = pd.read_csv(LEDGER)
    src["entry_time"] = pd.to_datetime(src["entry_time"], utc=True)
    src = src.sort_values("entry_time").reset_index(drop=True)

    # Re-run the account curve at the reported risk so P&L and Balance are
    # this workbook's own numbers rather than the ledger's internal basis.
    bal = START
    rows = []
    for _, t in src.iterrows():
        risk_dollars = bal * RISK_PCT
        pnl = risk_dollars * float(t["r_multiple"])
        bal += pnl
        ps = pip_size(t["symbol"])
        stop_pips = abs(float(t["entry"]) - float(t["stop"])) / ps
        rows.append({
            "Date": t["entry_time"].to_pydatetime().replace(tzinfo=None).date(),
            "Entry Time (UTC)": t["entry_time"].to_pydatetime().replace(tzinfo=None),
            "Pair": t["symbol"],
            "Direction": "BUY" if str(t["side"]).lower() == "buy" else "SELL",
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
            "Week": t["entry_time"].strftime("%G-W%V"),
            "Month": t["entry_time"].strftime("%Y-%m"),
        })
    trades = pd.DataFrame(rows)

    wins = int(trades["Win"].sum())
    gross_w = trades.loc[trades["P&L ($)"] > 0, "P&L ($)"].sum()
    gross_l = abs(trades.loc[trades["P&L ($)"] < 0, "P&L ($)"].sum())
    curve = np.concatenate([[START], trades["Balance ($)"].to_numpy()])
    peak = np.maximum.accumulate(curve)
    max_dd = float(((peak - curve) / peak).max())

    headline = {
        "Signals": int(len(src)),
        "Trades Taken": int(len(trades)),
        "Skipped (Daily Cap)": 0,
        "Win Rate": wins / len(trades),
        "Profit Factor": gross_w / gross_l if gross_l else float("inf"),
        "Ending Balance": float(trades["Balance ($)"].iloc[-1]),
        "ROI": float(trades["Balance ($)"].iloc[-1]) / START - 1.0,
        "Max Drawdown": max_dd,
    }

    days = trades["Date"].nunique()
    per_day = trades.groupby("Date")["Pair"].nunique()
    concurrency = {
        "Trading days": int(days),
        "Days with 2+ instruments signaling": int((per_day >= 2).sum()),
        "Max instruments same day": int(per_day.max()),
        "Window (days)": int((trades["Date"].max() - trades["Date"].min()).days),
        "Trades per day": round(len(trades) / max(1, (trades["Date"].max() - trades["Date"].min()).days), 3),
        "Longest losing streak": int(
            max((len(list(g)) for k, g in __import__("itertools").groupby(trades["Win"]) if k == 0), default=0)
        ),
    }

    grp = trades.groupby("Pair")
    per_instrument = pd.DataFrame({
        "Pair": grp.size().index,
        "Trades": grp.size().values,
        "Win Rate": grp["Win"].mean().values,
        # A pair with no losing trade has no finite profit factor. Report it as
        # such rather than dividing by a fabricated 1.0, which silently prints
        # the gross win total in a column the reader will read as a ratio.
        "PF": [
            (round(g.loc[g["P&L ($)"] > 0, "P&L ($)"].sum() /
                   abs(g.loc[g["P&L ($)"] < 0, "P&L ($)"].sum()), 2)
             if (g["P&L ($)"] < 0).any() else "n/a (no losses)")
            for _, g in grp
        ],
        "Total P&L ($)": grp["P&L ($)"].sum().round(2).values,
        "Strategy Params": "1H setup, flat 4R, BE arm @+3R, score>=80, honest fills",
    }).sort_values("Total P&L ($)", ascending=False).reset_index(drop=True)

    methodology = (
        "WHAT THIS IS: the v6 adopted configuration (1H setup timeframe, flat 4R target, no trade "
        "management beyond a break-even stop armed at +3R, score gate 80, 29 instruments) over the full "
        f"~1,200-day TradeLocker broker window, ${START:,.0f} account, {RISK_PCT:.0%} risk per trade, "
        "compounding trade by trade. Bars are the broker's own BID series with modelled spread; fills are "
        "trade-through only, spread is paid at entry, and a bar that touches both target and stop is "
        "counted as a LOSS.\n\n"
        "HOW THE CONFIGURATION WAS CHOSEN: every parameter was selected on TRAIN only and scored on an "
        "untouched TEST half, then re-checked by walk-forward. Eight defects found in the v5 audit are "
        "fixed here, including two lookaheads (an order-block quality rank that read two bars into the "
        "future, and a risk engine that booked P/L at signal time) and a commission ~190x too small on "
        "every JPY cross. Fixing them LOWERED the out-of-sample half from +0.083R to +0.032R -- the "
        "lookahead had been flattering the part that matters most.\n\n"
        "READ THIS BEFORE TRUSTING THE ROI. The win rate is ~36%, and that is by design: at a flat 4R "
        "target the break-even win rate is 20%, so the edge lives in the size of the winners, not their "
        "frequency. The system is therefore streak-prone -- the recorded longest losing run is 11 trades, "
        "and a 13-trade run at 2% risk would put the account 24% down and need +31.8% to recover. 1% risk "
        "is the recommendation; 2% is outside the system's own configured cap.\n\n"
        "WHAT IS NOT ESTABLISHED: the full-window cluster-bootstrap confidence interval on expectancy is "
        "[+0.0092, +0.6948] -- it clears zero, but by 0.0092R on 142 correlated clusters. The walk-forward "
        "interval [-0.0431, +0.7079] still SPANS zero, and walk-forward is the harder test. Treat this as "
        "encouraging, not proven. Nothing in this repo has ever placed a live or demo order; forward "
        "results are PENDING A DEMO RUN.\n\n"
        "CONCURRENCY: these instruments share one account, so several fixed-%-risk positions can be open "
        "at once. Pooling many instruments' bets on one account is not full diversification -- treat the "
        "ROI as an upper bound."
    )

    rf.build_workbook(
        OUT,
        title="Mylifeloading SMC Sniper -- 29 Instruments (FX majors, crosses, Gold)",
        subtitle=(
            f"{trades['Date'].min()} to {trades['Date'].max()}  ·  ${START:,.0f} account  ·  "
            f"{RISK_PCT:.0%} risk/trade  ·  flat 4R target  ·  1H execution  ·  TradeLocker data"
        ),
        methodology=methodology,
        headline=headline,
        trades=trades,
        starting_balance=START,
        concurrency=concurrency,
        per_instrument=per_instrument,
    )
    print(f"wrote {OUT}: {len(trades)} trades, "
          f"WR {headline['Win Rate']:.2%}, PF {headline['Profit Factor']:.3f}, "
          f"ROI {headline['ROI']:.2%}, maxDD {max_dd:.2%}")


if __name__ == "__main__":
    main()
