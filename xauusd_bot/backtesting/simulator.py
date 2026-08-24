"""
Execution simulation: spread, commission, slippage and intrabar fill logic.

Fill philosophy - always the pessimistic branch:
  * Entries are MARKET orders filled at the NEXT M1 bar's open, plus half the
    spread against us, plus slippage. Never at the signal bar's close.
  * If a bar's range contains BOTH the stop and the target, the STOP is
    assumed to fill first. Bar data cannot tell us the path, so we take the
    bad one.
  * Stops fill at the stop price plus stop slippage against us (gaps fill at
    the bar open when the bar gaps through the stop).
  * Targets fill at the target price exactly (limit orders get no positive
    slippage).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from xauusd_bot.config import Config


def spread_series(F: pd.DataFrame, cfg: Config) -> pd.Series:
    """Modelled bid/ask spread in price units. HistData M1 has no spread
    column, so we model it: a session base, widened proportionally to
    short-term realised volatility relative to its own median."""
    c = cfg.costs
    base = F["session"].map(c.spread_by_session).astype(float).fillna(c.base_spread)
    atr = F["M5_atr"].ffill()
    med = atr.rolling(2000, min_periods=100).median()
    vol_ratio = (atr / med).clip(0.5, 4.0).fillna(1.0)
    sp = base * (1.0 + c.spread_vol_coef * (vol_ratio - 1.0))
    return sp.clip(lower=0.10, upper=5.0)


@dataclass
class Fill:
    price: float
    slippage: float
    kind: str


def entry_fill(next_open: float, direction: int, spread: float, cfg: Config) -> Fill:
    half = spread / 2.0
    slip = cfg.costs.entry_slippage
    px = next_open + direction * (half + slip)
    return Fill(px, slip, "entry")


def exit_fill_stop(bar: dict, stop: float, direction: int, spread: float,
                   cfg: Config, news: bool = False) -> Fill:
    """Stop-out price including gap handling."""
    slip = cfg.costs.stop_slippage_news if news else cfg.costs.stop_slippage
    half = spread / 2.0
    if direction > 0:
        gapped = bar["open"] < stop
        base = bar["open"] if gapped else stop
        px = base - slip - half
    else:
        gapped = bar["open"] > stop
        base = bar["open"] if gapped else stop
        px = base + slip + half
    return Fill(px, slip + (abs(base - stop)), "stop_gap" if gapped else "stop")


def exit_fill_limit(target: float, direction: int, spread: float, cfg: Config) -> Fill:
    half = spread / 2.0
    px = target - direction * half
    return Fill(px, 0.0, "target")


def exit_fill_market(bar_open: float, direction: int, spread: float, cfg: Config) -> Fill:
    half = spread / 2.0
    slip = cfg.costs.entry_slippage
    px = bar_open - direction * (half + slip)
    return Fill(px, slip, "market")


def commission(lots: float, cfg: Config) -> float:
    return lots * cfg.costs.commission_per_lot_round_turn
