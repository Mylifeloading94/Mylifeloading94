"""
Trade chart for the Telegram alert.

Uses the repo's LOCKED-IN chart style (see the tradelocker skill: light-blue
bull bodies, light-pink bear bodies, black wicks, blue price scale, and the
TradingView-style position box on the right).

matplotlib is optional — when it is not installed the bot simply sends a
text-only alert instead of failing.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

log = logging.getLogger("xauusd_smc.chart")

BG = "white"
BULL_BODY = "#90bff9"
BEAR_BODY = "#f48fb1"
WICK = "black"
SCALE_BLUE = "#0000ff"
PROFIT_BLUE = "#2962ff"
LOSS_RED = "#f23645"
GRID = "#e0e0e0"


def available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def render(bars: List[dict], label: str, entry: float, sl: float, tp1: float,
           tp2: float, direction: str, path: str) -> Optional[str]:
    """Render the last ~60 bars with entry/SL/TP levels. Returns path or None."""
    if not available() or not bars:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle

        w = bars[-60:]
        n = len(w)
        fig, ax = plt.subplots(figsize=(10, 6), facecolor=BG)
        ax.set_facecolor(BG)

        for i, b in enumerate(w):
            up = b["c"] >= b["o"]
            ax.plot([i, i], [b["l"], b["h"]], color=WICK, linewidth=0.7, zorder=2)
            bottom = min(b["o"], b["c"])
            height = max(abs(b["c"] - b["o"]), 1e-6)
            ax.add_patch(Rectangle((i - 0.3, bottom), 0.6, height,
                                   facecolor=BULL_BODY if up else BEAR_BODY,
                                   edgecolor="black", linewidth=0.5, zorder=3))

        for level, style, name in ((entry, "-", "Entry"), (sl, "--", "SL"),
                                   (tp1, ":", "TP1"), (tp2, "--", "TP2")):
            ax.axhline(level, color="black", linestyle=style, linewidth=0.9, zorder=4)
            ax.text(-0.5, level, f" {name} {level:.2f}", va="center", ha="right",
                    fontsize=8, color="black")

        box_x = n - 0.5
        box_w = max(n * 0.13, 1.0)
        long = direction == "bullish"
        top_zone = (entry, tp2 - entry) if long else (entry, sl - entry)
        bot_zone = (sl, entry - sl) if long else (tp2, entry - tp2)
        for (y0, h), col in ((top_zone, PROFIT_BLUE if long else LOSS_RED),
                             (bot_zone, LOSS_RED if long else PROFIT_BLUE)):
            ax.add_patch(Rectangle((box_x, y0), box_w, h, facecolor=col,
                                   edgecolor=col, alpha=0.25, zorder=1))
        ax.plot([box_x, box_x + box_w], [tp1, tp1], color=PROFIT_BLUE,
                alpha=0.7, linewidth=1.0, zorder=4)

        ax.set_title("")
        ax.text(0.01, 0.97, label, transform=ax.transAxes, ha="left", va="top",
                fontsize=13, fontweight="bold", color="black")
        ax.text(0.99, 0.97, "▲  LONG" if long else "▼  SHORT",
                transform=ax.transAxes, ha="right", va="top", fontsize=11,
                fontweight="bold", color=PROFIT_BLUE if long else LOSS_RED)

        ax.grid(axis="y", color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", colors=SCALE_BLUE, labelsize=8)
        ax.tick_params(axis="x", bottom=False, labelbottom=False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xlim(-0.5 - n * 0.12, box_x + box_w * 2.2)

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fig.tight_layout()
        fig.savefig(path, dpi=110, facecolor=BG)
        plt.close(fig)
        return path
    except Exception as e:                      # charting must never block a trade
        log.warning("chart render failed: %s", e)
        return None
