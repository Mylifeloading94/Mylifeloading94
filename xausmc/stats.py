"""
Validated-performance store (spec §9).

The probability a setup displays is NEVER a guess and never a hand-picked
number. It is the measured win rate of the same configuration
(pattern x mode x grade x direction) in the backtest / journal, and it is
always displayed next to its sample size.

When a configuration has fewer than `min_sample` observations, the engine
reports `INSUFFICIENT SAMPLE` and shows the count. It does not fall back to a
flattering number.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

BUCKET_LEVELS = [
    ("pattern+mode+grade+dir", lambda t: f"{t['pattern']}|{t['mode']}|{t['grade']}|{t['direction']}"),
    ("pattern+mode+grade", lambda t: f"{t['pattern']}|{t['mode']}|{t['grade']}"),
    ("pattern+grade", lambda t: f"{t['pattern']}|*|{t['grade']}"),
    ("mode+grade", lambda t: f"*|{t['mode']}|{t['grade']}"),
    ("grade", lambda t: f"*|*|{t['grade']}"),
    ("all", lambda t: "ALL"),
]
# Extra descriptive breakdowns required by spec §9/§15 (not used for lookup).
BREAKDOWNS = {
    "by_session": lambda t: f"session:{t.get('session', 'UNKNOWN')}",
    "by_mode": lambda t: f"mode:{t['mode']}",
    "by_pattern": lambda t: f"pattern:{t['pattern']}",
    "by_direction": lambda t: f"direction:{t['direction']}",
    "by_grade": lambda t: f"grade:{t['grade']}",
    "by_timeframe": lambda t: f"tf:{t.get('exec_tf', '?')}",
}


@dataclass
class Bucket:
    key: str = ""
    n: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float = 0.0
    avg_rr: float = 0.0          # realised average R multiple per trade (expectancy)
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    target_rr: float = 0.0       # planned R:R of these setups
    profit_factor: float = 0.0
    expectancy_r: float = 0.0
    max_drawdown_r: float = 0.0
    total_r: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def compute_bucket(key: str, trades: list[dict]) -> Bucket:
    b = Bucket(key=key, n=len(trades))
    if not trades:
        return b
    rs = [float(t.get("r_multiple", 0.0)) for t in trades]
    b.wins = sum(1 for r in rs if r > 0.02)
    b.losses = sum(1 for r in rs if r < -0.02)
    b.breakeven = b.n - b.wins - b.losses
    decided = b.wins + b.losses
    b.win_rate = round(100.0 * b.wins / decided, 1) if decided else 0.0
    gains = sum(r for r in rs if r > 0)
    pains = -sum(r for r in rs if r < 0)
    b.profit_factor = round(gains / pains, 2) if pains > 0 else (float("inf") if gains > 0 else 0.0)
    b.total_r = round(sum(rs), 2)
    b.avg_rr = round(sum(rs) / b.n, 3)
    b.expectancy_r = b.avg_rr
    b.avg_win_r = round(gains / b.wins, 2) if b.wins else 0.0
    b.avg_loss_r = round(-pains / b.losses, 2) if b.losses else 0.0
    tr = [float(t.get("target_rr", 0.0)) for t in trades if t.get("target_rr")]
    b.target_rr = round(sum(tr) / len(tr), 2) if tr else 0.0
    peak = eq = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    b.max_drawdown_r = round(dd, 2)
    return b


@dataclass
class ProbabilityEstimate:
    win_rate: float | None = None
    sample_size: int = 0
    profit_factor: float | None = None
    avg_rr: float | None = None
    expectancy_r: float | None = None
    bucket: str = ""
    level: str = ""
    sufficient: bool = False
    note: str = "no validated sample"

    @property
    def display(self) -> str:
        if not self.sufficient or self.win_rate is None:
            return f"INSUFFICIENT SAMPLE (n={self.sample_size})"
        return f"{self.win_rate:.1f}% (n={self.sample_size})"


@dataclass
class StatsStore:
    """Buckets built from a set of RESOLVED trades — backtest, journal, or both."""
    buckets: dict[str, Bucket] = field(default_factory=dict)
    breakdowns: dict[str, dict[str, Bucket]] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # -- construction ------------------------------------------------------
    @classmethod
    def from_trades(cls, trades: list[dict], meta: dict | None = None) -> "StatsStore":
        store = cls(meta=dict(meta or {}))
        store.meta["trades"] = len(trades)
        groups: dict[str, list[dict]] = {}
        for t in trades:
            for _, keyfn in BUCKET_LEVELS:
                groups.setdefault(keyfn(t), []).append(t)
        store.buckets = {k: compute_bucket(k, v) for k, v in groups.items()}
        for name, keyfn in BREAKDOWNS.items():
            g: dict[str, list[dict]] = {}
            for t in trades:
                g.setdefault(keyfn(t), []).append(t)
            store.breakdowns[name] = {k: compute_bucket(k, v) for k, v in g.items()}
        return store

    # -- persistence -------------------------------------------------------
    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"meta": self.meta,
                       "buckets": {k: v.as_dict() for k, v in self.buckets.items()},
                       "breakdowns": {n: {k: v.as_dict() for k, v in b.items()}
                                      for n, b in self.breakdowns.items()}}, fh, indent=2)
        return path

    @classmethod
    def load(cls, path: str) -> "StatsStore":
        if not path or not os.path.exists(path):
            return cls(meta={"source": "none", "note": "no stats file — run `xau_bot.py backtest`"})
        with open(path) as fh:
            raw = json.load(fh)
        return cls(buckets={k: Bucket(**v) for k, v in raw.get("buckets", {}).items()},
                   breakdowns={n: {k: Bucket(**v) for k, v in b.items()}
                               for n, b in raw.get("breakdowns", {}).items()},
                   meta=raw.get("meta", {}))

    @property
    def empty(self) -> bool:
        return not self.buckets

    # -- lookup ------------------------------------------------------------
    def lookup(self, pattern: str, mode: str, grade: str, direction: str,
               min_sample: int = 30) -> ProbabilityEstimate:
        """
        Walk from the most specific bucket to the most general, stopping at the
        first with enough observations. If none qualifies, return the most
        specific bucket we DO have, flagged insufficient.
        """
        probe = {"pattern": pattern, "mode": mode, "grade": grade, "direction": direction}
        best_partial: ProbabilityEstimate | None = None
        for level, keyfn in BUCKET_LEVELS:
            b = self.buckets.get(keyfn(probe))
            if b is None or b.n == 0:
                continue
            est = ProbabilityEstimate(
                win_rate=b.win_rate, sample_size=b.n,
                profit_factor=None if b.profit_factor == float("inf") else b.profit_factor,
                avg_rr=b.target_rr or b.avg_rr, expectancy_r=b.expectancy_r,
                bucket=b.key, level=level, sufficient=b.n >= min_sample,
                note=(f"measured over n={b.n} backtested trades at the '{level}' level"
                      if b.n >= min_sample else
                      f"only n={b.n} observations at the '{level}' level "
                      f"(need {min_sample}) — no probability published"))
            if est.sufficient:
                return est
            if best_partial is None:
                best_partial = est
        return best_partial or ProbabilityEstimate(
            note="no historical observations of this configuration at any level")


def apply_probability(setup, store: StatsStore, min_sample: int = 30):
    """Stamp the measured (or explicitly absent) probability onto a setup."""
    est = store.lookup(setup.pattern, setup.mode, setup.grade, setup.direction, min_sample)
    setup.probability = est.win_rate if est.sufficient else None
    setup.sample_size = est.sample_size
    setup.profit_factor = est.profit_factor if est.sufficient else None
    setup.avg_rr = est.avg_rr if est.sufficient else None
    setup.prob_bucket = est.bucket
    setup.prob_note = est.note
    return setup


def validation_report(trades: list[dict]) -> dict:
    """
    Split the backtested trades chronologically and report each part separately.

    An in-sample number on its own says almost nothing: any rule tuned on a
    period will describe that period. What matters is whether the same rule
    still pays on data it did not shape. This repository already learned that
    the hard way (see sniper_smc.py), so the split is reported next to the
    headline figure rather than left for someone to ask about.

    Nothing here is tuned on the result. It is published as measured.
    """
    ordered = sorted(trades, key=lambda t: t.get("signal_ts", 0))
    n = len(ordered)
    if n < 20:
        return {"note": f"only {n} resolved trades — too few to split meaningfully"}

    def part(name: str, rows: list[dict]) -> dict:
        b = compute_bucket(name, rows)
        return {"n": b.n, "win_rate": b.win_rate,
                "profit_factor": None if b.profit_factor == float("inf") else b.profit_factor,
                "expectancy_r": b.expectancy_r, "total_r": b.total_r,
                "max_drawdown_r": b.max_drawdown_r}

    cut = int(n * 0.6)
    mid = n // 2
    out = {
        "method": ("chronological 60/40 train/test split and split halves; the "
                   "engine was not tuned on either part"),
        "train_first_60pct": part("train", ordered[:cut]),
        "test_last_40pct": part("test", ordered[cut:]),
        "first_half": part("h1", ordered[:mid]),
        "second_half": part("h2", ordered[mid:]),
        "test_by_grade": {g: part(g, [t for t in ordered[cut:] if t.get("grade") == g])
                          for g in ("A+", "A", "B", "C")
                          if any(t.get("grade") == g for t in ordered[cut:])},
    }
    tst = out["test_last_40pct"]
    pf = tst.get("profit_factor") or 0.0
    out["verdict"] = ("edge holds out of sample" if pf >= 1.3 else
                      "marginal out of sample" if pf >= 1.0 else
                      "DOES NOT HOLD out of sample — treat the in-sample figures as noise")
    return out


DISCLAIMER = ("Historical/backtested performance. Measured on past data only — "
              "it is not a prediction and not a guarantee of future results.")
