"""
Portfolio backtest engine.

Realism rules (all deliberately conservative):
  * A signal computed on the close of bar i is FILLED AT THE OPEN OF BAR i+1.
  * Entry crosses the spread and pays adverse slippage.
  * Stops pay additional adverse slippage; a gap through the stop fills at the
    gapped open, not the stop price.
  * If a bar's range touches both the stop and the target, the STOP is assumed
    to have hit first. Every ambiguous bar resolves against the account.
  * Commission is charged round-turn per lot on entry and on each exit slice.
  * P&L is converted to USD with the live cross-rate for that timestamp.

Portfolio controls: fixed-fractional risk, daily loss cap, concurrent-position
cap, per-currency exposure cap, consecutive-loss lockout.
"""
import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import strategy as st
from strategy import (PIP, CONTRACT, QUOTE, BASE, SPREAD_PIPS,
                      COMMISSION_PER_LOT, SLIPPAGE_PIPS, STOP_SLIPPAGE_PIPS)


@dataclass
class RiskConfig:
    start_balance: float = 10_000.0
    risk_pct: float = 0.005            # 0.5% of equity per trade
    risk_pct_gold: float = 0.0035      # gold gaps harder -> smaller
    max_daily_loss: float = 0.02       # stop trading for the day at -2%
    max_concurrent: int = 3
    max_per_currency: int = 2          # same-currency same-direction exposure
    max_consecutive_losses: int = 4    # then sit out the rest of the day
    max_trades_per_day: int = 3        # quality over quantity
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 50.0


@dataclass
class Trade:
    symbol: str
    direction: int
    entry_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    tp1: float
    lots: float
    risk_usd: float
    score: int
    planned_rr: float
    parts: dict = field(default_factory=dict)
    # filled on close
    exit_time: pd.Timestamp = None
    exit: float = None
    reason: str = None
    pnl: float = 0.0
    r_multiple: float = 0.0
    bars_held: int = 0
    mfe_r: float = 0.0
    mae_r: float = 0.0


class UsdConverter:
    """Converts one price unit of a symbol's QUOTE currency into USD, using
    the rate that was live at that timestamp (reindexed, forward-filled)."""

    def __init__(self, frames):
        self.close = {s: f["close"] for s, f in frames.items()}
        self._cache = {}

    def _series(self, sym, index):
        # Keyed on the index's identity-by-value, not id(): a freed Index can
        # be reallocated at the same address, which would silently hand back
        # another symbol's conversion rates.
        key = (sym, len(index), index[0], index[-1])
        if key not in self._cache:
            self._cache[key] = self.close[sym].reindex(index).ffill().bfill()
        return self._cache[key]

    def quote_to_usd(self, symbol, index):
        """Series aligned to `index`: USD value of 1 unit of quote currency."""
        q = QUOTE[symbol]
        ones = pd.Series(1.0, index=index)
        if q == "USD":
            return ones
        direct = f"USD{q}"          # e.g. USDJPY -> 1 JPY = 1/USDJPY USD
        if direct in self.close:
            return 1.0 / self._series(direct, index)
        inverse = f"{q}USD"         # e.g. GBPUSD -> 1 GBP = GBPUSD USD
        if inverse in self.close:
            return self._series(inverse, index)
        raise KeyError(f"no USD cross available for {q}")


def round_lots(x, cfg):
    lots = np.floor(x / cfg.lot_step) * cfg.lot_step
    return float(np.clip(round(lots, 2), 0.0, cfg.max_lot))


