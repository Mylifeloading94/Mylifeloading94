#!/usr/bin/env python3
"""SMC Sniper -- backtest entry point.

Runs the full honest protocol and writes every artefact:

    python3 run_backtest.py                    # default stack from config
    python3 run_backtest.py --stack sniper     # 15m setup, ~400d broker data
    python3 run_backtest.py --stack swing      # 1H setup, ~1200d broker data
    python3 run_backtest.py --refresh-data     # re-pull bars from TradeLocker
    python3 run_backtest.py --source yahoo     # credential-free fallback
    python3 run_backtest.py --quick            # skip perturbation/matched-R

Outputs land in ``reports/`` plus ``SMC_Sniper_Backtest.xlsx`` at the repo root.
No orders are placed and no order endpoint is contacted -- ever.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smc_sniper import adaptive as adaptive_mod
from smc_sniper import dashboard, report_xlsx, walkforward
from smc_sniper.backtest import Backtester, rejections_to_frame, trades_to_frame
from smc_sniper.config import load_config
from smc_sniper.data import DataEngine
from smc_sniper.logging_engine import DecisionLog
from smc_sniper.metrics import (breakdown, compute_metrics, equity_curve,
                                expectancy_ci, periodic, win_rate_ci)
from smc_sniper.news import NewsFilter
from smc_sniper.telegram import TelegramEngine

REPO = os.path.dirname(os.path.abspath(__file__))


def parse_args():
    p = argparse.ArgumentParser(description="SMC Sniper backtest")
    p.add_argument("--stack", default=None, help="sniper | sniper_5m | swing")
    p.add_argument("--source", default=None, help="tradelocker | yahoo")
    p.add_argument("--refresh-data", action="store_true")
    p.add_argument("--quick", action="store_true",
                   help="skip perturbation and matched-R control")
    p.add_argument("--xlsx", default=os.path.join(REPO, "SMC_Sniper_Backtest.xlsx"))
    p.add_argument("--no-xlsx", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = load_config()
    if args.stack:
        cfg.set("active_stack", args.stack)
    source = args.source or cfg.get("data.provider", "tradelocker")
    stack = cfg.stack
    balance = float(cfg.get("risk.starting_balance", 10000.0))

    print("=" * 78)
    print(f"SMC SNIPER BACKTEST -- stack '{stack['name']}'  source '{source}'")
    print(f"  {stack['bias_tf']} bias / {stack['structure_tf']} structure / "
          f"{stack['setup_tf']} setup / {stack['entry_tf']} entry")
    print(f"  score gate {cfg.score_threshold:.0f} of {cfg.get('scoring.max_possible', 95)} max"
          f"  |  risk {cfg.get('risk.risk_per_trade_pct')}%/trade")
    print("=" * 78)

    engine = DataEngine(cfg, source=source)
    if args.refresh_data:
        print("\nRefreshing market data...")
        results = engine.download_all(force=True)
        failed = [r for r in results if not r.ok]
        if failed:
            print(f"\n  {len(failed)} fetch failures (proceeding with the rest):")
            for r in failed:
                print(f"    {r.symbol} {r.interval}: {r.error}")

    news = NewsFilter(cfg)
    print(f"\nNews filter: {news.status}")
    if not news.active:
        print("  -> backtest runs WITHOUT news filtering (no calendar available)")

    log = DecisionLog(cfg, f"decisions_{stack['name']}")
    log.reset()
    telegram = TelegramEngine(cfg)

    # ---------------- full window ----------------
    t0 = time.time()
    bt = Backtester(cfg, engine)
    contexts = bt.build_contexts()
    print(f"\nContexts built for {len(contexts)}/{len(cfg.symbols)} pairs "
          f"({time.time() - t0:.0f}s)")
    missing = [s for s in cfg.symbols if s not in contexts]
    if missing:
        print(f"  PAIRS WITHOUT DATA (documented, not silently dropped): {missing}")

    coverage = pd.concat([engine.coverage(tf) for tf in
                          dict.fromkeys([stack["bias_tf"], stack["structure_tf"],
                                         stack["setup_tf"], stack["entry_tf"]])],
                         ignore_index=True)

    trades, rejections, _ = bt.run(contexts=contexts)
    ledger = trades_to_frame(trades)
    rej_frame = rejections_to_frame(rejections)
    metrics = compute_metrics(ledger, balance)
    print(f"\nSignals generated : {bt.n_signals_total}")
    print(f"Trades executed   : {metrics['trades']}")

    for sig_symbol, sig in bt.collect_signals(contexts)[0][:200]:
        log.signal(sig)
    for rej in rejections[:4000]:
        log.rejection(rej)
    for trade in trades:
        log.fill(trade)
        log.close(trade)

    wr_lo, wr_hi = win_rate_ci(ledger, int(cfg.get("backtest.bootstrap_iterations", 5000)))
    ex_lo, ex_hi = expectancy_ci(ledger, int(cfg.get("backtest.bootstrap_iterations", 5000)))

    print("\n--- FULL WINDOW (in-sample + out-of-sample combined) ---")
    for key in ("trades", "win_rate", "profit_factor", "expectancy_r", "total_r",
                "net_profit", "max_drawdown_pct", "sharpe", "sortino",
                "avg_winner_r", "avg_loser_r", "max_consecutive_losses"):
        print(f"  {key:24s} {metrics[key]:>12.4f}")
    print(f"  win_rate 95% CI          [{wr_lo:.2f}, {wr_hi:.2f}]")
    print(f"  expectancy_r 95% CI      [{ex_lo:.4f}, {ex_hi:.4f}]")

    # ---------------- splits ----------------
    fractions = (float(cfg.get("backtest.train_fraction", 0.5)),
                 float(cfg.get("backtest.validation_fraction", 0.2)),
                 float(cfg.get("backtest.test_fraction", 0.3)))
    print("\n--- CHRONOLOGICAL SPLITS ---")
    split_res = walkforward.run_splits(bt, contexts, fractions, balance)
    split_rows = []
    for name in ("train", "validation", "test"):
        m = split_res[name]["metrics"]
        a, b = split_res["bounds"][name]
        lo, hi = win_rate_ci(split_res[name]["trades"], 2000)
        split_rows.append({
            "split": name.upper(), "start": a[:10], "end": b[:10],
            "trades": m["trades"], "win_rate": round(m["win_rate"], 2),
            "wr_ci_low": round(lo, 2), "wr_ci_high": round(hi, 2),
            "profit_factor": round(m["profit_factor"], 3),
            "expectancy_r": round(m["expectancy_r"], 4),
            "total_r": round(m["total_r"], 2),
            "max_dd_pct": round(m["max_drawdown_pct"], 2)})
        print(f"  {name.upper():11s} n={m['trades']:<4} WR={m['win_rate']:5.2f}% "
              f"PF={m['profit_factor']:5.3f} E={m['expectancy_r']:+.4f}R")
    splits = pd.DataFrame(split_rows)

    # pair selection: TRAIN only, frozen, then applied to TEST
    chosen, sel_note = walkforward.select_pairs_on_train(
        split_res["train"]["trades"], cfg, with_note=True)
    print(f"\n  Pair selection on TRAIN only: {sel_note}")
    print(f"  -> {chosen}")
    sel_row = {}
    if chosen:
        a, b = split_res["bounds"]["test"]
        sel_trades, _, _ = bt.run(contexts=contexts, start=pd.Timestamp(a),
                                  end=pd.Timestamp(b), collect_rejections=False,
                                  allowed_symbols=chosen)
        sel_frame = trades_to_frame(sel_trades)
        sm = compute_metrics(sel_frame, balance)
        lo, hi = win_rate_ci(sel_frame, 2000)
        sel_row = {"split": "TEST (train-selected pairs)", "start": a[:10],
                   "end": b[:10], "trades": sm["trades"],
                   "win_rate": round(sm["win_rate"], 2), "wr_ci_low": round(lo, 2),
                   "wr_ci_high": round(hi, 2),
                   "profit_factor": round(sm["profit_factor"], 3),
                   "expectancy_r": round(sm["expectancy_r"], 4),
                   "total_r": round(sm["total_r"], 2),
                   "max_dd_pct": round(sm["max_drawdown_pct"], 2)}
        splits = pd.concat([splits, pd.DataFrame([sel_row])], ignore_index=True)
        print(f"  TEST on those pairs: n={sm['trades']} WR={sm['win_rate']:.2f}% "
              f"PF={sm['profit_factor']:.3f} E={sm['expectancy_r']:+.4f}R")

    # ---------------- walk-forward ----------------
    print("\n--- WALK-FORWARD ---")
    wf = walkforward.walk_forward(
        bt, contexts, folds=int(cfg.get("backtest.walk_forward.folds", 5)),
        anchored=bool(cfg.get("backtest.walk_forward.anchored", False)),
        starting_balance=balance)
    wf_metrics = wf["oos_metrics"]
    print(wf["folds"][["fold", "fit_trades", "fit_wr", "fit_exp_r",
                       "oos_trades", "oos_wr", "oos_exp_r"]].to_string(index=False))
    wf_lo, wf_hi = win_rate_ci(wf["oos_trades"], 2000)
    print(f"  COMBINED OOS: n={wf_metrics['trades']} WR={wf_metrics['win_rate']:.2f}% "
          f"[{wf_lo:.1f},{wf_hi:.1f}] PF={wf_metrics['profit_factor']:.3f} "
          f"E={wf_metrics['expectancy_r']:+.4f}R")

    # ---------------- controls ----------------
    matched = perturb = None
    if not args.quick:
        print("\n--- MATCHED-R CONTROL (anti TP-shrinking) ---")
        matched = walkforward.matched_r_control(
            lambda c: Backtester(c, engine), contexts, cfg, starting_balance=balance)
        print(matched.to_string(index=False))

        print("\n--- PERTURBATION ---")

        def rebuild(variant):
            return Backtester(variant, engine).build_contexts()

        perturb = walkforward.perturbation_check(
            lambda c: Backtester(c, engine), contexts, cfg, {
                "scoring.threshold": [75, 80, 85],
                "stops.buffer_atr": [0.2, 0.25, 0.35],
                "stops.min_stop_over_cost": [0.0, 6.0, 10.0, 15.0],
                "targets.min_rr": [1.5, 2.0, 2.5],
                "fvg.min_size_atr": [0.14, 0.18, 0.25],
                "structure.swing_lookback": [2, 3],
            }, starting_balance=balance, rebuild_fn=rebuild)
        print(perturb.to_string(index=False))

    # ---------------- breakdowns ----------------
    per_pair = breakdown(ledger, "symbol", balance)
    per_session = breakdown(ledger, "session", balance)
    per_setup = breakdown(ledger, "setup_type", balance)
    monthly = periodic(ledger, "ME", balance)
    weekly = periodic(ledger, "W", balance)
    adaptive_tables = adaptive_mod.analyse(ledger, cfg, balance)
    adaptive_notes = adaptive_mod.recommendations(adaptive_tables, cfg)

    rejected_summary = pd.DataFrame()
    if not rej_frame.empty:
        rejected_summary = (rej_frame.groupby(["step", "reason"])
                            .size().reset_index(name="count")
                            .sort_values("count", ascending=False).head(80))

    # ---------------- verdict ----------------
    target = 68.0
    hit = metrics["win_rate"] >= target and metrics["profit_factor"] > 1.0
    oos_hit = wf_metrics["win_rate"] >= target and wf_metrics["profit_factor"] > 1.0
    verdict = build_verdict(cfg, stack, source, metrics, wr_lo, wr_hi, ex_lo, ex_hi,
                            splits, wf_metrics, wf_lo, wf_hi, target, hit, oos_hit,
                            news, chosen, matched, adaptive_notes, len(contexts),
                            bt.n_signals_total, coverage)
    print("\n" + "=" * 78)
    for line in verdict[:26]:
        print(line)
    print("=" * 78)

    # ---------------- artefacts ----------------
    summary_rows = [{"metric": k, "value": v} for k, v in metrics.items()]
    summary_rows += [
        {"metric": "win_rate_ci_low", "value": round(wr_lo, 3)},
        {"metric": "win_rate_ci_high", "value": round(wr_hi, 3)},
        {"metric": "expectancy_ci_low", "value": round(ex_lo, 4)},
        {"metric": "expectancy_ci_high", "value": round(ex_hi, 4)},
        {"metric": "signals_generated", "value": bt.n_signals_total},
        {"metric": "rejected_setups", "value": len(rej_frame)},
        {"metric": "stack", "value": stack["name"]},
        {"metric": "data_source", "value": source},
        {"metric": "score_threshold", "value": cfg.score_threshold},
        {"metric": "score_max_possible", "value": cfg.get("scoring.max_possible", 95)},
        {"metric": "news_filter", "value": news.status},
        {"metric": "target_68pct_reached", "value": "YES" if hit else "NO"},
    ]
    summary = pd.DataFrame(summary_rows)

    caveats = data_caveats(cfg, source, stack, news, coverage)
    tables = {"Per-pair": per_pair, "Per-session": per_session,
              "In-sample / out-of-sample": splits,
              "Walk-forward folds": wf["folds"],
              "Monthly": monthly,
              "Rejected setups (top reasons)": rejected_summary}
    if matched is not None:
        tables["Matched-R control"] = matched
    dash_path = dashboard.write(cfg, metrics, tables, caveats)
    print(f"\nDashboard : {dash_path}")

    equity = equity_curve(ledger, balance)
    if not equity.empty:
        equity.to_csv(os.path.join(REPO, "reports", f"equity_{stack['name']}.csv"),
                      index=False)

    if not args.no_xlsx:
        path = report_xlsx.build(
            args.xlsx, summary=summary, verdict=verdict, ledger=ledger,
            per_pair=per_pair, per_session=per_session, monthly=monthly,
            weekly=weekly, splits=splits, walk_forward=wf["folds"],
            rejected=rejected_summary, matched_r=matched, perturbation=perturb,
            coverage=coverage, per_setup=per_setup, adaptive=adaptive_tables)
        print(f"Excel     : {path}")
    print(f"Decisions : {log.path}")
    telegram.daily_summary(metrics)
    return 0


def data_caveats(cfg, source, stack, news, coverage) -> list[str]:
    setup_tf = stack["setup_tf"]
    rows = coverage[coverage["tf"] == setup_tf] if not coverage.empty else pd.DataFrame()
    days = int(rows["days"].max()) if not rows.empty else 0
    out = [
        f"Data source: {source}. Bars are BID (TradeLocker) or mid (Yahoo); the "
        f"backtester adds spread explicitly rather than reading bid/ask depth.",
        f"Setup timeframe {setup_tf} covers about {days} days -- the provider's "
        f"history limit, not a choice.",
        "No historical economic calendar is available, so results are computed "
        "WITHOUT news filtering. The filter is implemented and config-driven.",
        "Paper/demo forward results: PENDING DEMO RUN. Nothing here has traded live.",
        "XAUUSD on the Yahoo fallback is the COMEX future GC=F, a close but not "
        "identical proxy for spot gold.",
    ]
    if news.active:
        out[2] = f"News filter ACTIVE: {news.status}."
    return out


def build_verdict(cfg, stack, source, m, wr_lo, wr_hi, ex_lo, ex_hi, splits,
                  wf_m, wf_lo, wf_hi, target, hit, oos_hit, news, chosen,
                  matched, adaptive_notes, n_pairs, n_signals, coverage) -> list[str]:
    def row(name):
        sel = splits[splits["split"] == name]
        return sel.iloc[0] if not sel.empty else None

    train, test = row("TRAIN"), row("TEST")
    lines = [
        "VERDICT",
        "",
        f"Did this system reach the 68% win-rate target?   {'YES' if hit else 'NO'}",
        "",
        f"Full window: {m['trades']} trades, {m['win_rate']:.2f}% win rate "
        f"(95% CI {wr_lo:.1f}-{wr_hi:.1f}%), profit factor {m['profit_factor']:.3f}, "
        f"expectancy {m['expectancy_r']:+.4f}R (95% CI {ex_lo:+.4f} to {ex_hi:+.4f}).",
        f"Max drawdown {m['max_drawdown_pct']:.2f}%. "
        f"Longest losing streak {m['max_consecutive_losses']}.",
        "",
    ]
    if not hit:
        lines += [
            "The 68% target was NOT reached, and it is not being rounded up to or",
            "argued toward. The measured win rate is what it is. Per the spec's own",
            "instruction -- 'do not claim a 68% win rate unless the actual test data",
            "demonstrates it' -- this is reported against the target, not manufactured.",
            "",
        ]
    if m["profit_factor"] <= 1.0:
        lines += [
            "MORE IMPORTANTLY: profit factor is at or below 1.0 and expectancy is",
            "negative. This configuration does not have a demonstrated edge. It should",
            "NOT be traded with real money in its current form. A lower win rate with",
            "good expectancy would be preferable to this; what is here is neither.",
            "",
        ]
    if train is not None and test is not None:
        lines += [
            f"TRAIN ({train['start']} to {train['end']}): {train['trades']} trades, "
            f"{train['win_rate']:.2f}% WR, PF {train['profit_factor']:.3f}, "
            f"E {train['expectancy_r']:+.4f}R",
            f"TEST  ({test['start']} to {test['end']}): {test['trades']} trades, "
            f"{test['win_rate']:.2f}% WR, PF {test['profit_factor']:.3f}, "
            f"E {test['expectancy_r']:+.4f}R",
        ]
        gap = train["win_rate"] - test["win_rate"]
        if abs(gap) > 8:
            lines.append(f"  -> TRAIN/TEST win-rate gap of {gap:+.1f} points. A large gap "
                         "is the signature of a fit, not an edge.")
        lines.append("")
    lines += [
        f"WALK-FORWARD (out-of-sample only, pairs chosen per fold on the fit window):",
        f"  {wf_m['trades']} trades, {wf_m['win_rate']:.2f}% WR "
        f"(95% CI {wf_lo:.1f}-{wf_hi:.1f}%), PF {wf_m['profit_factor']:.3f}, "
        f"E {wf_m['expectancy_r']:+.4f}R",
        f"  Walk-forward reached 68%? {'YES' if oos_hit else 'NO'}",
        "",
    ]
    if matched is not None and not matched.empty:
        lines += ["MATCHED-R CONTROL (proves the result is not TP-shrinking):"]
        for _, r in matched.iterrows():
            verdict_word = "beats" if r["win_rate"] > r["breakeven_wr_needed"] else "below"
            lines.append(
                f"  fixed {r['fixed_rr']}R -> {r['trades']} trades, "
                f"{r['win_rate']:.1f}% WR vs {r['breakeven_wr_needed']:.1f}% needed "
                f"({verdict_word}), E {r['expectancy_r']:+.4f}R")
        lines += [
            "  Win rate falling as R rises is the expected mechanical relationship.",
            "  What matters is whether win rate clears the break-even line at any R.",
            "",
        ]
    lines += [
        "SAMPLE SIZE AND CONFIDENCE:",
        f"  {n_signals} signals -> {m['trades']} filled trades across {n_pairs} pairs.",
        f"  The 95% win-rate CI spans {wr_hi - wr_lo:.1f} points. A point estimate on",
        "  this sample size is not precise enough to defend to one decimal place.",
        "",
        "HOW COSTS WERE MODELLED (the honesty-critical part):",
        "  - Limit fills require price to trade THROUGH the level. A touch is not a fill.",
        "  - Spread is charged in full at entry, on top of BID bars.",
        "  - Slippage is applied against the trade on entry and on stop exits.",
        "  - A bar that reaches both TP and SL is booked as a LOSS.",
        "  - Commission is charged per round turn.",
        "  Relaxing any one of these would raise the headline number and make it false.",
        "",
        "CAVEATS:",
    ]
    lines += [f"  - {c}" for c in data_caveats(cfg, source, stack, news, coverage)]
    lines += ["", "ADAPTIVE ANALYSIS (suggestions only, never overrides risk):"]
    lines += [f"  - {n}" for n in adaptive_notes[:12]]
    lines += ["", f"Pairs selected on TRAIN only: {chosen or '(none qualified)'}"]
    return lines


if __name__ == "__main__":
    sys.exit(main())
