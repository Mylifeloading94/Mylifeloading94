"""
XAUUSD momentum-continuation scalper.

WHAT THE DATA SAID (train window 2024-01-01 .. 2026-05-22, M1 barrier scan)
    Fading extremes LOSES on gold: RSI<=25 -> long won 40.3% (-0.34R).
    Buying strength WINS: RSI>=75 -> long won 75.0% (+0.22R).
    The effect is symmetric -- shorts on weakness pay about as well as longs on
    strength -- so it is not the 2024-26 gold uptrend leaking in. It held in all
    10 training quarters on both sides.

THE SETUP
    Signal timeframe M5, execution and barrier resolution on M1.
    LONG  : 5-bar thrust >= +1.5 ATR, RSI(14) >= 75, price in top 15% of the
            40-bar range.
    SHORT : mirror image.
    Both sides required -- this is not a long-only bull-market bot.

Conventions: 1 pip = $0.10, contract 100 oz, so $1.00 = $100 per standard lot.
A 25-pip target is $2.50 and a 40-pip stop is $4.00.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

import features as ft

PIP = 0.10
CONTRACT = 100.0                 # oz per standard lot
SPREAD_PIPS = 3.0                # $0.30, conservative for gold
SLIP_PIPS = 0.5                  # adverse, on entry
STOP_SLIP_PIPS = 1.0             # extra adverse when a stop triggers
COMMISSION_PER_LOT = 7.0         # USD round turn


@dataclass
class ScalpParams:
    # --- signal ---
    thrust_atr: float = 1.5      # 5-bar move, in ATR
    rsi_long: float = 75.0
    rsi_short: float = 25.0
    range_edge: float = 0.15     # top/bottom fraction of the 40-bar range
    atr_period: int = 14

    # --- exits (pips) ---
    tp_pips: float = 25.0
    sl_pips: float = 40.0
    max_hold_bars_m1: int = 240  # 4 hours

    # --- filters ---
    min_atr: float = 1.0         # $ — skip dead tape
    max_atr: float = 40.0        # $ — skip disorderly tape
    sessions: tuple = ((0, 21),) # UTC; excludes the 21:00-24:00 rollover window

    # --- trade management ---
    cooldown_bars_m5: int = 3    # bars to wait after an exit before re-arming
    max_trades_per_day: int = 6
    one_at_a_time: bool = True


def default_params():
    return ScalpParams()


def signals(m5, p: ScalpParams):
    """+1 long, -1 short, 0 none — per M5 bar, using bars <= i only."""
    F = ft.build(m5)
    long_c = ((F.ret5 >= p.thrust_atr) & (F.rsi >= p.rsi_long)
              & (F.range_pos >= 1 - p.range_edge))
    short_c = ((F.ret5 <= -p.thrust_atr) & (F.rsi <= p.rsi_short)
               & (F.range_pos <= p.range_edge))

    ok = F.atr.between(p.min_atr, p.max_atr) & F.atr.notna() & F.range_pos.notna()
    hour = m5.index.hour
    in_sess = np.zeros(len(m5), dtype=bool)
    for a, b in p.sessions:
        in_sess |= (hour >= a) & (hour < b)

    sig = np.where(long_c & ok & in_sess, 1,
                   np.where(short_c & ok & in_sess, -1, 0))
    return sig.astype(np.int8), F


def backtest(m1, m5, p: ScalpParams, start, end, balance=10_000.0,
             risk_pct=0.01, max_daily_loss=0.04, verbose=False):
    """Sequential scalper backtest.

    One position at a time by default, so overlapping signals inside a single
    thrust collapse into ONE trade rather than being counted five times.
    Barriers are resolved on M1 bars; a bar spanning both resolves as a stop.
    """
    sig, F = signals(m5, p)
    m5_idx = m5.index
    m1_idx = m1.index
    m1_o = m1["open"].values.astype(float)
    m1_h = m1["high"].values.astype(float)
    m1_l = m1["low"].values.astype(float)
    m1_ts = m1_idx.values

    # position of each M5 bar's CLOSE inside the M1 array
    m5_close_pos = np.searchsorted(
        m1_ts, (m5_idx + pd.Timedelta(minutes=5)).values, "left")

    lo = int(np.searchsorted(m5_idx.values,
                             np.datetime64(pd.Timestamp(start).tz_localize(None)
                                           if pd.Timestamp(start).tzinfo is None
                                           else pd.Timestamp(start).tz_convert("UTC").tz_localize(None)), "left"))
    hi = int(np.searchsorted(m5_idx.values,
                             np.datetime64(pd.Timestamp(end).tz_convert("UTC").tz_localize(None)), "right"))

    tp_px = p.tp_pips * PIP
    sl_px = p.sl_pips * PIP
    entry_cost = (SPREAD_PIPS / 2 + SLIP_PIPS) * PIP

    trades = []
    equity_pts = []
    busy_until_m1 = -1
    cooldown_until = -1
    day = None
    day_pnl = 0.0
    day_trades = 0
    day_start_bal = balance

    for i in range(lo, min(hi, len(m5_idx) - 1)):
        ts = m5_idx[i]
        d = ts.date()
        if d != day:
            day, day_pnl, day_trades, day_start_bal = d, 0.0, 0, balance

        if sig[i] == 0 or i <= cooldown_until:
            continue
        if day_trades >= p.max_trades_per_day:
            continue
        if day_start_bal > 0 and day_pnl / day_start_bal <= -max_daily_loss:
            continue

        fill_pos = m5_close_pos[i]
        if fill_pos >= len(m1_o) - 2:
            continue
        if p.one_at_a_time and fill_pos < busy_until_m1:
            continue

        direction = int(sig[i])
        entry = m1_o[fill_pos] + direction * entry_cost
        stop = entry - direction * sl_px
        target = entry + direction * tp_px

        # position size from the % risk and the stop distance
        risk_usd = balance * risk_pct
        lots = risk_usd / (sl_px * CONTRACT)
        lots = max(0.01, np.floor(lots * 100) / 100)

        # --- resolve on M1 ---
        end_pos = min(len(m1_o), fill_pos + p.max_hold_bars_m1)
        exit_px, reason, exit_pos = None, "time", end_pos - 1
        for k in range(fill_pos, end_pos):
            h_, l_ = m1_h[k], m1_l[k]
            hit_sl = (l_ <= stop) if direction > 0 else (h_ >= stop)
            hit_tp = (h_ >= target) if direction > 0 else (l_ <= target)
            if hit_sl:                       # ambiguity resolves against us
                exit_px = stop - direction * STOP_SLIP_PIPS * PIP
                reason, exit_pos = "stop", k
                break
            if hit_tp:
                exit_px, reason, exit_pos = target, "target", k
                break
        if exit_px is None:
            exit_px = m1_o[end_pos - 1] - direction * SLIP_PIPS * PIP
            exit_pos = end_pos - 1

        gross = (exit_px - entry) * direction * CONTRACT * lots
        comm = COMMISSION_PER_LOT * lots
        pnl = gross - comm

        balance += pnl
        day_pnl += pnl
        day_trades += 1
        busy_until_m1 = exit_pos + 1
        cooldown_until = i + p.cooldown_bars_m5

        trades.append(dict(
            time=ts, entry_time=m1_idx[fill_pos], exit_time=m1_idx[exit_pos],
            direction=direction, entry=entry, stop=stop, target=target,
            exit=exit_px, lots=round(lots, 2), pnl=pnl, reason=reason,
            hold_min=int(exit_pos - fill_pos), balance=balance,
            r=pnl / risk_usd if risk_usd else 0.0))
        equity_pts.append((m1_idx[exit_pos], balance))

    eq = pd.DataFrame(equity_pts, columns=["time", "equity"]).set_index("time")
    return pd.DataFrame(trades), eq