def _trail(cur_stop, entry, best, direction, risk, pip, params):
    """Stepped trail into profit. Proportional (`trail_r`) by preference,
    fixed-pip (`trail_pips`) if that is what is configured."""
    step_r = getattr(params, "trail_r", 0.0)
    if step_r > 0 and risk > 0:
        prog = ((best - entry) if direction > 0 else (entry - best)) / risk
        steps = int(prog // step_r)
        if steps < 1:
            return cur_stop
        locked = (steps * step_r - getattr(params, "trail_gap_r", step_r)) * risk
        cand = entry + direction * locked
        return max(cur_stop, cand) if direction > 0 else min(cur_stop, cand)
    if getattr(params, "trail_pips", 0.0) <= 0:
        return cur_stop
    prog = ((best - entry) if direction > 0 else (entry - best)) / pip
    steps = int(prog // params.trail_pips)
    if steps < 1:
        return cur_stop
    locked = steps * params.trail_pips - params.trail_gap_pips
    cand = entry + direction * locked * pip
    return max(cur_stop, cand) if direction > 0 else min(cur_stop, cand)


def run(frames, params: st.Params, cfg: RiskConfig, start, end, symbols=None, m1=None):
    """Run the portfolio backtest.

    frames : {symbol: M15 OHLCV DataFrame} covering warm-up + test window
    start/end : tz-aware bounds of the REPORTED window
    """
    symbols = symbols or sorted(frames)
    conv = UsdConverter(frames)

    ctxs, q2usd = {}, {}
    for s in symbols:
        ctxs[s] = st.Context(s, frames[s], params)
    # Context may resample up to the signal timeframe; the engine must walk
    # the SAME bars the signals were computed on.
    frames = {**frames, **{s: ctxs[s].m15 for s in symbols}}
    for s in symbols:
        q2usd[s] = conv.quote_to_usd(s, frames[s].index).values

    # master clock = union of all bar timestamps inside the test window
    all_idx = sorted(set().union(*[set(frames[s].index) for s in symbols]))
    all_idx = [t for t in all_idx if start <= t <= end]
    clock = pd.DatetimeIndex(all_idx)

    # positional lookup per symbol (plain dicts: the hot path runs this
    # ~400k times, and pandas .loc is two orders of magnitude slower)
    pos_of = {s: {ts: k for k, ts in enumerate(frames[s].index)} for s in symbols}
    arr = {s: {c: frames[s][c].values for c in ("open", "high", "low", "close")}
           for s in symbols}
    bar_index = {s: frames[s].index for s in symbols}

    equity = cfg.start_balance
    balance = cfg.start_balance
    open_trades = []          # list of (Trade, symbol_bar_index_at_entry)
    closed = []
    equity_curve = []

    day = None
    day_start_equity = equity
    day_pnl = 0.0
    day_trades = 0
    day_locked = False
    consec_losses = 0

    pending = []              # signals waiting for the next bar's open

    for t in clock:
        d = t.date()
        if d != day:
            day = d
            day_start_equity = equity
            day_pnl = 0.0
            day_trades = 0
            day_locked = False

        # -------------------------------------------------------------
        # 1. manage open trades on this bar (before any new entry)
        # -------------------------------------------------------------
        still_open = []
        for tr in open_trades:
            s = tr.symbol
            i = pos_of[s].get(t)
            if i is None:
                still_open.append(tr)
                continue
            f = arr[s]
            o = f["open"][i]; hi = f["high"][i]; lo = f["low"][i]
            pip = PIP[s]
            unit_usd = CONTRACT[s] * q2usd[s][i]     # USD per 1.0 price unit per lot
            tr.bars_held += 1

            # ---- trail the stop into profit -------------------------------
            # Resolved bar-by-bar on M1 when available. Stop and target are
            # tested INSIDE that walk, in sequence, before the trail is
            # advanced -- otherwise a bar that dips and then rallies would be
            # measured against a stop that had not yet moved when the dip
            # happened, which manufactures losses that never occurred.
            trailing = (getattr(params, "trail_r", 0.0) > 0
                        or getattr(params, "trail_pips", 0.0) > 0)
            m1_walk = None
            if trailing:
                mm = (m1 or {}).get(s)
                if mm is not None:
                    if getattr(tr, "_m1_ts", None) is None:
                        tr._m1_ts = mm.index.values.astype("datetime64[ns]")
                        tr._m1_h = mm["high"].values.astype(float)
                        tr._m1_l = mm["low"].values.astype(float)
                    t0 = np.datetime64(t.tz_localize(None) if t.tzinfo else t)
                    t1 = t0 + np.timedelta64(params.tf_minutes, "m")
                    a1 = int(np.searchsorted(tr._m1_ts, t0, "left"))
                    b1 = int(np.searchsorted(tr._m1_ts, t1, "right"))
                    if b1 > a1:
                        m1_walk = (a1, min(b1, len(tr._m1_h)))

            def close_slice(px, frac, reason):
                lots = tr.lots * frac
                gross = (px - tr.entry) * tr.direction * unit_usd * lots
                comm = COMMISSION_PER_LOT * lots * 0.5      # half the round turn
                return gross - comm, lots, reason

            realized = 0.0
            done = False
            risk_px0 = abs(tr.entry - tr.stop_initial)

            if m1_walk is not None:
                a1, b1 = m1_walk
                for k1 in range(a1, b1):
                    mh, ml = tr._m1_h[k1], tr._m1_l[k1]
                    hit_stop = (ml <= tr.stop) if tr.direction > 0 else (mh >= tr.stop)
                    if hit_stop:
                        px = tr.stop - tr.direction * STOP_SLIPPAGE_PIPS * pip
                        trailed = ((tr.stop > tr.stop_initial) if tr.direction > 0
                                   else (tr.stop < tr.stop_initial))
                        lbl = "trail_stop" if trailed else "stop"
                        pnl, _, _ = close_slice(px, 1.0, lbl)
                        realized += pnl
                        tr.exit, tr.reason, done = px, lbl, True
                        break
                    hit_tp = (mh >= tr.target) if tr.direction > 0 else (ml <= tr.target)
                    if hit_tp:
                        pnl, _, _ = close_slice(tr.target, 1.0, "target")
                        realized += pnl
                        tr.exit, tr.reason, done = tr.target, "target", True
                        break
                    tr.best = max(tr.best, mh) if tr.direction > 0 else min(tr.best, ml)
                    tr.stop = _trail(tr.stop, tr.entry, tr.best, tr.direction,
                                     risk_px0, pip, params)
                if not done and tr.bars_held >= params.time_stop_bars:
                    px = f["close"][i] - tr.direction * SLIPPAGE_PIPS * pip
                    pnl, _, _ = close_slice(px, 1.0, "time")
                    realized += pnl
                    tr.exit, tr.reason, done = px, "time", True
                if realized:
                    balance += realized; equity = balance
                    tr.pnl += realized; day_pnl += realized
                if done:
                    tr.exit_time = t
                    tr.r_multiple = tr.pnl / tr.risk_usd if tr.risk_usd else 0.0
                    closed.append(tr)
                    if tr.pnl < 0:
                        consec_losses += 1
                    elif tr.pnl > 0:
                        consec_losses = 0
                    if consec_losses >= cfg.max_consecutive_losses:
                        day_locked = True
                else:
                    still_open.append(tr)
                continue

            # --- gap handling: an open beyond the stop fills at the open ---
            gapped = (tr.direction > 0 and o <= tr.stop) or (tr.direction < 0 and o >= tr.stop)
            if gapped:
                px = o
                pnl, _, _ = close_slice(px, 1.0, "stop_gap")
                realized += pnl
                tr.exit, tr.reason, done = px, "stop_gap", True
            else:
                # --- TP1 partial ---
                if (not tr.tp1_done) and params.tp1_frac > 0:
                    hit_tp1 = (tr.direction > 0 and hi >= tr.tp1) or \
                              (tr.direction < 0 and lo <= tr.tp1)
                    hit_sl_too = (tr.direction > 0 and lo <= tr.stop) or \
                                 (tr.direction < 0 and hi >= tr.stop)
                    if hit_tp1 and not hit_sl_too:
                        pnl, _, _ = close_slice(tr.tp1, params.tp1_frac, "tp1")
                        realized += pnl
                        tr.lots_closed += tr.lots * params.tp1_frac
                        tr.tp1_done = True
                        if params.breakeven_after_tp1:
                            tr.stop = tr.entry

                remaining = 1.0 - (params.tp1_frac if tr.tp1_done else 0.0)

                hit_sl = (tr.direction > 0 and lo <= tr.stop) or \
                         (tr.direction < 0 and hi >= tr.stop)
                hit_tp = (tr.direction > 0 and hi >= tr.target) or \
                         (tr.direction < 0 and lo <= tr.target)

                if hit_sl:
                    # adverse slippage on the stop; conservative when both hit
                    px = tr.stop - tr.direction * STOP_SLIPPAGE_PIPS * pip
                    trailed = ((tr.stop > tr.stop_initial) if tr.direction > 0
                               else (tr.stop < tr.stop_initial))
                    lbl = "trail_stop" if trailed else (
                        "breakeven" if tr.stop == tr.entry else "stop")
                    pnl, _, _ = close_slice(px, remaining, lbl)
                    realized += pnl
                    tr.exit = px
                    tr.reason = lbl
                    done = True
                elif hit_tp:
                    pnl, _, _ = close_slice(tr.target, remaining, "target")
                    realized += pnl
                    tr.exit, tr.reason, done = tr.target, "target", True
                elif tr.bars_held >= params.time_stop_bars:
                    px = f["close"][i] - tr.direction * SLIPPAGE_PIPS * pip
                    pnl, _, _ = close_slice(px, remaining, "time")
                    realized += pnl
                    tr.exit, tr.reason, done = px, "time", True

            if realized:
                balance += realized
                equity = balance
                tr.pnl += realized
                day_pnl += realized

            if done:
                tr.exit_time = t
                tr.r_multiple = tr.pnl / tr.risk_usd if tr.risk_usd else 0.0
                closed.append(tr)
                if tr.pnl < 0:
                    consec_losses += 1
                elif tr.pnl > 0:
                    consec_losses = 0
                if consec_losses >= cfg.max_consecutive_losses:
                    day_locked = True
            else:
                still_open.append(tr)
        open_trades = still_open

        # daily loss cap
        if day_start_equity > 0 and (day_pnl / day_start_equity) <= -cfg.max_daily_loss:
            day_locked = True

        # -------------------------------------------------------------
        # 2. work the resting orders on THIS bar
        # -------------------------------------------------------------
        # A "retrace" signal rests a limit inside the displacement leg. It
        # fills only if this bar actually trades through the level, is
        # abandoned if the stop level is taken out first, and expires after
        # `entry_expiry` bars. A "market" signal fills at this bar's open.
        fills, carry = [], []
        for od in pending:
            sig = od["sig"]
            s = sig.symbol
            i = pos_of[s].get(t)
            if i is None:
                carry.append(od)
                continue
            if params.entry_mode != "retrace":
                if t >= od["arm_t"]:
                    fills.append((sig, arr[s]["open"][i], "market"))
                else:
                    carry.append(od)
                continue
            if t < od["arm_t"]:
                carry.append(od)
                continue
            od["age"] += 1
            hi_b, lo_b = arr[s]["high"][i], arr[s]["low"][i]
            lim = sig.entry_ref
            touched = (lo_b <= lim) if sig.direction > 0 else (hi_b >= lim)
            invalid = (lo_b <= sig.stop) if sig.direction > 0 else (hi_b >= sig.stop)
            if touched:
                fills.append((sig, lim, "limit"))
            elif invalid or od["age"] >= params.entry_expiry:
                pass                      # cancelled
            else:
                carry.append(od)
        pending = carry

        for sig, fill_px, fill_kind in fills:
            s = sig.symbol
            if day_locked or day_trades >= cfg.max_trades_per_day:
                continue
            if len(open_trades) >= cfg.max_concurrent:
                continue
            if any(o.symbol == s for o in open_trades):
                continue
            # currency exposure cap
            legs = [BASE[s], QUOTE[s]]
            exposure = 0
            for o in open_trades:
                o_legs = [BASE[o.symbol], QUOTE[o.symbol]]
                for cur in legs:
                    if cur in o_legs:
                        exposure += 1
                        break
            if exposure >= cfg.max_per_currency:
                continue

            i = pos_of[s].get(t)
            if i is None:
                continue
            pip = PIP[s]
            spread = SPREAD_PIPS[s] * pip

            # cross the spread + adverse slippage, off the actual fill level
            entry = fill_px + sig.direction * (spread / 2 + SLIPPAGE_PIPS * pip)
            stop = sig.stop
            risk_px = abs(entry - stop)
            if risk_px <= 0:
                continue
            # re-price targets off the ACTUAL fill, keeping planned R
            target = entry + sig.direction * params.tp_r * risk_px
            tp1 = entry + sig.direction * params.tp1_r * risk_px

            unit_usd = CONTRACT[s] * q2usd[s][i]
            risk_pct = cfg.risk_pct_gold if s == "XAUUSD" else cfg.risk_pct
            risk_usd_target = equity * risk_pct
            lots = round_lots(risk_usd_target / (risk_px * unit_usd), cfg)
            if lots < cfg.min_lot:
                continue

            risk_usd = risk_px * unit_usd * lots
            # never let rounding push risk materially past the budget
            if risk_usd > risk_usd_target * 1.5:
                continue

            tr = Trade(symbol=s, direction=sig.direction, entry_time=t, entry=entry,
                       stop=stop, target=target, tp1=tp1, lots=lots,
                       risk_usd=risk_usd, score=sig.score, planned_rr=sig.rr,
                       parts=dict(sig.parts))
            tr.stop_initial = stop
            tr.tp1_done = False
            tr.lots_closed = 0.0
            tr.best = entry
            tr._m1_ts = None
            # entry-side commission
            entry_comm = COMMISSION_PER_LOT * lots * 0.5
            balance -= entry_comm
            equity = balance
            tr.pnl -= entry_comm
            day_pnl -= entry_comm

            # Same rule as the signal simulator: the fill bar may resolve the
            # STOP but never the target, because the intrabar order after a
            # mid-bar limit fill is unknowable from OHLC.
            hi_f, lo_f = arr[s]["high"][i], arr[s]["low"][i]
            stopped_on_fill = (lo_f <= stop) if sig.direction > 0 else (hi_f >= stop)
            if stopped_on_fill:
                px = stop - sig.direction * STOP_SLIPPAGE_PIPS * pip
                unit_usd_f = CONTRACT[s] * q2usd[s][i]
                gross = (px - entry) * sig.direction * unit_usd_f * lots
                exit_comm = COMMISSION_PER_LOT * lots * 0.5
                realized_f = gross - exit_comm
                balance += realized_f
                equity = balance
                tr.pnl += realized_f
                day_pnl += realized_f
                tr.exit, tr.reason, tr.exit_time = px, "stop", t
                tr.bars_held = 1
                tr.mae_r = -1.0
                tr.r_multiple = tr.pnl / tr.risk_usd if tr.risk_usd else 0.0
                closed.append(tr)
                consec_losses += 1
                if consec_losses >= cfg.max_consecutive_losses:
                    day_locked = True
                day_trades += 1
                continue

            open_trades.append(tr)
            day_trades += 1

        # -------------------------------------------------------------
        # 3. scan for new signals on bars that just closed
        # -------------------------------------------------------------
        if not day_locked and day_trades < cfg.max_trades_per_day:
            for s in symbols:
                i = pos_of[s].get(t)
                if i is None:
                    continue
                if i + 1 >= len(bar_index[s]):
                    continue
                if any(o.symbol == s for o in open_trades):
                    continue
                if any(od["sig"].symbol == s for od in pending):
                    continue
                sig = st.evaluate(ctxs[s], i)
                if sig is not None:
                    pending.append({"sig": sig, "arm_t": bar_index[s][i + 1], "age": 0})

        equity_curve.append((t, balance))

    return closed, pd.DataFrame(equity_curve, columns=["time", "equity"]).set_index("time")
