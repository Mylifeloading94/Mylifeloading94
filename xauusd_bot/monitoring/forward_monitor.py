"""
Forward performance monitor (spec section 52). Compares live rolling windows
against backtest expectations and escalates WARNING -> PAUSE.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Expectation:
    win_rate: float
    profit_factor: float
    expectancy_r: float


@dataclass
class ForwardMonitor:
    expected: Expectation
    warn_expectancy_gap: float = 0.15      # R below expectation -> WARNING
    pause_expectancy_gap: float = 0.30     # R below expectation -> PAUSE
    min_trades: int = 20
    r_history: list = field(default_factory=list)

    def add(self, r_multiple: float) -> None:
        self.r_history.append(float(r_multiple))

    def window(self, n: int) -> dict:
        r = np.array(self.r_history[-n:])
        if len(r) == 0:
            return {"n": 0}
        gains, losses = r[r > 0].sum(), -r[r < 0].sum()
        return {"n": len(r), "win_rate": 100 * (r > 0).mean(),
                "profit_factor": float(gains / losses) if losses > 0 else float("inf"),
                "expectancy_r": float(r.mean()),
                "max_dd_r": float(self._max_dd(r))}

    @staticmethod
    def _max_dd(r: np.ndarray) -> float:
        eq = np.cumsum(r)
        peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
        return float((peak - eq).max()) if len(eq) else 0.0

    def status(self) -> tuple[str, str]:
        w = self.window(max(self.min_trades, 20))
        if w["n"] < self.min_trades:
            return "COLLECTING", f"{w['n']}/{self.min_trades} trades"
        gap = self.expected.expectancy_r - w["expectancy_r"]
        if gap >= self.pause_expectancy_gap:
            return "PAUSE", (f"expectancy {w['expectancy_r']:+.3f}R vs expected "
                             f"{self.expected.expectancy_r:+.3f}R (gap {gap:.3f}R)")
        if gap >= self.warn_expectancy_gap:
            return "WARNING", (f"expectancy {w['expectancy_r']:+.3f}R vs expected "
                               f"{self.expected.expectancy_r:+.3f}R (gap {gap:.3f}R)")
        return "OK", f"expectancy {w['expectancy_r']:+.3f}R over {w['n']} trades"

    def report(self) -> str:
        lines = ["FORWARD PERFORMANCE MONITOR"]
        for n in (20, 50, 100):
            w = self.window(n)
            if w["n"]:
                lines.append(f"  last {n:3d}: n={w['n']:3d} win={w['win_rate']:5.1f}% "
                             f"PF={min(w['profit_factor'], 99):5.2f} "
                             f"expR={w['expectancy_r']:+.3f} maxDD={w['max_dd_r']:.2f}R")
        s, why = self.status()
        lines.append(f"  STATUS: {s} - {why}")
        return "\n".join(lines)
