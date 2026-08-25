"""
SMC signal simulator with a stepped fixed-pip trailing stop.

TRAILING RULE (as specified: "trail stop loss into profit every 20 pips")
    Once price is `trail_start_pips` in profit, the stop is moved to
    (best price achieved) - `trail_gap_pips`, but only in `trail_step_pips`
    increments and only ever in the profitable direction. In practice:

        +20 pips  -> stop moves to entry (breakeven)
        +40 pips  -> stop moves to +20
        +60 pips  -> stop moves to +40   ... and so on

    Trailing is resolved on M1 bars when M1 data is present, so an intrabar
    spike that would have taken out the trailed stop is caught rather than
    being smoothed away by the M15 bar.

Fill and exit conventions match the rest of the project: signal on the close of
M15 bar i is filled no earlier than bar i+1, and every intrabar ambiguity
resolves against the account.
"""
import numpy as np
import pandas as pd

import smc
from strategy import PIP, SPREAD_PIPS, SLIPPAGE_PIPS, STOP_SLIPPAGE_PIPS, COMMISSION_PER_LOT, CONTRACT, QUOTE


def _pip_value(symbol, price):
    contract = CONTRACT[symbol]
    pip = PIP[symbol]
    if QUOTE[symbol] == "USD":
        return contract * pip
    return contract * pip / price


