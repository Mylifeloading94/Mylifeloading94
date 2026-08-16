#!/usr/bin/env python3
"""SMC Sniper v8 -- the loss audit on the ADOPTED 1:2 population, and an
honest per-pair win-rate cull.

The owner's request, in his words: *"Find out the losing trades, see what needs
to be improved and tweak the bot and improve, increase win rate. Aim for
minimum 3 trades a day across all pairs and gold, remove any pairs that's under
60% win rate. Give feedback, profit, ROI."*

Two questions here are genuinely new, one is already closed:

1. **The loss audit on the CURRENT trade population.** v6 audited its losses on
   a flat-4R ledger and found no exploitable cluster. That population no longer
   exists: v7 adopted a flat 1:2 target, which turns a large share of v6's
   losers into winners and changes the shape of every cut. So the audit is
   re-run from scratch on the adopted ledger -- every entry-time cut (symbol,
   session, hour, weekday, direction, HTF-bias alignment, setup type, liquidity
   type, zone kind, score band, target/stop geometry) plus the descriptive
   outcome cuts (MAE, MFE, bars held) that explain the losses without being
   usable as filters.

2. **The per-pair win-rate cull.** Selected on TRAIN only, scored on an
   untouched TEST and on the walk-forward. The trap is obvious and it is the
   one this repo exists to catch: pick the pairs that won on TRAIN and they
   will win on TRAIN. The test that matters is whether the TRAIN-selected list
   holds up on data it was not chosen from.

3. **3 trades/day.** Already measured to its end in v5/v6/v7 and negative
   everywhere except the proven-losing 15m stack. Not re-run here.

    python3 tune_v8.py --round ledger   # dump the adopted ledger + reproduce v6/v7
    python3 tune_v8.py --round loss     # the loss audit, TRAIN then TEST
    python3 tune_v8.py --round pairs    # per-pair WR, TRAIN-selected, TEST-scored

Results land in ``reports/v8/``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tune_v5 import (apply, bounds, cluster_bootstrap, cluster_ids, evaluate,
                     load_env)
from tune_v6 import CTX, PCOLS
from tune_v7 import V6, geometry, pip_table, spread_table
from smc_sniper import walkforward
from smc_sniper.backtest import Backtester, trades_to_frame
from smc_sniper.metrics import compute_metrics, expectancy_ci

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "v8")
os.makedirs(OUT, exist_ok=True)

# The v7-adopted configuration: v6 (v5 + break-even at +3R) with a flat 1:2
# target and the 20-pip minimum-target gate live.
V7 = dict(V6)
V7.update({"targets.fixed_rr": 2.0, "targets.min_target_pips": 20.0})

RISK_PCT = 0.01
BALANCE = 100_000.0
MIN_TRAIN_N = 8          # below this a pair-level win rate is noise, not signal
WR_FLOOR = 60.0          # the owner's threshold


def env():
    return load_env("swing", "tradelocker", CTX, "_causal")


def label_splits(frame, sp):
    f = frame.copy()
    f["signal_time"] = pd.to_datetime(f["signal_time"], utc=True)
    (_, tr_b), (te_a, _) = sp["train"], sp["test"]
    f["split"] = np.where(f.signal_time < tr_b, "train",
                          np.where(f.signal_time >= te_a, "test", "val"))
    return f


def stats(frame, label="", ci=False):
    """n / WR / PF / expectancy for an arbitrary subset of a ledger."""
    if frame is None or not len(frame):
        return {"cut": label, "n": 0, "wr": np.nan, "pf": np.nan, "exp": np.nan,
                "total_r": 0.0}
    r = frame["r_multiple"].astype(float)
    wins, losses = r[r > 0], r[r <= 0]
    gross_w, gross_l = float(wins.sum()), float(-losses.sum())
    row = {
        "cut": label,
        "n": int(len(r)),
        "wins": int((r > 0).sum()),
        "wr": round(float((r > 0).mean()) * 100, 2),
        "pf": round(gross_w / gross_l, 3) if gross_l > 0 else np.nan,
        "exp": round(float(r.mean()), 4),
        "total_r": round(float(r.sum()), 2),
    }
    if ci and len(r) >= 25:
        lo, hi, nc = cluster_bootstrap(frame, 5000)
        row.update({"clusters": nc, "ccl_lo": round(lo, 4), "ccl_hi": round(hi, 4),
                    "clears": "YES" if not (lo < 0 < hi) else "no"})
    return row


def cut_table(frame, column, name, min_n=4):
    """One categorical cut, TRAIN and TEST scored independently side by side."""
    rows = []
    for value, g in frame.groupby(column, dropna=False):
        gt, ge = g[g.split == "train"], g[g.split == "test"]
        if len(gt) < min_n and len(ge) < min_n:
            continue
        st, se, sa = stats(gt), stats(ge), stats(g)
        rows.append({
            "cut": name, "value": str(value),
            "train_n": st["n"], "train_wr": st["wr"], "train_pf": st["pf"],
            "train_exp": st["exp"],
            "test_n": se["n"], "test_wr": se["wr"], "test_pf": se["pf"],
            "test_exp": se["exp"],
            "all_n": sa["n"], "all_wr": sa["wr"], "all_exp": sa["exp"],
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("train_exp", ascending=False)


# ---------------------------------------------------------------------------
# Round 1 -- dump the adopted ledger, and reproduce v6 and v7 exactly
# ---------------------------------------------------------------------------
def round_ledger():
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    pips, spreads = pip_table(cfg), spread_table(cfg)

    print("\n=== V8 SANITY CHECK: v6 and v7 must reproduce ===")
    for label, over, expect in (
        ("v7 flat 1:2 + 20p gate", V7, "196 / 47.45% / PF 1.478 / +0.2660R"),
        ("v6 flat 4R", V6, "193 / 36.27% / PF 1.520 / +0.3521R"),
    ):
        variant = apply(cfg, over)
        bt = Backtester(variant, engine)
        bt.bind(contexts)
        trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
        f = trades_to_frame(trades)
        m = compute_metrics(f, 10000.0)
        clo, chi, nc = cluster_bootstrap(f, 5000)
        print(f"  {label:24s} n={m['trades']:4d}  WR {m['win_rate']:6.2f}%  "
              f"PF {m['profit_factor']:6.3f}  E {m['expectancy_r']:+.4f}R  "
              f"cluster CI [{clo:+.4f}, {chi:+.4f}]")
        print(f"    expected: {expect}")
        if over is V7:
            led = label_splits(geometry(f, pips, spreads), sp)

    led["hour"] = led.signal_time.dt.hour
    led["dow"] = led.signal_time.dt.day_name()
    led["win"] = led.r_multiple > 0
    led["bias_aligned"] = ((led.htf_bias == "bullish") & (led.direction == "bullish")) | \
                          ((led.htf_bias == "bearish") & (led.direction == "bearish"))
    led.to_csv(os.path.join(OUT, "v8_adopted_ledger.csv"), index=False)
    print(f"\nledger -> {OUT}/v8_adopted_ledger.csv  "
          f"({len(led)} trades, {int(led.win.sum())} wins, "
          f"{int((~led.win).sum())} losses)")
    for s in ("train", "val", "test"):
        print(f"  {s:6s} {stats(led[led.split == s])}")
    return led


def load_ledger():
    path = os.path.join(OUT, "v8_adopted_ledger.csv")
    if not os.path.exists(path):
        return round_ledger()
    f = pd.read_csv(path)
    f["signal_time"] = pd.to_datetime(f["signal_time"], utc=True)
    f["exit_time"] = pd.to_datetime(f["exit_time"], utc=True)
    return f


# ---------------------------------------------------------------------------
# Round 2 -- the loss audit
# ---------------------------------------------------------------------------
def round_loss():
    led = load_ledger()
    losers = led[~led.win]
    winners = led[led.win]
    print(f"\n=== V8 LOSS AUDIT: {len(led)} trades, {len(winners)} winners, "
          f"{len(losers)} losers ({len(losers)/len(led)*100:.1f}%) ===")

    # -- descriptive: what a loss looks like against what a win looks like ----
    print("\n--- shape of a loss vs a win (descriptive, NOT filterable) ---")
    desc = []
    for col in ("mae_r", "mfe_r", "bars_held", "score", "target_pips",
                "stop_pips", "cost_share", "rr_tp2"):
        if col not in led.columns:
            continue
        desc.append({
            "field": col,
            "win_mean": round(float(winners[col].mean()), 3),
            "win_median": round(float(winners[col].median()), 3),
            "loss_mean": round(float(losers[col].mean()), 3),
            "loss_median": round(float(losers[col].median()), 3),
        })
    dframe = pd.DataFrame(desc)
    print(dframe.to_string(index=False))
    dframe.to_csv(os.path.join(OUT, "v8_loss_shape.csv"), index=False)

    # How many losers ever ran into meaningful profit before reversing?
    for thr in (0.5, 1.0, 1.5, 2.0):
        n = int((losers.mfe_r >= thr).sum())
        print(f"  losers reaching +{thr:.1f}R before losing: {n:3d} "
              f"({n/len(losers)*100:5.1f}%)")
    for thr in (0.25, 0.5, 0.75):
        n = int((winners.mae_r <= -thr).sum())
        print(f"  winners drawing down past -{thr:.2f}R first: {n:3d} "
              f"({n/len(winners)*100:5.1f}%)")

    # -- the entry-time cuts, TRAIN and TEST scored independently ------------
    led = led.copy()
    led["score_band"] = pd.cut(led.score, [79, 84, 89, 94, 101],
                               labels=["80-84", "85-89", "90-94", "95-100"])
    led["target_band"] = pd.qcut(led.target_pips, 4, duplicates="drop")
    led["stop_band"] = pd.qcut(led.stop_pips, 4, duplicates="drop")
    led["hour_block"] = pd.cut(led.hour, [-1, 5, 11, 15, 23],
                               labels=["00-05", "06-11", "12-15", "16-23"])

    cuts = [("symbol", "pair"), ("session", "session"), ("hour_block", "hour block"),
            ("dow", "weekday"), ("direction", "direction"),
            ("bias_aligned", "HTF bias aligned"), ("setup_type", "setup type"),
            ("liquidity_type", "liquidity type"), ("zone_kind", "zone kind"),
            ("score_band", "score band"), ("target_band", "target pips quartile"),
            ("stop_band", "stop pips quartile"), ("exit_reason", "exit reason")]

    tables = []
    for col, name in cuts:
        if col not in led.columns:
            continue
        t = cut_table(led, col, name)
        if t.empty:
            continue
        print(f"\n--- {name} (TRAIN selects, TEST judges) ---")
        print(t.to_string(index=False))
        tables.append(t)
    allcuts = pd.concat(tables, ignore_index=True)
    allcuts.to_csv(os.path.join(OUT, "v8_loss_cuts.csv"), index=False)

    # -- the screen: a cut is a candidate only if it is bad on TRAIN ---------
    base_train = stats(led[led.split == "train"])
    base_test = stats(led[led.split == "test"])
    print(f"\nbaseline TRAIN {base_train}")
    print(f"baseline TEST  {base_test}")

    # `exit reason` is an OUTCOME, not an entry-time property -- excluding the
    # stop-loss bucket is just deleting the losses. It is tabulated above for
    # completeness and it is never a filter candidate.
    cand = allcuts[(allcuts.train_n >= MIN_TRAIN_N)
                   & (allcuts.train_exp < 0)
                   & (allcuts.cut != "exit reason")].sort_values("train_exp")
    print("\n=== CANDIDATE EXCLUSIONS: negative on TRAIN with n>=8 ===")
    if cand.empty:
        print("  NONE. No entry-time cut with an adequate TRAIN sample is "
              "negative on TRAIN. There is no loss cluster to exclude.")
    else:
        print(cand.to_string(index=False))
        print("\n--- do they hold on TEST? (a filter must help BOTH halves) ---")
        rows = []
        for _, c in cand.iterrows():
            col = dict((n, k) for k, n in cuts)[c.cut]
            keep = led[led[col].astype(str) != c.value]
            kt, ke = stats(keep[keep.split == "train"]), stats(keep[keep.split == "test"])
            full = stats(keep, ci=True)
            rows.append({
                "excluded": f"{c.cut}={c.value}",
                "removed_n": int(c.all_n),
                "train_exp": kt["exp"], "d_train": round(kt["exp"] - base_train["exp"], 4),
                "test_exp": ke["exp"], "d_test": round(ke["exp"] - base_test["exp"], 4),
                "full_n": full["n"], "full_wr": full["wr"], "full_exp": full["exp"],
                "ccl_lo": full.get("ccl_lo"), "ccl_hi": full.get("ccl_hi"),
                "helps_both": "YES" if (kt["exp"] > base_train["exp"]
                                        and ke["exp"] > base_test["exp"]) else "no",
            })
        res = pd.DataFrame(rows).sort_values("d_test", ascending=False)
        print(res.to_string(index=False))
        res.to_csv(os.path.join(OUT, "v8_loss_filters.csv"), index=False)
    return allcuts


# ---------------------------------------------------------------------------
# Round 3 -- the per-pair win-rate cull
# ---------------------------------------------------------------------------
def round_pairs():
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    led = load_ledger()

    print("\n=== V8 PER-PAIR WIN RATE, TRAIN ONLY (the selection surface) ===")
    rows = []
    for sym, g in led.groupby("symbol"):
        gt = g[g.split == "train"]
        ge = g[g.split == "test"]
        st, se, sa = stats(gt), stats(ge), stats(g)
        rows.append({
            "pair": sym,
            "train_n": st["n"], "train_wr": st["wr"], "train_pf": st["pf"],
            "train_exp": st["exp"],
            "adequate": "yes" if st["n"] >= MIN_TRAIN_N else "NOISE",
            "clears_60": "yes" if (st["n"] >= MIN_TRAIN_N and st["wr"] >= WR_FLOOR)
                         else ("no" if st["n"] >= MIN_TRAIN_N else "-"),
            "test_n": se["n"], "test_wr": se["wr"], "test_exp": se["exp"],
            "all_n": sa["n"], "all_wr": sa["wr"], "all_exp": sa["exp"],
        })
    pf = pd.DataFrame(rows).sort_values(["train_n", "train_wr"], ascending=False)
    print(pf.to_string(index=False))
    pf.to_csv(os.path.join(OUT, "v8_pair_train.csv"), index=False)

    adequate = pf[pf.train_n >= MIN_TRAIN_N]
    print(f"\n  pairs in universe: {len(pf)}")
    print(f"  pairs with TRAIN n >= {MIN_TRAIN_N} (a 60% threshold is even "
          f"meaningful): {len(adequate)}")
    print(f"  pairs with TRAIN n < {MIN_TRAIN_N} -- their win rate is NOISE: "
          f"{len(pf) - len(adequate)}")
    if len(adequate):
        print(f"  of the adequate ones, clearing {WR_FLOOR:.0f}% WR on TRAIN: "
              f"{int((adequate.train_wr >= WR_FLOOR).sum())}")

    # Binomial reality check: with n TRAIN trades at the system's true 47.45%
    # win rate, how often does a pair show >= 60% by chance alone?
    from math import comb
    p = 0.4745
    print("\n--- how often a 47.45%-WR pair FAKES >=60% on n TRAIN trades ---")
    for n in (4, 6, 8, 10, 12, 15, 20, 30):
        need = int(np.ceil(0.6 * n))
        prob = sum(comb(n, k) * p**k * (1 - p)**(n - k) for k in range(need, n + 1))
        print(f"  n={n:3d}  needs {need:3d} wins  P(>=60% by luck) = {prob*100:5.1f}%")

    # -- the candidate universes ------------------------------------------
    keep_60 = sorted(adequate.loc[adequate.train_wr >= WR_FLOOR, "pair"])
    keep_60_plus_thin = sorted(set(keep_60) | set(pf.loc[pf.train_n < MIN_TRAIN_N, "pair"]))
    keep_pos = sorted(adequate.loc[adequate.train_exp > 0, "pair"])
    allsyms = sorted(cfg.get("markets"))

    universes = {
        "all pairs (v7 adopted)": None,
        f"TRAIN WR >= 60% and n >= {MIN_TRAIN_N}": keep_60,
        f"TRAIN WR >= 60% (n>={MIN_TRAIN_N}) + untested thin pairs": keep_60_plus_thin,
        f"TRAIN expectancy > 0 and n >= {MIN_TRAIN_N}": keep_pos,
    }
    json.dump({k: v for k, v in universes.items()},
              open(os.path.join(OUT, "v8_universes.json"), "w"), indent=1)

    print("\n=== V8 CANDIDATE UNIVERSES SCORED ON UNTOUCHED TEST ===")
    out = []
    for label, keep in universes.items():
        row, frames = evaluate(cfg, engine, contexts, V7, label, splits=sp,
                               allowed=keep)
        full = frames["full"]
        if len(full) >= 25:
            clo, chi, nc = cluster_bootstrap(full, 5000)
            row.update({"clusters": nc, "ccl_lo": round(clo, 4),
                        "ccl_hi": round(chi, 4),
                        "clears": "YES" if not (clo < 0 < chi) else "no"})
        row["pairs"] = len(keep) if keep is not None else len(allsyms)
        out.append(row)
        print(f"\n{label}  ({row['pairs']} pairs)")
        cols = ["n", "per_day", "wr", "pf", "exp", "train_n", "train_wr",
                "train_exp", "test_n", "test_wr", "test_exp", "max_dd",
                "ccl_lo", "ccl_hi", "clears"]
        print(pd.DataFrame([row])[[c for c in cols if c in row]].to_string(index=False))
    res = pd.DataFrame(out)
    res.to_csv(os.path.join(OUT, "v8_universe_scored.csv"), index=False)

    # -- walk-forward on the TRAIN-selected list ---------------------------
    print("\n=== WALK-FORWARD (the real out-of-sample verdict) ===")
    wf_rows = []
    for label, keep in universes.items():
        variant = apply(cfg, V7)
        bt = Backtester(variant, engine)
        bt.bind(contexts)
        wf = walkforward.walk_forward(bt, contexts, folds=5, train_frac=0.5,
                                      anchored=False, allowed_symbols=keep)
        oos, om = wf["oos_trades"], wf["oos_metrics"]
        if len(oos) >= 20:
            oclo, ochi, onc = cluster_bootstrap(oos, 5000)
        else:
            oclo = ochi = np.nan
            onc = 0
        print(f"  {label:52s} n={om['trades']:4d}  WR {om['win_rate']:6.2f}%  "
              f"PF {om['profit_factor']:6.3f}  E {om['expectancy_r']:+.4f}R  "
              f"cluster CI [{oclo:+.4f}, {ochi:+.4f}]")
        wf_rows.append({"universe": label, "oos_n": om["trades"],
                        "oos_wr": round(om["win_rate"], 2),
                        "oos_pf": round(om["profit_factor"], 3),
                        "oos_exp": round(om["expectancy_r"], 4),
                        "ccl_lo": round(oclo, 4), "ccl_hi": round(ochi, 4)})
    pd.DataFrame(wf_rows).to_csv(os.path.join(OUT, "v8_universe_wf.csv"), index=False)
    return res


# ---------------------------------------------------------------------------
# Round 4 -- the one live lever the loss audit exposed: the break-even stop
# ---------------------------------------------------------------------------
def round_exits():
    """v7 inherited v6's break-even trigger of +3R, which a 1:2 target can
    never reach -- so trade management is INERT in the adopted config (the
    ledger's exit reasons are TP1 and stop_loss, nothing else).

    The audit says 66% of losers ran to +0.5R and 27% to +1.0R before
    reversing, so arming the stop somewhere reachable is the one mechanical
    change the loss shape actually suggests. Every row is entry-matched by
    construction -- the entries are identical and only the exit differs -- and
    the cost is real: a winner that dips back past break-even after arming is
    converted from +2R into a scratch.
    """
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    rows = []
    variants = [("break-even OFF", {"targets.breakeven.enabled": False})]
    variants += [(f"break-even arms at +{t:.2f}R",
                  {"targets.breakeven.enabled": True, "targets.breakeven.trigger_r": t})
                 for t in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)]
    variants += [("v7 adopted (+3R, inert)",
                  {"targets.breakeven.enabled": True, "targets.breakeven.trigger_r": 3.0})]
    for label, over in variants:
        merged = dict(V7)
        merged.update(over)
        row, frames = evaluate(cfg, engine, contexts, merged, label, splits=sp)
        full = frames["full"]
        m = compute_metrics(full, 10000.0)
        clo, chi, nc = cluster_bootstrap(full, 5000)
        row.update({"ccl_lo": round(clo, 4), "ccl_hi": round(chi, 4),
                    "clears": "YES" if not (clo < 0 < chi) else "no",
                    "scratch": int((full.r_multiple.abs() < 0.05).sum()),
                    "streak": m.get("max_consecutive_losses", 0),
                    "exp_usd": round(row["exp"] * BALANCE * RISK_PCT, 2)})
        rows.append(row)
        print(f"\n{label}")
        cols = ["n", "wr", "pf", "exp", "exp_usd", "train_n", "train_wr", "train_exp",
                "val_n", "val_exp", "test_n", "test_wr", "test_exp", "max_dd",
                "streak", "scratch", "ccl_lo", "ccl_hi", "clears"]
        print(pd.DataFrame([row])[[c for c in cols if c in row]].to_string(index=False))
    print("\n=== V8 ROUND 4: BREAK-EVEN ARMING (entry-matched, exit-only) ===")
    frame = pd.DataFrame(rows)
    keep = [c for c in ["variant", "n", "wr", "pf", "exp", "exp_usd", "train_exp",
                        "val_exp", "test_exp", "max_dd", "streak", "scratch",
                        "ccl_lo", "ccl_hi", "clears"] if c in frame.columns]
    print(frame[keep].to_string(index=False))
    frame.to_csv(os.path.join(OUT, "v8_breakeven.csv"), index=False)
    return frame


ROUNDS = {"ledger": round_ledger, "loss": round_loss, "pairs": round_pairs,
          "exits": round_exits}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True, choices=sorted(ROUNDS))
    args = ap.parse_args()
    ROUNDS[args.round]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
