#!/usr/bin/env python3
"""Assemble the combined Excel deliverable from saved per-stack bundles.

``run_backtest.py`` writes every computed frame to ``reports/<stack>/``. This
script stitches those bundles into a single workbook with a Stack Comparison
sheet up front, so the spec-native 15m results and the long-window 1H results
sit side by side and neither can be quoted without the other.

    python3 run_backtest.py --stack swing
    python3 run_backtest.py --stack sniper
    python3 build_final_report.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smc_sniper import report_xlsx
from smc_sniper.config import load_config

REPO = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(REPO, "reports")

# The stack whose detail sheets fill the workbook (largest sample).
HEADLINE = "swing"
STACK_LABELS = {
    "swing": "LONG-WINDOW (1D bias / 4H structure / 1H setup) ~1200 days",
    "sniper": "SPEC-NATIVE (4H bias / 1H structure / 15m setup) ~400 days",
    "sniper_5m": "PRECISION CHECK (15m setup / 5m fills) ~120 days",
}


def load(stack: str, name: str) -> pd.DataFrame:
    path = os.path.join(REPORTS, stack, f"{name}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def summary_value(frame: pd.DataFrame, metric: str):
    if frame.empty or "metric" not in frame:
        return None
    row = frame[frame["metric"] == metric]
    return row.iloc[0]["value"] if not row.empty else None


def comparison(stacks: list[str]) -> pd.DataFrame:
    rows = []
    for stack in stacks:
        summary = load(stack, "summary")
        if summary.empty:
            continue
        splits = load(stack, "splits")
        wf = load(stack, "wf_oos_trades")

        def split_row(name):
            if splits.empty or "split" not in splits:
                return {}
            sel = splits[splits["split"] == name]
            return sel.iloc[0].to_dict() if not sel.empty else {}

        train, test = split_row("TRAIN"), split_row("TEST")
        if not wf.empty and "r_multiple" in wf:
            wf_n = len(wf)
            wf_wr = round((wf["r_multiple"] > 0).mean() * 100, 2)
        else:
            # Fall back to the per-fold summary when the OOS trade-level file
            # is unavailable (e.g. a bundle reconstructed from a workbook).
            folds = load(stack, "walk_forward")
            if not folds.empty and {"oos_trades", "oos_wr"} <= set(folds.columns):
                wf_n = int(folds["oos_trades"].sum())
                wins = (folds["oos_trades"] * folds["oos_wr"] / 100.0).sum()
                wf_wr = round(wins / wf_n * 100, 2) if wf_n else None
            else:
                wf_n, wf_wr = 0, None
        rows.append({
            "stack": stack,
            "description": STACK_LABELS.get(stack, stack),
            "full_trades": summary_value(summary, "trades"),
            "full_win_rate": summary_value(summary, "win_rate"),
            "full_wr_ci_low": summary_value(summary, "win_rate_ci_low"),
            "full_wr_ci_high": summary_value(summary, "win_rate_ci_high"),
            "full_profit_factor": summary_value(summary, "profit_factor"),
            "full_expectancy_r": summary_value(summary, "expectancy_r"),
            "full_max_dd_pct": summary_value(summary, "max_drawdown_pct"),
            "train_trades": train.get("trades"), "train_wr": train.get("win_rate"),
            "train_pf": train.get("profit_factor"),
            "test_trades": test.get("trades"), "test_wr": test.get("win_rate"),
            "test_pf": test.get("profit_factor"),
            "test_expectancy_r": test.get("expectancy_r"),
            "walkforward_oos_trades": wf_n, "walkforward_oos_wr": wf_wr,
            "reached_68pct": summary_value(summary, "target_68pct_reached"),
        })
    return pd.DataFrame(rows)


def main():
    cfg = load_config()
    stacks = [s for s in ("swing", "sniper", "sniper_5m")
              if os.path.isdir(os.path.join(REPORTS, s))]
    if not stacks:
        print("No bundles found. Run run_backtest.py first.")
        return 1
    print(f"Bundles found: {stacks}")

    head = HEADLINE if HEADLINE in stacks else stacks[0]
    compare = comparison(stacks)

    verdict_path = os.path.join(REPORTS, head, "verdict.txt")
    verdict = open(verdict_path).read().splitlines() if os.path.exists(verdict_path) else []

    # Prepend the cross-stack headline so the Verdict sheet leads with both.
    def num(value, digits=2):
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return str(value)

    lead = ["STACK COMPARISON -- both are reported; neither stands alone", ""]
    for _, row in compare.iterrows():
        lead.append(
            f"  {row['stack']}: {int(row['full_trades'])} trades, "
            f"{num(row['full_win_rate'])}% WR "
            f"(95% CI {num(row['full_wr_ci_low'])}-{num(row['full_wr_ci_high'])}), "
            f"PF {num(row['full_profit_factor'], 3)}, "
            f"expectancy {num(row['full_expectancy_r'], 4)}R, "
            f"max DD {num(row['full_max_dd_pct'])}%, "
            f"walk-forward OOS {row['walkforward_oos_trades']} trades at "
            f"{num(row['walkforward_oos_wr'])}% -- 68% reached: {row['reached_68pct']}")
    lead += ["", f"Detail sheets below are the '{head}' stack (largest sample).", "", "-" * 70, ""]
    verdict = lead + verdict

    adaptive = {}
    for dim in ("pair", "session", "setup_type", "liquidity_type",
                "rr_bucket", "volatility_regime", "direction_label"):
        frame = load(head, f"adaptive_{dim}")
        if not frame.empty:
            adaptive[dim] = frame

    summary = load(head, "summary")
    if not compare.empty:
        summary = pd.concat([
            summary,
            pd.DataFrame([{"metric": "--- stack comparison ---", "value": ""}]),
        ], ignore_index=True)

    out = os.path.join(REPO, "SMC_Sniper_Backtest.xlsx")
    report_xlsx.build(
        out, summary=summary, verdict=verdict, ledger=load(head, "ledger"),
        per_pair=load(head, "per_pair"), per_session=load(head, "per_session"),
        monthly=load(head, "monthly"), weekly=load(head, "weekly"),
        splits=load(head, "splits"), walk_forward=load(head, "walk_forward"),
        rejected=load(head, "rejected"), matched_r=load(head, "matched_r"),
        perturbation=load(head, "perturbation"), coverage=load(head, "coverage"),
        per_setup=load(head, "per_setup"), adaptive=adaptive,
        stack_comparison=compare)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
