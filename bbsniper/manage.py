"""Module 11 - trade management with honest fills.

Chart prices are BID. Longs: enter at ask (signal close + spread), stops/targets on bid.
Shorts: enter at bid (signal close), stops/targets on ask (bar price + spread).
Rules: management starts on the bar AFTER the signal bar; if a bar touches the stop and a target,
the stop is assumed first; a gap through the stop fills at the open; targets need a small
trade-through; break-even and trailing changes take effect from the next bar."""


def simulate(ctx, sig, cfg):
    x, atr = ctx.x, ctx.xi["atr"]
    o, h, l, c = x["o"], x["h"], x["l"], x["c"]; n = len(c)
    side, E, S, R = sig["side"], sig["entry"], sig["stop"], sig["risk"]
    spr = 0.0 if side == 1 else ctx.spread
    thr = cfg["tp_through_pips"] * ctx.pip
    tps = [E + side * r * R for r in cfg["tp_r"]]; fr = list(cfg["tp_frac"])
    rem, stop, hit, pnl, best = 1.0, S, [False] * len(tps), 0.0, E
    exit_i, how = None, None; i0 = sig["i"]
    last = min(n - 1, i0 + cfg["max_hold_bars"])
    for k in range(i0 + 1, last + 1):
        lo_k, hi_k, op = l[k] + spr, h[k] + spr, o[k] + spr
        if (lo_k <= stop) if side == 1 else (hi_k >= stop):                 # stop first (pessimistic)
            px = min(stop, op) if side == 1 else max(stop, op)
            pnl += rem * (px - E) * side; rem = 0.0; exit_i = k
            how = "SL" if not hit[0] else ("BE" if abs(stop - E) <= cfg["be_buffer_r"] * R + 1e-12 else "TRAIL")
            break
        for j, tp in enumerate(tps):
            if hit[j]: continue
            if (hi_k >= tp + thr) if side == 1 else (lo_k <= tp - thr):
                q = rem if j == len(tps) - 1 else fr[j]
                pnl += q * (tp - E) * side; rem -= q; hit[j] = True
        if rem <= 1e-9:
            exit_i, how = k, f"TP{len(tps)}"; break
        if hit[0] and cfg["be_after_tp1"]:
            be = E + side * cfg["be_buffer_r"] * R
            stop = max(stop, be) if side == 1 else min(stop, be)
        best = max(best, hi_k) if side == 1 else min(best, lo_k)
        if cfg["trail"] == "atr" and (best - E) * side >= cfg["trail_after_r"] * R:
            ts = best - side * cfg["trail_atr"] * atr[k]
            stop = max(stop, ts) if side == 1 else min(stop, ts)
    if exit_i is None:                                                       # time stop / end of data
        exit_i = last; px = c[last] + spr; pnl += rem * (px - E) * side
        how = "TIME" if last < n - 1 else "OPEN@END"
    r = pnl / R
    return dict(exit_i=exit_i, exit_t=int(x["t"][exit_i] + ctx.sec), r=round(r, 4), exit=how,
                tp1=hit[0], tp2=len(hit) > 1 and hit[1], tp3=len(hit) > 2 and hit[2], bars=exit_i - i0)
