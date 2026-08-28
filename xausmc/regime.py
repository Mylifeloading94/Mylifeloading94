"""Market regime + volatility classification for XAUUSD."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .candles import Bar, atr_series
from .smc import Structure


@dataclass
class Regime:
    state: str = "UNKNOWN"        # TRENDING | RANGING | VOLATILE | UNKNOWN
    efficiency: float = 0.0       # 0..1 directional efficiency of the last leg
    atr_value: float = 0.0
    atr_pctile: float = 0.0       # where current ATR sits in its own 200-bar history
    volatility: str = "NORMAL"    # DEAD | NORMAL | ELEVATED | EXTREME
    tradeable: bool = False
    note: str = ""

    @property
    def suitable(self) -> bool:
        return self.tradeable


def directional_efficiency(bars: Sequence[Bar]) -> float:
    """|net move| / total path. 1.0 = a straight line, ~0 = pure chop."""
    if len(bars) < 3:
        return 0.0
    net = abs(bars[-1].c - bars[0].c)
    path = sum(abs(bars[i].c - bars[i - 1].c) for i in range(1, len(bars)))
    return net / path if path > 0 else 0.0


def classify(bars: Sequence[Bar], structure: Structure, window: int = 40) -> Regime:
    if len(bars) < 60:
        return Regime(note="not enough bars to classify regime")
    full = atr_series(bars, 14)
    a_hist = [x for x in full[-200:] if x > 0]
    a_now = full[-1] if full else 0.0
    if not a_hist or a_now <= 0:
        return Regime(note="ATR unavailable")

    below = sum(1 for x in a_hist if x <= a_now)
    pct = below / len(a_hist)
    eff = directional_efficiency(bars[-window:])

    if pct >= 0.95:
        vol = "EXTREME"
    elif pct >= 0.80:
        vol = "ELEVATED"
    elif pct <= 0.12:
        vol = "DEAD"
    else:
        vol = "NORMAL"

    if vol == "EXTREME":
        state = "VOLATILE"
    elif eff >= 0.32 and structure.trend in ("bullish", "bearish"):
        state = "TRENDING"
    elif eff <= 0.16:
        state = "RANGING"
    else:
        state = "TRENDING" if structure.trend in ("bullish", "bearish") else "RANGING"

    tradeable, note = True, ""
    if vol == "DEAD":
        tradeable, note = False, "volatility in bottom 12% of its own range — spreads dominate the move"
    elif vol == "EXTREME":
        tradeable, note = False, "volatility in top 5% — stop placement unreliable (news/spike regime)"

    return Regime(state=state, efficiency=round(eff, 3), atr_value=a_now,
                  atr_pctile=round(pct, 3), volatility=vol, tradeable=tradeable, note=note)
