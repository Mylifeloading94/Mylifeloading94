"""Adaptive layer -- analysis only.

Reports which pair / session / setup-type / liquidity-type / R:R / volatility
combinations carry the strongest expectancy, and flags the ones with enough
trades to be worth believing.

Two hard constraints, both from the spec:

* It **can never override a risk limit** (``adaptive.can_override_risk`` is
  false and :meth:`recommendations` refuses to emit risk changes).
* It **requires a statistically meaningful sample** before suggesting
  anything; groups below ``min_trades_for_significance`` are reported but
  explicitly marked ``insufficient_sample``.

This layer suggests. It does not act.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import bootstrap_ci, compute_metrics


def _rr_bucket(value: float) -> str:
    if value < 2:
        return "<2R"
    if value < 3:
        return "2-3R"
    if value < 4:
        return "3-4R"
    return "4R+"


def enrich(trades: pd.DataFrame) -> pd.DataFrame:
    """Add the derived dimensions the adaptive layer analyses."""
    if trades is None or trades.empty:
        return trades
    frame = trades.copy()
    frame["rr_bucket"] = frame["rr_tp2"].apply(_rr_bucket)
    if "atr" not in frame and "risk_price" in frame:
        pass
    # Volatility regime from the trade's own risk distance vs its pair median.
    med = frame.groupby("symbol")["risk_price"].transform("median")
    ratio = frame["risk_price"] / med.replace(0, np.nan)
    frame["volatility_regime"] = pd.cut(
        ratio, [-np.inf, 0.8, 1.25, np.inf],
        labels=["low", "normal", "high"]).astype(str)
    frame["direction_label"] = frame["direction"].map(
        {"bullish": "long", "bearish": "short"}).fillna("unknown")
    return frame


def analyse(trades: pd.DataFrame, cfg, starting_balance: float = 10000.0) -> dict:
    """Per-dimension expectancy tables with significance flags."""
    acfg = cfg.get("adaptive", {}) or {}
    min_n = int(acfg.get("min_trades_for_significance", 30))
    dims = list(acfg.get("dimensions", []))
    frame = enrich(trades)
    out: dict[str, pd.DataFrame] = {}
    if frame is None or frame.empty:
        return out

    name_map = {"pair": "symbol"}
    for dim in dims + ["direction_label"]:
        col = name_map.get(dim, dim)
        if col not in frame:
            continue
        rows = []
        for key, group in frame.groupby(col):
            m = compute_metrics(group, starting_balance)
            lo, hi = bootstrap_ci(group["r_multiple"].values, "mean", 2000)
            rows.append({
                dim: key, "trades": m["trades"],
                "win_rate": round(m["win_rate"], 2),
                "profit_factor": round(m["profit_factor"], 3),
                "expectancy_r": round(m["expectancy_r"], 4),
                "exp_ci_low": round(lo, 4), "exp_ci_high": round(hi, 4),
                "total_r": round(m["total_r"], 2),
                "significant": "yes" if m["trades"] >= min_n else "insufficient_sample",
            })
        out[dim] = pd.DataFrame(rows).sort_values(
            "expectancy_r", ascending=False).reset_index(drop=True)
    return out


def recommendations(tables: dict, cfg) -> list[str]:
    """Plain-English suggestions. Never touches risk settings."""
    acfg = cfg.get("adaptive", {}) or {}
    min_n = int(acfg.get("min_trades_for_significance", 30))
    notes: list[str] = []
    if acfg.get("can_override_risk", False):
        notes.append("REFUSED: adaptive layer is not permitted to change risk limits.")

    for dim, table in tables.items():
        if table.empty:
            continue
        strong = table[(table["trades"] >= min_n) & (table["exp_ci_low"] > 0)]
        weak = table[(table["trades"] >= min_n) & (table["exp_ci_high"] < 0)]
        for _, row in strong.iterrows():
            notes.append(
                f"{dim}={row[dim]}: positive expectancy {row['expectancy_r']:+.3f}R "
                f"with the whole 95% CI above zero (n={row['trades']}). Worth keeping.")
        for _, row in weak.iterrows():
            notes.append(
                f"{dim}={row[dim]}: negative expectancy {row['expectancy_r']:+.3f}R "
                f"with the whole 95% CI below zero (n={row['trades']}). Candidate to drop.")
    if not notes:
        notes.append("No dimension reached the significance threshold "
                     f"(n>={min_n}) with a CI clear of zero. No changes suggested.")
    return notes
