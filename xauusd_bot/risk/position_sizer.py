"""
Position sizing. Lot size is DERIVED from risk, never hard-coded.

Returns a SizingResult that explicitly says when the broker's minimum lot makes
the requested risk impossible - which is the normal case for a small account on
XAUUSD, and must not be silently rounded away.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from xauusd_bot.config import Config


@dataclass
class SizingResult:
    lots: float
    risk_money: float
    risk_percent_actual: float
    ok: bool
    reason: str = ""


def size_position(equity: float, entry: float, stop: float, cfg: Config,
                  risk_percent: float | None = None) -> SizingResult:
    ins = cfg.instrument
    rp = cfg.risk.risk_percent if risk_percent is None else risk_percent
    risk_money = equity * rp / 100.0
    sl_distance = abs(entry - stop)
    if sl_distance <= 0:
        return SizingResult(0.0, 0.0, 0.0, False, "invalid stop distance")

    money_per_lot = sl_distance * ins.contract_size          # $ lost per 1.00 lot
    raw_lots = risk_money / money_per_lot
    lots = math.floor(raw_lots / ins.lot_step) * ins.lot_step
    lots = round(lots, 8)

    if lots < ins.min_lot:
        min_risk_money = ins.min_lot * money_per_lot
        min_risk_pct = 100.0 * min_risk_money / equity
        if cfg.risk.allow_min_lot_override and min_risk_pct <= cfg.risk.max_risk_percent_hard_cap:
            return SizingResult(ins.min_lot, min_risk_money, min_risk_pct, True,
                                f"min lot override ({min_risk_pct:.2f}% risk)")
        return SizingResult(0.0, 0.0, min_risk_pct, False,
                            f"min lot {ins.min_lot} would risk {min_risk_pct:.2f}% "
                            f"(> {rp:.2f}% target)")
    if lots > ins.max_lot:
        lots = ins.max_lot
    actual_money = lots * money_per_lot
    actual_pct = 100.0 * actual_money / equity
    if actual_pct > cfg.risk.max_risk_percent_hard_cap:
        return SizingResult(0.0, 0.0, actual_pct, False, "exceeds hard risk cap")
    return SizingResult(lots, actual_money, actual_pct, True)
