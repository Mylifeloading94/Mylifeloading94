"""
Search the gold momentum-continuation family over a FULL YEAR of real ticks,
ranking by CONSISTENCY rather than by the best single number.

Method notes that matter:
  * One simulate per config over the whole year; the resulting trades are then
    split by date into first/second half. That is 3x cheaper than simulating
    each half separately and avoids giving each half its own indicator warmup.
  * Configs are ranked by min(PF_first_half, PF_second_half) -- the WORSE half.
    Ranking by full-period PF rewards a config that got one lucky quarter,
    which is exactly the mistake that produced the earlier 90-day result.
  * A config must clear a trade floor or its win rate is noise.

Usage:  python3 search_momentum.py [--out results/search_momentum.json]
"""
import argparse, json, os
from dataclasses import replace, asdict
from multiprocessing import Pool

import pandas as pd

import gold_scalper_backtest as G

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_TRADES = 120

_B = _T = _MID = None


def _init():
    global _B, _T, _MID
    _B, _T = G.load("M5")
    _MID = _B.index[len(_B) // 2]


def _run(c):
    t = G.simulate(_B, _T, c)
    if t is None or t.empty:
        return G.stats(t), G.stats(t), G.stats(t), c
    st = pd.to_datetime(t.signal_time)
    if st.dt.tz is None:
        st = st.dt.tz_localize("UTC")
    h1 = t[st < _MID]
    h2 = t[st >= _MID]
    return G.stats(t), G.stats(h1), G.stats(h2), c


def build_grid():
    base = G.Config(setup="breakout", tf="M5", sess_start=0, sess_end=24)
    cfgs = []
    for side in ("long", "both"):
        for rl in (65, 70, 75):
            for sl in (1.0, 1.4, 1.8):
                # trailing exits
                for tr in (1.0, 1.5, 2.0):
                    for ts in (0.5, 1.0):
                        cfgs.append(replace(base, side=side, rsi_band_lo=rl,
                                            rsi_band_hi=100, sl_atr=sl,
                                            exit_mode="trail", tp_r=99.0,
                                            trail_atr=tr, trail_start_r=ts,
                                            max_bars_in_trade=48))
                # fixed targets, for comparison on equal terms
                for tp in (1.0, 1.5, 2.0):
                    cfgs.append(replace(base, side=side, rsi_band_lo=rl,
                                        rsi_band_hi=100, sl_atr=sl,
                                        exit_mode="fixed", tp_r=tp,
                                        max_bars_in_trade=48))
    seen, uniq = set(), []
    for c in cfgs:
        k = json.dumps(asdict(c), sort_keys=True)
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def label(c):
    ex = f"trail{c.trail_atr}@{c.trail_start_r}R" if c.exit_mode == "trail" \
        else f"tp{c.tp_r}"
    return f"{c.side:5s} rsi>{c.rsi_band_lo:.0f} sl{c.sl_atr} {ex}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "results",
                                                  "search_momentum.json"))
    a = ap.parse_args()
    cfgs = build_grid()
    print(f"{len(cfgs)} configs over a full year of ticks", flush=True)

    rows = []
    with Pool(4, initializer=_init) as pool:
        for n, (f, s1, s2, c) in enumerate(pool.imap_unordered(_run, cfgs, chunksize=1), 1):
            rows.append((f, s1, s2, c))
            if n % 10 == 0:
                print(f"  {n}/{len(cfgs)}", flush=True)

    ok = [r for r in rows if r[0]["trades"] >= MIN_TRADES]
    ok.sort(key=lambda r: min(r[1]["profit_factor"], r[2]["profit_factor"]),
            reverse=True)
    print(f"\n{len(ok)} configs cleared the {MIN_TRADES}-trade floor\n")
    print(f"{'config':34s} | {'n':>4}{'WR%':>7}{'PF':>6}{'totR':>8} | "
          f"{'H1 PF':>6}{'H2 PF':>7} | {'worst':>6}")
    for f, s1, s2, c in ok[:25]:
        print(f"{label(c):34s} | {f['trades']:4d}{f['win_rate']:7.1f}"
              f"{f['profit_factor']:6.2f}{f['total_r']:8.1f} | "
              f"{s1['profit_factor']:6.2f}{s2['profit_factor']:7.2f} | "
              f"{min(s1['profit_factor'], s2['profit_factor']):6.2f}")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump([dict(cfg=asdict(c), full=f, h1=s1, h2=s2)
               for f, s1, s2, c in ok], open(a.out, "w"), indent=2, default=str)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
