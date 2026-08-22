"""
Signal-level simulator (no portfolio constraints).

This is the tool used for PARAMETER SELECTION. It takes every signal a symbol
produces and simulates it standalone with the same conservative fill rules as
the portfolio engine, so the statistics describe the SETUP rather than the
money-management layer on top of it.

Parameter selection is done on 2025 only. The 2026 window the user asked about
is never touched during selection.
"""
import numpy as np
import pandas as pd

import strategy as st
from strategy import PIP, SPREAD_PIPS, SLIPPAGE_PIPS, STOP_SLIPPAGE_PIPS


def simulate_symbol(symbol, frame, params, start, end, ctx=None):
    """Return a list of dicts, one per signal, with R-multiple outcomes."""
    ctx = ctx or st.Context(symbol, frame, params)
    idx = frame.index
    o = frame["open"].values; h = frame["high"].values
    l = frame["low"].values;  c = frame["close"].values
    n = len(idx)
    pip = PIP[symbol]
    spread = SPREAD_PIPS[symbol] * pip

    lo_i = int(np.searchsorted(idx.values, np.datetime64(start.tz_convert("UTC").tz_localize(None)), "left"))
    hi_i = int(np.searchsorted(idx.values, np.datetime64(end.tz_convert("UTC").tz_localize(None)), "right"))

    out = []
    blocked_until = -1
    for i in range(lo_i, min(hi_i, n - 1)):
        if i <= blocked_until:
            continue
        sig = st.evaluate(ctx, i)
        if sig is None:
            continue
        # ---- fill ----------------------------------------------------
        stop = sig.stop
        if params.entry_mode == "retrace":
            # rest a limit at sig.entry_ref; it fills only if a later bar
            # trades through it, and the trade is abandoned if the stop is
            # taken out first or the order expires unfilled.
            j = None
            lim = sig.entry_ref
            for k in range(i + 1, min(n, i + 1 + params.entry_expiry)):
                if (sig.direction > 0 and l[k] <= lim) or (sig.direction < 0 and h[k] >= lim):
                    j = k
                    break
                if (sig.direction > 0 and l[k] <= stop) or (sig.direction < 0 and h[k] >= stop):
                    break                       # invalidated before filling
            if j is None:
                continue
            entry = lim + sig.direction * (spread / 2 + SLIPPAGE_PIPS * pip)
        else:
            j = i + 1
            entry = o[j] + sig.direction * (spread / 2 + SLIPPAGE_PIPS * pip)
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + sig.direction * params.tp_r * risk
        tp1 = entry + sig.direction * params.tp1_r * risk

        r_realized = 0.0
        frac_open = 1.0
        cur_stop = stop
        tp1_done = False
        reason, bars = "open", 0
        mfe = mae = 0.0

        for k in range(j, min(n, j + params.time_stop_bars + 1)):
            bars = k - j + 1
            bh, bl, bo = h[k], l[k], o[k]
            fill_bar = (k == j)
            if sig.direction > 0:
                mfe = max(mfe, (bh - entry) / risk); mae = min(mae, (bl - entry) / risk)
            else:
                mfe = max(mfe, (entry - bl) / risk); mae = min(mae, (entry - bh) / risk)

            # On the bar the limit filled we cannot know the intrabar order,
            # so only the STOP may resolve there -- never the target, and the
            # gap-open test is meaningless on a bar we filled inside.
            if fill_bar:
                if (sig.direction > 0 and bl <= cur_stop) or (sig.direction < 0 and bh >= cur_stop):
                    px = cur_stop - sig.direction * STOP_SLIPPAGE_PIPS * pip
                    r_realized += frac_open * ((px - entry) * sig.direction) / risk
                    reason = "stop"; frac_open = 0.0; break
                continue

            # gap through the stop -> fill at the open
            if (sig.direction > 0 and bo <= cur_stop) or (sig.direction < 0 and bo >= cur_stop):
                r_realized += frac_open * ((bo - entry) * sig.direction) / risk
                reason = "stop_gap"; frac_open = 0.0; break

            if (not tp1_done) and params.tp1_frac > 0:
                hit1 = (sig.direction > 0 and bh >= tp1) or (sig.direction < 0 and bl <= tp1)
                hitsl = (sig.direction > 0 and bl <= cur_stop) or (sig.direction < 0 and bh >= cur_stop)
                if hit1 and not hitsl:
                    r_realized += params.tp1_frac * params.tp1_r
                    frac_open -= params.tp1_frac
                    tp1_done = True
                    if params.breakeven_after_tp1:
                        cur_stop = entry

            hitsl = (sig.direction > 0 and bl <= cur_stop) or (sig.direction < 0 and bh >= cur_stop)
            hittp = (sig.direction > 0 and bh >= target) or (sig.direction < 0 and bl <= target)
            if hitsl:                                  # ambiguity resolves against us
                px = cur_stop - sig.direction * STOP_SLIPPAGE_PIPS * pip
                r_realized += frac_open * ((px - entry) * sig.direction) / risk
                reason = "breakeven" if cur_stop == entry else "stop"
                frac_open = 0.0; break
            if hittp:
                r_realized += frac_open * params.tp_r
                reason = "target"; frac_open = 0.0; break
        else:
            k = min(n - 1, j + params.time_stop_bars)
            px = c[k] - sig.direction * SLIPPAGE_PIPS * pip
            r_realized += frac_open * ((px - entry) * sig.direction) / risk
            reason = "time"; frac_open = 0.0

        # commission expressed in R (round turn, standard-lot equivalent)
        cost_r = (st.COMMISSION_PER_LOT / (risk / pip * _pip_value(symbol, entry))) \
            if risk > 0 else 0.0
        r_net = r_realized - cost_r

        out.append(dict(symbol=symbol, time=idx[i], entry_time=idx[j], direction=sig.direction,
                        score=sig.score, r=r_net, r_gross=r_realized, reason=reason,
                        bars=bars, mfe=mfe, mae=mae, entry=entry, stop=stop,
                        target=target, planned_rr=sig.rr, parts=sig.parts))
        blocked_until = j + bars                       # one position per symbol
    return out


def _pip_value(symbol, price):
    """USD value of one pip per standard lot, approximated at `price`.
    Used only to express commission in R; the portfolio engine uses exact
    cross-rate conversion."""
    from strategy import CONTRACT, QUOTE
    contract = CONTRACT[symbol]
    pip = PIP[symbol]
    q = QUOTE[symbol]
    if q == "USD":
        return contract * pip
    if symbol.startswith("USD"):
        return contract * pip / price
    return contract * pip / price * 1.0                # cross approximation


def stats(rows):
    if not rows:
        return dict(n=0, wr=0.0, pf=0.0, exp=0.0, avg_win=0.0, avg_loss=0.0, total_r=0.0)
    r = np.array([x["r"] for x in rows])
    wins, losses = r[r > 0], r[r <= 0]
    gp, gl = wins.sum(), -losses.sum()
    return dict(
        n=len(r), wr=100.0 * len(wins) / len(r),
        pf=float(gp / gl) if gl > 0 else float("inf"),
        exp=float(r.mean()), total_r=float(r.sum()),
        avg_win=float(wins.mean()) if len(wins) else 0.0,
        avg_loss=float(losses.mean()) if len(losses) else 0.0,
    )
