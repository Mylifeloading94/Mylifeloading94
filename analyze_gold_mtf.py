"""
Live multi-timeframe SMC read on XAUUSD: Daily bias, 4H structure, 1H setup,
15m entry -- using the exact tested structure/liquidity/zone/signal engine,
not a hand-rolled chart read. Read-only.

    python3 analyze_gold_mtf.py
"""
import datetime

import smc_sniper.config as cfgmod
import smc_sniper.data as datamod
from smc_sniper.signal_engine import PairContext, generate_signals

SYMBOL = "XAUUSD"


def ts(t):
    return datetime.datetime.utcfromtimestamp(int(t)).strftime("%Y-%m-%d %H:%M")


def main():
    cfg = cfgmod.load_config()
    cfg = cfg.use_stack("swing").apply_profile("v6")
    # Owner asked for 15m sniper entry specifically -- swing's own entry_tf
    # is 1H; override it to 15m while keeping the validated 1D/4H/1H
    # bias/structure/setup layers untouched.
    cfg.set("stacks.swing.entry_tf", "15m")

    eng = datamod.DataEngine(cfg, source="tradelocker")
    for interval in ("1D", "4H", "1H", "15m"):
        res = eng.download(SYMBOL, interval, force=True)
        if not res.ok:
            print(f"  {interval}: FETCH FAILED -- {res.error}")

    ctx = PairContext(eng, SYMBOL, cfg)
    if not ctx.ok:
        print(f"{SYMBOL}: context build failed (insufficient data on one layer)")
        return

    stack = cfg.stack
    print("=" * 78)
    print(f"XAUUSD -- live multi-timeframe read, {datetime.datetime.utcnow():%Y-%m-%d %H:%M} UTC")
    print(f"stack: bias={stack['bias_tf']} structure={stack['structure_tf']} "
          f"setup={stack['setup_tf']} entry={stack['entry_tf']}")
    print("=" * 78)

    price = ctx.setup.iloc[-1].close
    print(f"\nlast closed {stack['setup_tf']} bar: {ctx.setup.index[-1]}  close={price:.2f}")

    for label, frame, state, name in (
        ("DAILY bias", ctx.bias_frame, ctx.bias_state, stack["bias_tf"]),
        ("4H structure", ctx.struct_frame, ctx.struct_state, stack["structure_tf"]),
        ("1H setup", ctx.setup, ctx.setup_state, stack["setup_tf"]),
    ):
        bias = ctx.htf_bias(len(ctx.setup) - 1) if name == stack["bias_tf"] else None
        print(f"\n--- {label} ({name}) --- last bar {frame.index[-1]}  close={frame.iloc[-1].close:.2f}")
        recent = state.events[-3:] if state.events else []
        for e in recent:
            print(f"  {e.kind:6s} {e.direction:8s} broke {e.broken_swing.label} "
                  f"@ {e.broken_swing.price:.2f}  disp={e.displacement}")
        if not recent:
            print("  no structure events in this window")

    print(f"\ncurrent HTF bias (per {stack['bias_tf']}, min_swings gate): {ctx.htf_bias(len(ctx.setup)-1)}")
    print(f"current mid-TF bias (per {stack['structure_tf']}): {ctx.structure_bias(len(ctx.setup)-1)}")

    # Liquidity pools still unswept, nearest to price
    pools = ctx.liq.pools if hasattr(ctx.liq, "pools") else []
    above = sorted([p for p in pools if p.price > price], key=lambda p: p.price)[:3]
    below = sorted([p for p in pools if p.price < price], key=lambda p: -p.price)[:3]
    print(f"\nnearest liquidity pools above price: {[(round(p.price,2), p.kind) for p in above]}")
    print(f"nearest liquidity pools below price: {[(round(p.price,2), p.kind) for p in below]}")

    # Active order blocks / FVGs at the current bar, both directions
    last_i = len(ctx.setup) - 1
    active = []
    for direction in ("bullish", "bearish"):
        active += [("OB", direction, z) for z in ctx.zones.active_obs(last_i, direction)]
        active += [("FVG", direction, z) for z in ctx.zones.active_fvgs(last_i, direction)]
    active_sorted = sorted(active, key=lambda t: min(abs(t[2].top - price), abs(t[2].bottom - price)))[:5]
    print(f"\nnearest active zones (OB/FVG) at the current bar:")
    for kind, direction, z in active_sorted:
        print(f"  {kind:4s} {direction:8s} [{z.bottom:.2f} - {z.top:.2f}]  "
              f"dist={min(abs(z.top-price), abs(z.bottom-price)):.2f}  quality={z.quality}")
    if not active_sorted:
        print("  none active right now")

    # Run the actual validated signal generator on this context, then filter
    # to setups still LIVE right now (same rule as execute_live.py/scan_live.py:
    # a signal is fresh only while valid_until_bar > the current bar index).
    sigs, rejs = generate_signals(ctx, cfg)
    n_s = len(ctx.setup)
    live = [s for s in sigs if s.valid_until_bar > n_s - 1]
    print(f"\n{'='*78}\nSIGNAL ENGINE (same code path as execute_live.py):")
    print(f"  {len(sigs)} setup(s) found across the whole {stack['setup_tf']} history; "
          f"{len(live)} still LIVE right now (valid_until_bar > current bar {n_s-1}).")
    if live:
        for s in live:
            bars_left = s.valid_until_bar - (n_s - 1)
            print(f"\n  LIVE SETUP: {s.direction.upper()} {s.symbol}")
            print(f"    entry {s.entry:.2f}  stop {s.stop:.2f}  tp {s.tp2:.2f}  "
                  f"R:R {s.rr_tp2:.1f}  score {s.score:.0f}")
            print(f"    fill window: {bars_left} bars left  |  session {s.session}")
            print(f"    reasons: {', '.join(s.scorecard.reasons)}")
    else:
        print("\n  No live setup right now -- honest answer, not a hedge.")
        if sigs:
            most_recent = max(sigs, key=lambda s: s.bar_index)
            age = n_s - 1 - most_recent.bar_index
            print(f"  Most recent setup in this pair's history: {most_recent.direction} "
                  f"at {most_recent.time}, {age} bars ago (long expired, fill window was "
                  f"{most_recent.valid_until_bar - most_recent.bar_index} bars).")
        recent_rejs = rejs[-3:] if rejs else []
        if recent_rejs:
            print("  most recent rejected candidates (why they didn't qualify):")
            for r in recent_rejs:
                print(f"    {r}")
    print("=" * 78)


if __name__ == "__main__":
    main()
