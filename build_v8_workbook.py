#!/usr/bin/env python3
"""Assemble ``Mylifeloading_SMC_Sniper_v8_100k_backtest.xlsx``.

v8 changed NOTHING about the configuration -- that is the deliverable. The
round searched for a loss cluster on the adopted 1:2 population and for a
defensible per-pair win-rate cull, and neither survived its own out-of-sample
test. So the numbers here are the v7 run's numbers, and the new sheets are the
evidence for why they are unchanged.

Layout is `report_format.py` -- the house standard
(`.claude/commands/spreadsheet-format.md`) -- so Summary / Trade Log / Periods
keep their names, order and shape. Everything else is additive:

    Daily / Weekly / Monthly Profit   continuous calendars (established in v7)
    Loss Audit                        every cut, TRAIN and TEST side by side
    Break-Even Sweep                  the win-rate-for-money trade, priced
    Pair Cull                         per-pair TRAIN WR + the TEST verdict
    RR Frontier                       why 1:2, carried forward from v7
    90-Day Window                     small-sample run, labelled non-evidence

    python3 build_v8_workbook.py
"""
from __future__ import annotations

import os

import pandas as pd
from openpyxl import load_workbook

import report_format as rf
from build_v7_workbook import (SRC, START, RISK_PCT, period_profit, stats,
                               trade_frame, write_table)

REPO = os.path.dirname(os.path.abspath(__file__))
V7DIR = os.path.join(REPO, "reports", "v7")
V8DIR = os.path.join(REPO, "reports", "v8")
DEST = os.path.join(REPO, "Mylifeloading_SMC_Sniper_v8_100k_backtest.xlsx")


