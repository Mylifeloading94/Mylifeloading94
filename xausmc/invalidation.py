"""
Automatic setup invalidation (spec §12).

Every 60-second scan re-runs these checks against fresh data. The moment a
condition fails the setup is marked INVALID with the specific reason. An old
signal is never left standing as valid.
"""
from __future__ import annotations

from dataclasses import dataclass

from .candles import to_pips
from .config import MODES, StrategyConfig
from .setups import Context, Setup
from .smc import PremiumDiscount


@dataclass
class Verdict:
    valid: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.valid


VALID = Verdict(True)


def revalidate(setup: Setup, ctx: Context, cfg: StrategyConfig, price: float,
               high_since: float | None = None, low_since: float | None = None) -> Verdict:
    """
    Re-check a previously published setup against the current market.
    `high_since` / `low_since` are the extremes traded since the setup was
    published — supplied by the journal so wicks are not missed between scans.
    """
    mode = MODES[setup.mode]
    hi = max(price, high_since if high_since is not None else price)
    lo = min(price, low_since if low_since is not None else price)
    buy = setup.direction == "BUY"

    # 1. Stop loss taken out
    if (buy and lo <= setup.sl) or (not buy and hi >= setup.sl):
        return Verdict(False, "STOP LOSS HIT — setup closed as a loss")

    # 2. Target already reached: the setup has done its job, it is not re-entered
    if (buy and hi >= setup.tp1) or (not buy and lo <= setup.tp1):
        if setup.entry_state == "PENDING":
            return Verdict(False, "TP1 reached before the entry zone filled — opportunity missed")

    # 3. Price moved beyond the entry zone without filling (limit setups only)
    if setup.entry_state == "PENDING":
        a = ctx.ltf.atr or 1.0
        if buy and price < setup.entry_low - 1.5 * a:
            return Verdict(False, "price traded clean through the entry zone — zone no longer valid")
        if not buy and price > setup.entry_high + 1.5 * a:
            return Verdict(False, "price traded clean through the entry zone — zone no longer valid")

    # 4. Higher-timeframe bias reversed against the trade
    bias = ctx.htf_bias
    want = "bullish" if buy else "bearish"
    if bias not in (want, "ranging", "conflicted"):
        return Verdict(False, f"HTF bias reversed to {bias.upper()} — directional premise gone")

    # 5. The confirming structure break failed (structure re-broke the other way)
    ltf_trend = ctx.ltf.structure.trend
    last = ctx.ltf.structure.last_event
    if last is not None and last.ts > setup.signal_ts and last.direction != want and last.kind == "BOS":
        return Verdict(False, f"{setup.anchors.get('mss', {}).get('kind', 'MSS')} failed — "
                              f"opposing BOS printed on {mode.ltf}")
    if ltf_trend not in (want, "ranging") and setup.entry_state == "PENDING":
        return Verdict(False, f"execution-TF structure flipped to {ltf_trend.upper()} before entry")

    # 6. Liquidity condition changed: the swept pool was reclaimed
    sweep = setup.anchors.get("sweep", {})
    pool_px = sweep.get("pool_price")
    if pool_px is not None:
        if buy and price < pool_px - 0.5 * (ctx.ltf.atr or 0.0):
            return Verdict(False, "liquidity reclaimed — price closed back below the swept pool")
        if not buy and price > pool_px + 0.5 * (ctx.ltf.atr or 0.0):
            return Verdict(False, "liquidity reclaimed — price closed back above the swept pool")

    # 7. The FVG that justified the entry has been fully mitigated without a fill
    if setup.entry_state == "PENDING" and setup.anchors.get("poi", {}).get("kind") == "FVG":
        top = setup.anchors["poi"]["top"]
        bottom = setup.anchors["poi"]["bottom"]
        if buy and lo < bottom and price < bottom:
            return Verdict(False, "FVG fully invalidated — price closed below the imbalance")
        if not buy and hi > top and price > top:
            return Verdict(False, "FVG fully invalidated — price closed above the imbalance")

    # 8. R:R decayed below the mode minimum (chasing an unfilled limit)
    risk = abs(setup.entry - setup.sl)
    if risk > 0:
        live_entry = price if setup.entry_state == "ARMED" else setup.entry
        live_risk = abs(live_entry - setup.sl)
        if live_risk > 0:
            live_rr = abs(setup.tp2 - live_entry) / live_risk
            if live_rr < mode.min_rr:
                return Verdict(False, f"risk/reward decayed to {live_rr:.2f}, "
                                      f"below the {mode.name} minimum {mode.min_rr}")

    # 9. Volatility regime became unsuitable
    if not ctx.ltf.regime.tradeable:
        return Verdict(False, f"market volatility unsuitable ({ctx.ltf.regime.volatility}) — "
                              f"{ctx.ltf.regime.note}")

    # 10. Sequence aged out
    bars_old = max(0, (ctx.ts - setup.signal_ts) // (60 * {"M1": 1, "M5": 5, "M15": 15,
                                                          "H1": 60, "H4": 240}[mode.ltf]))
    if setup.entry_state == "PENDING" and bars_old > mode.max_age_bars * 3:
        return Verdict(False, f"setup expired — {bars_old} {mode.ltf} bars without a fill")

    return VALID