def trail_stop(cur_stop, entry, best, direction, pip, p):
    """Stepped trail. Returns the new stop, never worse than the current one.

    Two readings of "trail the stop into profit every 20 pips" are supported,
    because they behave very differently once the entry stop is small:

    mode "gap"  (default) - the stop follows the best price at a fixed
        distance (`trail_gap_pips`), updated in `trail_step_pips` increments.
        At +20 pips with a 20-pip gap the stop sits at entry; at +40 it sits
        at +20. This is the usual desk meaning of a trailing stop.

    mode "step" - the stop jumps to the last completed step boundary:
        +20 -> breakeven, +40 -> +20, +60 -> +40.

    With an 8-pip sniper stop, a 20-pip trigger is already ~2.4R of profit, so
    whichever mode is used the trail acts as a profit-lock rather than a tight
    trail. That interaction is measured in the report rather than assumed.
    """
    mode = getattr(p, "trail_mode", "gap")
    if mode == "off":
        return cur_stop

    if mode == "r":
        # R-based trail: every `trail_r` of progress, lock in one step less.
        risk_px = abs(entry - getattr(p, "_orig_stop", entry))
        if risk_px <= 0:
            return cur_stop
        prog_r = ((best - entry) if direction > 0 else (entry - best)) / risk_px
        steps = int(prog_r // p.trail_r)
        if steps < 1:
            return cur_stop
        cand = entry + direction * (steps - 1) * p.trail_r * risk_px
        return max(cur_stop, cand) if direction > 0 else min(cur_stop, cand)

    prog_pips = ((best - entry) if direction > 0 else (entry - best)) / pip
    if prog_pips < p.trail_start_pips:
        return cur_stop
    steps = int(prog_pips // p.trail_step_pips)
    if steps < 1:
        return cur_stop
    if mode == "gap":
        # quantise progress to completed steps, then hold `trail_gap_pips` back
        locked = steps * p.trail_step_pips - p.trail_gap_pips
    else:
        locked = (steps - 1) * p.trail_step_pips
    cand = entry + direction * locked * pip
    if direction > 0:
        return max(cur_stop, cand)
    return min(cur_stop, cand)


def simulate_symbol(symbol, m15, params, start, end, m1=None, ctx=None):
    ctx = ctx or smc.SMCContext(symbol, m15, params, m1=m1)
    idx = ctx.m15.index
    o, h, l, c = ctx.m15_o, ctx.m15_h, ctx.m15_l, ctx.m15_c
    n = len(idx)
    pip = PIP[symbol]
    spread = SPREAD_PIPS[symbol] * pip

    lo_i = int(np.searchsorted(idx.values, np.datetime64(start.tz_convert("UTC").tz_localize(None)), "left"))
    hi_i = int(np.searchsorted(idx.values, np.datetime64(end.tz_convert("UTC").tz_localize(None)), "right"))

    have_m1 = ctx.m1_idx is not None
    out = []
    blocked_until = -1

    for i in range(max(lo_i, 60), min(hi_i, n - 1)):
        if i <= blocked_until:
            continue
        sig = smc.evaluate_smc(ctx, i)
        if sig is None:
            continue

        stop = sig.stop
        j = i + 1                                    # never fill on the signal bar

        if sig.entry_tf == "M1" and have_m1:
            # The sniper entry is a LIMIT at the micro order block. It fills
            # only if price actually trades back into the block before the
            # order expires, and is abandoned if the stop is taken first.
            win = ctx.m1_slice(idx[i] + pd.Timedelta(minutes=15),
                               idx[i] + pd.Timedelta(minutes=15 * (params.m1_fill_bars + 1)))
            if win is None:
                continue
            a1, b1 = win
            fill_m = None
            for m in range(a1, min(b1, len(ctx.m1_c))):
                mh, ml = ctx.m1_h[m], ctx.m1_l[m]
                if (sig.direction > 0 and ml <= stop) or (sig.direction < 0 and mh >= stop):
                    break                            # invalidated before filling
                if (sig.direction > 0 and ml <= sig.entry) or \
                   (sig.direction < 0 and mh >= sig.entry):
                    fill_m = m
                    break
            if fill_m is None:
                continue
            fill_ts = ctx.m1_idx[fill_m]
            j = int(np.searchsorted(idx.values,
                                    np.datetime64(fill_ts.tz_localize(None)
                                                  if fill_ts.tzinfo else fill_ts), "right")) - 1
            j = max(j, i + 1)
            if j >= n - 1:
                continue
            entry = sig.entry + sig.direction * (spread / 2 + SLIPPAGE_PIPS * pip)
        else:
            entry = o[j] + sig.direction * (spread / 2 + SLIPPAGE_PIPS * pip)

        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + sig.direction * params.tp_r * risk

        cur_stop = stop
        params._orig_stop = stop          # the R-trail measures progress in R
        best = entry
        reason, bars = "open", 0
        r_out = None
        mfe = mae = 0.0
        exit_i = j

        for k in range(j, min(n, j + params.time_stop_bars_m15 + 1)):
            bars = k - j + 1
            exit_i = k
            bh, bl, bo = h[k], l[k], o[k]
            if sig.direction > 0:
                mfe = max(mfe, (bh - entry) / risk); mae = min(mae, (bl - entry) / risk)
            else:
                mfe = max(mfe, (entry - bl) / risk); mae = min(mae, (entry - bh) / risk)

            # ---- gap through the stop ----
            if (sig.direction > 0 and bo <= cur_stop) or (sig.direction < 0 and bo >= cur_stop):
                r_out = ((bo - entry) * sig.direction) / risk
                reason = "stop_gap"; break

            # ---- resolve this M15 bar on M1 when available ----
            if have_m1:
                sl_ = ctx.m1_slice(idx[k], idx[k] + pd.Timedelta(minutes=15))
                seq = range(sl_[0], sl_[1]) if sl_ else None
            else:
                seq = None

            if seq is not None and len(seq) > 0:
                hit = False
                for m in seq:
                    mh, ml = ctx.m1_h[m], ctx.m1_l[m]
                    # stop first: ambiguity resolves against the account
                    if (sig.direction > 0 and ml <= cur_stop) or (sig.direction < 0 and mh >= cur_stop):
                        px = cur_stop - sig.direction * STOP_SLIPPAGE_PIPS * pip
                        r_out = ((px - entry) * sig.direction) / risk
                        reason = "trail_stop" if _is_trailed(cur_stop, stop, sig.direction) else "stop"
                        hit = True; break
                    if (sig.direction > 0 and mh >= target) or (sig.direction < 0 and ml <= target):
                        r_out = params.tp_r
                        reason = "target"; hit = True; break
                    best = max(best, mh) if sig.direction > 0 else min(best, ml)
                    cur_stop = trail_stop(cur_stop, entry, best, sig.direction, pip, params)
                if hit:
                    break
            else:
                # M15-only resolution
                if (sig.direction > 0 and bl <= cur_stop) or (sig.direction < 0 and bh >= cur_stop):
                    px = cur_stop - sig.direction * STOP_SLIPPAGE_PIPS * pip
                    r_out = ((px - entry) * sig.direction) / risk
                    reason = "trail_stop" if _is_trailed(cur_stop, stop, sig.direction) else "stop"
                    break
                if (sig.direction > 0 and bh >= target) or (sig.direction < 0 and bl <= target):
                    r_out = params.tp_r; reason = "target"; break
                best = max(best, bh) if sig.direction > 0 else min(best, bl)
                cur_stop = trail_stop(cur_stop, entry, best, sig.direction, pip, params)
        else:
            k = min(n - 1, j + params.time_stop_bars_m15)
            exit_i = k
            px = c[k] - sig.direction * SLIPPAGE_PIPS * pip
            r_out = ((px - entry) * sig.direction) / risk
            reason = "time"

        cost_r = COMMISSION_PER_LOT / ((risk / pip) * _pip_value(symbol, entry))
        r_net = r_out - cost_r

        out.append(dict(symbol=symbol, time=idx[i], entry_time=idx[j],
                        exit_time=idx[exit_i], direction=sig.direction,
                        score=sig.score, r=r_net, r_gross=r_out, reason=reason,
                        bars=bars, mfe=mfe, mae=mae, entry=entry, stop=stop,
                        target=target, entry_tf=sig.entry_tf, rr=sig.rr,
                        risk_pips=risk / pip, parts=sig.parts))
        blocked_until = exit_i
    return out


def _is_trailed(cur_stop, orig_stop, direction):
    return (cur_stop > orig_stop) if direction > 0 else (cur_stop < orig_stop)


def stats(rows):
    if not rows:
        return dict(n=0, wr=0.0, pf=0.0, exp=0.0, total_r=0.0)
    r = np.array([x["r"] for x in rows])
    w, ls = r[r > 0], r[r <= 0]
    gp, gl = w.sum(), -ls.sum()
    return dict(n=len(r), wr=100.0 * len(w) / len(r),
                pf=float(gp / gl) if gl > 0 else float("inf"),
                exp=float(r.mean()), total_r=float(r.sum()),
                avg_win=float(w.mean()) if len(w) else 0.0,
                avg_loss=float(ls.mean()) if len(ls) else 0.0)