def main() -> str:
    full = trade_frame(os.path.join(SRC, "full_2r", "ledger_1pct.csv"))
    d90 = trade_frame(os.path.join(SRC, "90d_2r", "ledger_1pct.csv"))
    sf, s9 = stats(full), stats(d90)

    first, last = full["Date"].min(), full["Date"].max()
    window_days = (last - first).days
    per_day = full.groupby("Date")["Pair"].nunique()

    methodology = (
        "WHAT THIS IS. SMC Sniper v8 -- 1H setups across 29 TradeLocker instruments, "
        "score gate 80, a FLAT 1:2 REWARD-TO-RISK TARGET, a 20-pip minimum target "
        "distance gate, break-even stop armed at +3R. $100,000, 1% risk per trade, "
        f"compounding trade by trade over the full {window_days}-day broker window "
        f"({first} to {last}). Fills are honest: the entry limit and the take profit both "
        "require TRADE-THROUGH, the spread is paid at entry, and a bar that touches both "
        "the target and the stop is counted a LOSS. No lookahead: every zone, sweep and "
        "bias value is indexed by the bar it becomes knowable on.\n\n"
        "THE CONFIGURATION IS UNCHANGED FROM v7, AND THAT IS THIS ROUND'S RESULT. The ask "
        "was: find the losing trades, fix what they show, raise the win rate, reach 3 "
        "trades a day, and remove every pair under 60%. Three searches were run against "
        "that ask. All three came back negative, and shipping the unchanged config with "
        "the evidence is the honest outcome. Nothing was adopted that did not improve the "
        "TRAIN half and the untouched TEST half together.\n\n"
        "1. THE LOSS AUDIT -- NO CLUSTER. 196 trades, 93 winners, 103 losers. Thirteen "
        "entry-time cuts (pair, session, hour block, weekday, direction, HTF-bias "
        "alignment, setup type, liquidity type, zone kind, score band, target-pips "
        "quartile, stop-pips quartile) were scored on TRAIN and TEST independently -- the "
        "Loss Audit sheet has all of them. Six buckets are negative on TRAIN with n>=8. "
        "Every one flips or washes out: CHFJPY is -0.6618R on TRAIN and +1.2743R on TEST; "
        "PDL liquidity is -0.2977R then +0.3583R; Wednesday is -0.0124R then +0.5980R. "
        "The single cut that improved TRAIN and TEST together -- dropping signals from "
        "16:00 UTC onward -- removes a bucket that is POSITIVE over the full window "
        "(+0.0348R) and POSITIVE on the untouched validation split (+0.3809R), and "
        "dropping it HURTS validation. It was rejected before it reached the engine. The "
        "losses are not concentrated in a pair, an hour, a setup, a session or a score "
        "band. They are the 52.6% of a 47%-win-rate system that loses, and there is "
        "nothing in them to filter.\n\n"
        "2. THE WIN RATE -- 60% IS REACHABLE AT 1:2, AND IT IS FAKE. The audit found one "
        "live lever: the break-even stop was armed at +3R, which a 1:2 target can never "
        "reach, so trade management had been INERT. 66% of losers ran to +0.5R first and "
        "27% to +1.0R, so arming it lower is exactly what the loss shape suggests. Swept "
        "entry-matched (identical entries, exit-only change) on the Break-Even Sweep "
        "sheet. Arming at +0.50R produces a 66.34% win rate -- the owner's 60%, cleared. "
        "It is not a real improvement: 115 of those 205 trades exit AT the break-even "
        "offset, and the win rate excluding scratches is 47.78% against the baseline's "
        "47.45% -- unmoved. It costs 45% of the expectancy (+0.2660R to +0.1475R), turns "
        "the out-of-sample TEST half NEGATIVE (-0.0653R), and breaks the cluster interval. "
        "The effect is monotone across the whole sweep: every arming level that raises the "
        "printed win rate lowers the money. This is the same trade the 1:1 target offered "
        "in v7 and it is refused for the same reason.\n\n"
        "3. THE PAIR CULL -- THE SAMPLE CANNOT SUPPORT IT. Per-pair win rates were "
        "computed on TRAIN only and the TRAIN-chosen list scored on the untouched TEST "
        "(Pair Cull sheet). Of 29 instruments, 24 trade at all; TWO have 8 or more TRAIN "
        "trades; ONE (GBPUSD, n=14, 71.43%) clears 60%. The rest carry 0-7 TRAIN trades "
        "each and their win rates are arithmetic, not measurement -- a pair whose true win "
        "rate is the system's own 47.45% prints 60%-or-better 31.6% of the time at n=10. "
        "Screening 24 pairs on those samples manufactures a winning list every time. The "
        "GBPUSD-only universe is 23 trades in 1,200 days (0.024/day) and 17 walk-forward "
        "trades -- not a system. The broader TRAIN-selected list lifts TRAIN from +0.2931R "
        "to +0.3801R and LOWERS TEST from +0.1688R to +0.0918R, with walk-forward "
        "expectancy identical to four decimals. The cull moves only the half it was fitted "
        "on. ALL 29 PAIRS ARE KEPT.\n\n"
        "4. THREE TRADES A DAY -- ALREADY MEASURED, STILL NO. This was mapped to its end "
        "in v5-v7 and is not re-run here. On the 1H stack the ceiling is 0.62 trades a day "
        "and expectancy is negative there; on 30m the ceiling is 1.25 a day and it is "
        "negative at EVERY score gate on BOTH splits; only the 15m stack reaches 3.78 a "
        "day, and its cluster interval lies ENTIRELY BELOW ZERO -- it is a measured loser, "
        "not an untested option. The shipped configuration trades 0.163 times a day. "
        "Three-a-day does not exist profitably on this engine, and the honest answer is to "
        "say so rather than to raise frequency into a negative-expectancy stack.\n\n"
        "HOW THE CONFIGURATION WAS CHOSEN. TRAIN-only selection scored on an untouched "
        "TEST, plus a rolling walk-forward. The 1:2 target is the highest-win-rate point "
        "inside the owner's stated 1:2-1:5 band, and it is positive on all three splits "
        "independently -- TRAIN +0.2931R (n=95), VALIDATION +0.3503R (n=42), TEST +0.1688R "
        "(n=61). The full frontier is on the RR Frontier sheet. Both prior adopted configs "
        "reproduce exactly as a sanity check on the engine: v7 at 196 / 47.45% / PF 1.478 "
        "/ +0.2660R, v6 at 193 / 36.27% / PF 1.520 / +0.3521R.\n\n"
        "READ THIS BEFORE TRUSTING THE ROI. This is a thin edge on a small sample. The "
        "whole window is 196 trades sitting in 142 statistically independent clusters, "
        "because same-pair same-direction re-entries inside 24 hours are several bets on "
        "ONE liquidity event. Every confidence interval here is a CLUSTER bootstrap that "
        "resamples those groups whole. The full-window interval CLEARS zero "
        "([+0.0245, +0.5151]). The WALK-FORWARD interval DOES NOT: 168 out-of-sample "
        "trades across 122 clusters, 46.43% win rate, PF 1.404, +0.2304R, cluster CI "
        "[-0.0305, +0.5005] -- it spans zero. The walk-forward test is the harder one and "
        "it is the one to believe. The edge is encouraging and it is NOT established. A "
        "seven-loss run at 1% risk is a normal event at a 47% win rate, and one happened "
        "inside this window.\n\n"
        "WHAT IS NOT ESTABLISHED. That this makes money out of sample. That the win rate "
        "holds. That 60% is achievable at any reward-to-risk in the owner's band -- three "
        "separate searches now say it is not. Nothing in this repository has ever placed "
        "an order; there is no forward or demo result behind any number in this "
        "workbook.\n\n"
        "CONCURRENCY AND LOT ROUNDING. Up to three instruments hold fixed-1%-risk "
        "positions against the same account at once, so this is not full diversification "
        "and the ROI is an upper bound; correlated pairs can lose together. Position sizes "
        "are rounded to broker lot steps, which moves realised P&L slightly against the "
        "R-multiples. Dollar figures are read from the engine's booked P&L, never rebuilt "
        "from R.\n\n"
        "THE 90-DAY WINDOW IS ON ITS OWN SHEET AND IT IS NOT EVIDENCE. At 0.16 trades a "
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
        "Trades per day requested by owner": 3.0,
        "Longest losing streak": sf["streak"],
        "Expectancy (R)": round(sf["exp_r"], 4),
        "Expectancy ($/trade at 1% of $100k)": round(sf["exp_r"] * START * RISK_PCT, 2),
        "Break-even win rate at 1:2": "33.33%",
        "Win rate clears break-even by": f"{(sf['wr'] * 100) - 33.33:.2f} points",
        "Pairs kept after the 60% cull test": "29 of 29 -- the cull failed TEST",
    }

    rows = []
    for sym, g in full.groupby("Pair"):
        gl = abs(g.loc[g["P&L ($)"] < 0, "P&L ($)"].sum())
        gw = g.loc[g["P&L ($)"] > 0, "P&L ($)"].sum()
        rows.append({
            "Pair": sym, "Trades": len(g),
            "Win Rate": g["Win"].mean(),
            "PF": round(gw / gl, 3) if gl else "n/a (no losses)",
            "Total P&L ($)": round(float(g["P&L ($)"].sum()), 2),
            "Strategy Params": "1H SMC sniper, score>=80, flat 1:2 target, "
                               "min target 20 pips, BE stop inert below 3R",
        })
    per_instrument = pd.DataFrame(rows).sort_values("Total P&L ($)", ascending=False)

    rf.build_workbook(
        DEST,
        title="Mylifeloading SMC Sniper v8 -- 29 TradeLocker FX & metals instruments",
        subtitle=f"{first} to {last}  ·  $100,000 account  ·  1% risk/trade  ·  "
                 f"flat 1:2 target, 20-pip minimum  ·  1H execution  ·  "
                 f"TradeLocker broker bars  ·  config UNCHANGED from v7",
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
                "ISO weeks, continuous. At ~0.16 trades a day most weeks carry one trade or none.")
    write_table(wb.create_sheet("Monthly Profit"), period_profit(full, "M"),
                "Monthly Profit -- full window, $100,000 at 1% risk",
                "Continuous months. The flat and negative months are the ones to read: "
                "a thin edge spends long stretches doing nothing.")

    # ------------------------------------------------------ loss audit ------
    cuts = pd.read_csv(os.path.join(V8DIR, "v8_loss_cuts.csv"))
    cuts = cuts[cuts.cut != "exit reason"]
    cuts.columns = ["Cut", "Bucket", "TRAIN n", "TRAIN WR %", "TRAIN PF",
                    "TRAIN E (R)", "TEST n", "TEST WR %", "TEST PF",
                    "TEST E (R)", "All n", "All WR %", "All E (R)"]
    write_table(wb.create_sheet("Loss Audit"), cuts,
                "Loss audit -- every entry-time cut, TRAIN selects and TEST judges",
                "Baseline: TRAIN n=95 E +0.2931R  ·  TEST n=60 E +0.1889R  ·  full "
                "n=196 WR 47.45% E +0.2660R.\n"
                "A filter is only adopted if it improves BOTH halves. Six buckets are "
                "negative on TRAIN with n>=8 and NOT ONE holds: CHFJPY -0.6618 -> +1.2743, "
                "PDL -0.2977 -> +0.3583, Wednesday -0.0124 -> +0.5980, stop-quartile-2 "
                "+0.1087 on TRAIN but +0.0073 on TEST for 25% of the population.\n"
                "The only both-halves candidate (drop signals from 16:00 UTC) removes a "
                "bucket that is POSITIVE full-window (+0.0348R) and POSITIVE on the "
                "untouched validation split (+0.3809R), and dropping it HURTS validation. "
                "Rejected. NO LOSS CLUSTER EXISTS -- nothing was filtered.\n"
                "Exit reason is omitted here on purpose: it is an OUTCOME, not an "
                "entry-time property. 'Exclude the stop-loss bucket' is just deleting the "
                "losses.")

    shape = pd.read_csv(os.path.join(V8DIR, "v8_loss_shape.csv"))
    shape.columns = ["Field", "Winner mean", "Winner median", "Loser mean", "Loser median"]
    write_table(wb.create_sheet("Loss Shape"), shape,
                "What a loss looks like against what a win looks like (descriptive)",
                "These are OUTCOME fields -- MAE, MFE, bars held. They explain the losses; "
                "they cannot filter them, because none of them is knowable at entry.\n"
                "The one actionable reading: 66.0% of losers ran to +0.5R and 27.2% to "
                "+1.0R before reversing, while 40.9% of WINNERS first drew down past "
                "-0.50R and 12.9% past -0.75R. That symmetry is why arming the break-even "
                "stop converts winners into scratches at almost the same rate it rescues "
                "losers -- see the Break-Even Sweep sheet.\n"
                "Score is flat between winners and losers (80.54 vs 80.58), so the score "
                "gate has no further discrimination left in it at 80.")

    # ----------------------------------------------------- break-even -------
    be = pd.read_csv(os.path.join(V8DIR, "v8_breakeven.csv"))
    # Explicit name->label mapping. A positional rename here silently mislabels
    # a column whenever the harness adds or drops one, which is how a TEST
    # expectancy ends up printed under a VALIDATION header.
    BE_LABELS = [
        ("variant", "Break-even arming"), ("n", "Trades"), ("wr", "Win Rate %"),
        ("pf", "PF"), ("exp", "Expectancy (R)"),
        ("exp_usd", "Expectancy ($/trade)"), ("train_exp", "TRAIN E (R)"),
        ("validation_exp", "VALIDATION E (R)"), ("test_exp", "TEST E (R)"),
        ("max_dd", "Max DD %"), ("streak", "Longest Loss Streak"),
        ("scratch", "Scratch exits"), ("ccl_lo", "Cluster CI low"),
        ("ccl_hi", "Cluster CI high"), ("clears", "CI clears zero?"),
    ]
    missing = [k for k, _ in BE_LABELS if k not in be.columns]
    if missing:
        raise SystemExit(f"break-even sweep is missing columns: {missing}")
    be = be[[k for k, _ in BE_LABELS]]
    be.columns = [v for _, v in BE_LABELS]
    write_table(wb.create_sheet("Break-Even Sweep"), be,
                "Arming the break-even stop -- the win rate for money trade, priced",
                "Entry-matched and exit-only: identical entries on every row, only the "
                "stop management differs.\n"
                "v7 inherited a +3R arming trigger from the 1:4 config, which a 1:2 target "
                "can NEVER reach -- trade management has been inert all along. Arming it "
                "lower is what the loss shape suggests, and it is a trap.\n"
                "60% IS CLEARED: arming at +0.50R prints 66.34%. It is fake. 115 of those "
                "205 trades exit AT the break-even offset; win rate EXCLUDING SCRATCHES is "
                "47.78% against the baseline's 47.45% -- unmoved. Expectancy falls 45% and "
                "the TEST half goes NEGATIVE (-0.0653R).\n"
                "The relationship is monotone across the entire sweep: every arming level "
                "that raises the printed win rate lowers the money and breaks the interval. "
                "Nothing adopted; the inert +3R setting is kept.")

    # -------------------------------------------------------- pair cull -----
    pc = pd.read_csv(os.path.join(V8DIR, "v8_pair_train.csv"))
    pc.columns = ["Pair", "TRAIN n", "TRAIN WR %", "TRAIN PF", "TRAIN E (R)",
                  "Sample adequate?", "Clears 60% on TRAIN?", "TEST n",
                  "TEST WR %", "TEST E (R)", "All n", "All WR %", "All E (R)"]
    write_table(wb.create_sheet("Pair Cull"), pc,
                "The 60% per-pair cull -- selected on TRAIN, judged on TEST, REJECTED",
                "Of 29 instruments, 24 trade at all in the window. TWO have 8 or more "
                "TRAIN trades. ONE (GBPUSD) clears 60%. Every other row's win rate is "
                "arithmetic on 0-7 trades, marked NOISE, and must not be read as a "
                "measurement.\n"
                "How often a pair whose TRUE win rate is the system's own 47.45% FAKES "
                "60%+ on TRAIN: 27.5% of the time at n=4, 30.9% at n=8, 31.6% at n=10, "
                "18.4% at n=20. Screening 24 pairs at a 60% threshold on these samples "
                "manufactures a winning list every time.\n"
                "Scored out of sample with allowed_symbols passed into the engine, so the "
                "concurrency caps bind on the restricted universe: GBPUSD alone is 23 "
                "trades in 1,200 days (0.024/day, 17 walk-forward trades -- not a system). "
                "The broader TRAIN-selected list lifts TRAIN +0.2931 -> +0.3801 and LOWERS "
                "TEST +0.1688 -> +0.0918, with walk-forward expectancy identical to four "
                "decimals (+0.2304 both ways).\n"
                "ALL 29 PAIRS KEPT. The cull moves only the half it was fitted on.")

    us = pd.read_csv(os.path.join(V8DIR, "v8_universe_scored.csv"))
    wf = pd.read_csv(os.path.join(V8DIR, "v8_universe_wf.csv"))
    ucols = [c for c in ["variant", "pairs", "n", "per_day", "wr", "pf", "exp",
                         "train_n", "train_wr", "train_exp", "test_n", "test_wr",
                         "test_exp", "max_dd", "ccl_lo", "ccl_hi", "clears"]
             if c in us.columns]
    us = us[ucols].merge(wf.rename(columns={"universe": "variant"})[
        ["variant", "oos_n", "oos_wr", "oos_exp"]], on="variant", how="left")
    us.columns = ["Universe", "Pairs", "Trades", "Trades/day", "Win Rate %", "PF",
                  "Expectancy (R)", "TRAIN n", "TRAIN WR %", "TRAIN E (R)",
                  "TEST n", "TEST WR %", "TEST E (R)", "Max DD %",
                  "Cluster CI low", "Cluster CI high", "CI clears zero?",
                  "Walk-fwd n", "Walk-fwd WR %", "Walk-fwd E (R)"][:len(us.columns)]
    write_table(wb.create_sheet("Universe Test"), us,
                "Candidate pair universes scored on the untouched TEST and walk-forward",
                "This is the table that rejects the cull. Read TRAIN E against TEST E on "
                "row 3: the TRAIN-selected list gains +0.087R on the half it was chosen "
                "from and LOSES 0.077R on the half it was not.\n"
                "Walk-forward expectancy is identical for the full and culled universes "
                "(+0.2304R), which is what 'the cull does nothing out of sample' looks "
                "like numerically.")

    # ------------------------------------------------------- rr frontier ----
    frontier = pd.read_csv(os.path.join(V7DIR, "v7_rr_gate20.csv"))
    fr0 = pd.read_csv(os.path.join(V7DIR, "v7_rr_gate0.csv"))
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
                "The win-rate / reward-to-risk frontier -- why 1:2, carried forward from v7",
                "Every row is ENTRY-MATCHED: min_rr_on_liquidity is TRUE throughout, so the "
                "rows differ in their EXIT only and never in which setups they take.\n"
                "Read 'Clears By', not 'Win Rate'. 60.82% at 1:1 clears its 50% line by "
                "10.82 points; 47.45% at 1:2 clears its 33.33% line by 14.12. The higher "
                "win rate is the weaker result, and its TEST half is negative.\n"
                "v8 re-tested this from the other direction -- via the break-even stop "
                "rather than the target -- and got the same answer, which is the point: "
                "two independent ways of buying win rate, the same loss of money.")

    write_table(wb.create_sheet("90-Day Window"),
                period_profit(d90, "M") if not d90.empty else pd.DataFrame(),
                "The most recent 90 days -- NOT EVIDENCE, reported because it was asked for",
                f"{s9['n']} trades. At 0.16 trades a day that is what 90 days contains, and a "
                "sample that size cannot distinguish a working system from a broken one.\n"
                f"Ending balance ${s9['end']:,.2f}  ·  ROI {s9['roi']*100:+.2f}%  ·  "
                f"win rate {s9['wr']*100:.2f}%  ·  max drawdown {s9['dd']*100:.2f}%.\n"
                "Five of these seven trades lost. A five-loss run is completely ordinary at "
                "a 47% win rate -- the full window contains a seven-loss run and still ends "
                "up 61.93%. The full-window sheets are the ones that mean anything.")

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
