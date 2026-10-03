"""
Confirm the handful of candidate gold configs on a FULL YEAR of real ticks.

Prints each result as soon as it lands (the big grid search was killed once by
a container reclaim with nothing saved) and splits every config's trades into
first/second half, because a config that only works in one half is the exact
failure mode that produced the discredited 90-day result.
"""
import json, os, sys
from dataclasses import replace, asdict

import pandas as pd

import gold_scalper_backtest as G

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results", "confirm_momentum.json")


def main():
    bars, ticks = G.load("M5")
    mid = bars.index[len(bars) // 2]
    print(f"bars {len(bars):,}  ticks {len(ticks):,}  "
          f"{bars.index[0].date()} -> {bars.index[-1].date()}")
    print(f"half split at {mid.date()}\n", flush=True)

    base = G.Config(setup="breakout", tf="M5", sess_start=0, sess_end=24,
                    max_bars_in_trade=48)
    cands = {
        "SHIPPED (bo20 rsi50-80 sess12-20 tp1.5)":
            G.Config(),
        "long rsi>70 tp1.5":
            replace(base, side="long", rsi_band_lo=70, rsi_band_hi=100, tp_r=1.5),
        "long rsi>70 trail2.0@1R":
            replace(base, side="long", rsi_band_lo=70, rsi_band_hi=100,
                    exit_mode="trail", tp_r=99.0, trail_atr=2.0, trail_start_r=1.0),
        "long rsi>70 trail1.5@1R":
            replace(base, side="long", rsi_band_lo=70, rsi_band_hi=100,
                    exit_mode="trail", tp_r=99.0, trail_atr=1.5, trail_start_r=1.0),
        "long rsi>70 trail2.0@0.5R":
            replace(base, side="long", rsi_band_lo=70, rsi_band_hi=100,
                    exit_mode="trail", tp_r=99.0, trail_atr=2.0, trail_start_r=0.5),
        "long rsi>75 trail2.0@1R":
            replace(base, side="long", rsi_band_lo=75, rsi_band_hi=100,
                    exit_mode="trail", tp_r=99.0, trail_atr=2.0, trail_start_r=1.0),
        "long rsi>70 trail2.0 sl1.4":
            replace(base, side="long", rsi_band_lo=70, rsi_band_hi=100, sl_atr=1.4,
                    exit_mode="trail", tp_r=99.0, trail_atr=2.0, trail_start_r=1.0),
        "long rsi>70 trail2.0 sl1.0":
            replace(base, side="long", rsi_band_lo=70, rsi_band_hi=100, sl_atr=1.0,
                    exit_mode="trail", tp_r=99.0, trail_atr=2.0, trail_start_r=1.0),
        "both rsi>70 trail2.0@1R":
            replace(base, side="both", rsi_band_lo=70, rsi_band_hi=100,
                    exit_mode="trail", tp_r=99.0, trail_atr=2.0, trail_start_r=1.0),
        "long rsi>70 tp0.5 (win-rate bait)":
            replace(base, side="long", rsi_band_lo=70, rsi_band_hi=100, tp_r=0.5),
    }

    print(f"{'config':36s} | {'n':>4}{'WR%':>7}{'PF':>6}{'totR':>8}{'DD':>7} | "
          f"{'H1 PF':>6}{'H2 PF':>7} | {'worst':>6}", flush=True)
    out = []
    for name, c in cands.items():
        t = G.simulate(bars, ticks, c)
        f = G.stats(t)
        if t is None or t.empty:
            print(f"{name:36s} | no trades", flush=True)
            continue
        st = pd.to_datetime(t.signal_time)
        if st.dt.tz is None:
            st = st.dt.tz_localize("UTC")
        s1, s2 = G.stats(t[st < mid]), G.stats(t[st >= mid])
        worst = min(s1["profit_factor"], s2["profit_factor"])
        print(f"{name:36s} | {f['trades']:4d}{f['win_rate']:7.1f}"
              f"{f['profit_factor']:6.2f}{f['total_r']:8.1f}{f['max_dd_r']:7.1f} | "
              f"{s1['profit_factor']:6.2f}{s2['profit_factor']:7.2f} | {worst:6.2f}",
              flush=True)
        out.append(dict(name=name, cfg=asdict(c), full=f, h1=s1, h2=s2,
                        worst_half_pf=worst))
        json.dump(out, open(OUT, "w"), indent=2, default=str)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
