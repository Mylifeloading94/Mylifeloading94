"""
Two-stage parameter search for the Gold Sniper Scalper.

Discipline (this is what stops a backtest from lying to you):
  * Stage 1 screens STRUCTURE (timeframe, breakout window, momentum band,
    trend stack, session) with the risk model held fixed, so we are not
    reading tea leaves across nine dimensions at once.
  * Stage 2 sweeps the RISK model over the structures that survived.
  * Everything is fitted on the FIRST 60 DAYS. The LAST 30 DAYS are held back
    and scored exactly once, at the end. A config that only works in-sample is
    an artefact, and is reported as one rather than shipped.

Usage:  python3 optimize_gold.py
"""
import json, os
from dataclasses import replace, asdict
from multiprocessing import Pool

import pandas as pd

import gold_scalper_backtest as G

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_TRADES_IS = 40          # below this a win rate is noise, not a result
SPLIT_DAYS = 60

_TICKS = None
_BARS = {}


def _init():
    global _TICKS, _BARS
    for tf in ("M5", "M15"):
        b, t = G.load(tf)
        _BARS[tf] = b
        _TICKS = t


def _slice(tf, part):
    b = _BARS[tf]
    split = b.index[0] + pd.Timedelta(days=SPLIT_DAYS)
    return b[b.index < split] if part == "is" else b[b.index >= split]


def _score_is(cfg):
    return G.stats(G.simulate(_slice(cfg.tf, "is"), _TICKS, cfg)), cfg


def _score_oos(cfg):
    return G.stats(G.simulate(_slice(cfg.tf, "oos"), _TICKS, cfg)), cfg


def desc(c):
    return (f"{c.tf} bo{c.bo_len} rsi{c.rsi_band_lo:.0f}-{c.rsi_band_hi:.0f} "
            f"stack{int(c.require_stack)} sess{c.sess_start}-{c.sess_end} "
            f"{c.stop_mode}{c.sl_atr} tp{c.tp_r} be{c.be_at_r}")


def show(tag, rows, n=12):
    print(f"\n=== {tag} ===")
    print(f"{'WR%':>6} {'PF':>6} {'totR':>8} {'exp':>7} {'n':>4}  config")
    for s, c in rows[:n]:
        print(f"{s['win_rate']:6.1f} {s['profit_factor']:6.2f} {s['total_r']:8.2f} "
              f"{s['expectancy_r']:7.3f} {s['trades']:4d}  {desc(c)}")


def main():
    base = G.Config(setup="breakout")
    with Pool(4, initializer=_init) as pool:
        s1 = [replace(base, tf=tf, bo_len=bo, rsi_band_lo=lo, rsi_band_hi=hi,
                      require_stack=st, sess_start=ss, sess_end=se,
                      max_bars_in_trade=(72 if tf == "M5" else 32))
              for tf in ("M5", "M15")
              for bo in (6, 12, 20)
              for lo, hi in ((50, 80), (55, 85), (45, 75))
              for st in (True, False)
              for ss, se in ((7, 20), (0, 24), (12, 20))]
        print(f"stage 1: {len(s1)} structural configs", flush=True)
        r1 = [(s, c) for s, c in pool.map(_score_is, s1, chunksize=2)
              if s["trades"] >= MIN_TRADES_IS]
        r1.sort(key=lambda t: t[0]["expectancy_r"], reverse=True)
        show("STAGE 1 - best expectancy (in-sample 60d)", r1)

        seeds, seen = [], set()
        for _, c in r1[:10]:
            k = (c.tf, c.bo_len, c.rsi_band_lo, c.rsi_band_hi, c.require_stack,
                 c.sess_start, c.sess_end)
            if k not in seen:
                seen.add(k)
                seeds.append(c)
        s2 = [replace(c, stop_mode=sm, sl_atr=sl, tp_r=tp, be_at_r=be)
              for c in seeds
              for sm, sl in (("atr", 0.8), ("atr", 1.2), ("atr", 1.8), ("swing", 1.2))
              for tp in (0.5, 0.8, 1.0, 1.5, 2.0)
              for be in (0.0, 0.5)]
        print(f"\nstage 2: {len(s2)} risk configs over {len(seeds)} structures",
              flush=True)
        r2 = [(s, c) for s, c in pool.map(_score_is, s2, chunksize=2)
              if s["trades"] >= MIN_TRADES_IS]
        r2.sort(key=lambda t: t[0]["expectancy_r"], reverse=True)
        show("STAGE 2 - best expectancy (in-sample)", r2)
        r2_wr = sorted([r for r in r2 if r[0]["profit_factor"] >= 1.15],
                       key=lambda t: t[0]["win_rate"], reverse=True)
        show("STAGE 2 - best WIN RATE with PF>=1.15 (in-sample)", r2_wr)

        finalists, seen = [], set()
        for _, c in (r2_wr[:8] + r2[:8]):
            k = json.dumps(asdict(c), sort_keys=True)
            if k not in seen:
                seen.add(k)
                finalists.append(c)
        if not finalists:
            print("\nNo in-sample config cleared the bar. Nothing to hold out.")
            return
        print(f"\nscoring {len(finalists)} finalists on the HELD-OUT last 30 days",
              flush=True)
        oos = pool.map(_score_oos, finalists, chunksize=1)

        is_map = {json.dumps(asdict(c), sort_keys=True): s for s, c in r2}
        out = []
        print("\n=== FINALISTS: in-sample (60d) vs HELD-OUT (30d) ===")
        for so, c in oos:
            si = is_map[json.dumps(asdict(c), sort_keys=True)]
            out.append(dict(cfg=asdict(c), is_=si, oos=so))
            print(f"  IS WR {si['win_rate']:5.1f}% PF {si['profit_factor']:5.2f} "
                  f"n={si['trades']:3d}  |  OOS WR {so['win_rate']:5.1f}% "
                  f"PF {so['profit_factor']:5.2f} n={so['trades']:3d}  {desc(c)}")
        json.dump(out, open(os.path.join(HERE, "data", "optimize_results.json"), "w"),
                  indent=2, default=str)
        print("\nwrote data/optimize_results.json")


if __name__ == "__main__":
    main()
