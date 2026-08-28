"""
Signal history (spec §14).

Every setup the engine publishes is written here and then tracked to a result:
maximum favourable excursion, maximum adverse excursion, R multiple, outcome.
This is a PAPER record — the bot places no orders. It exists so the engine can
be judged on what it actually said, not on what it says it would have said.

Journal results are LIVE-TRACKED data and are kept strictly separate from the
backtest's HISTORICAL data everywhere they are displayed.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

STATES = ("PENDING", "ACTIVE", "CLOSED", "INVALIDATED")


@dataclass
class Record:
    # identity / provenance
    id: str = ""
    signal_ts: int = 0                  # bar timestamp the sequence completed on
    created_at: float = 0.0             # wall clock when first published
    mode: str = ""
    pattern: str = ""
    direction: str = ""
    session: str = ""
    exec_tf: str = ""
    data_quality: str = ""
    data_source: str = ""
    # the published plan
    price_at_signal: float = 0.0
    entry: float = 0.0
    entry_low: float = 0.0
    entry_high: float = 0.0
    entry_type: str = ""
    sl: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float | None = None
    target_rr: float = 0.0
    sl_pips: float = 0.0
    grade: str = ""
    score: float = 0.0
    probability: float | None = None
    sample_size: int = 0
    history_flag: str = ""
    # tracking
    state: str = "PENDING"
    fill_price: float | None = None
    fill_ts: int | None = None
    exit_price: float | None = None
    exit_ts: int | None = None
    outcome: str = ""                   # WIN | LOSS | BREAKEVEN | INVALIDATED | EXPIRED
    r_multiple: float = 0.0
    mfe: float = 0.0                    # in price
    mae: float = 0.0
    mfe_r: float = 0.0
    mae_r: float = 0.0
    high_since: float | None = None
    low_since: float | None = None
    last_seen_ts: float = 0.0
    invalid_reason: str = ""
    partial_taken: bool = False
    # The SMC anchors the setup was built on (sweep, MSS, POI, HTF range).
    # Kept so re-validation can check the ORIGINAL premise — a liquidity
    # reclaim or an invalidated FVG cannot be detected without them.
    anchors: dict = field(default_factory=dict)

    @property
    def buy(self) -> bool:
        return self.direction == "BUY"

    @property
    def risk(self) -> float:
        base = self.fill_price if self.fill_price is not None else self.entry
        return abs(base - self.sl)

    @property
    def day(self) -> str:
        return datetime.fromtimestamp(self.created_at or self.signal_ts,
                                      tz=timezone.utc).strftime("%Y-%m-%d")

    def as_stat_trade(self) -> dict:
        return {"pattern": self.pattern, "mode": self.mode, "grade": self.grade,
                "direction": self.direction, "session": self.session,
                "exec_tf": self.exec_tf, "r_multiple": self.r_multiple,
                "target_rr": self.target_rr, "outcome": self.outcome,
                "signal_ts": self.signal_ts, "exit_ts": self.exit_ts or 0}


class Journal:
    """Append-only signal log with an in-memory index keyed by setup id."""

    def __init__(self, path: str):
        self.path = path
        self.records: dict[str, Record] = {}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                known = {f for f in Record.__dataclass_fields__}
                self.records[d.get("id", "")] = Record(**{k: v for k, v in d.items() if k in known})

    def flush(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            for r in sorted(self.records.values(), key=lambda x: x.created_at):
                fh.write(json.dumps(asdict(r)) + "\n")
        os.replace(tmp, self.path)

    # -- writing -----------------------------------------------------------
    def record(self, setup) -> tuple[Record, bool]:
        """Insert a setup, or refresh the still-live plan for one already known."""
        existing = self.records.get(setup.id)
        if existing is not None:
            if existing.state == "PENDING":       # plan may still be re-priced
                existing.entry, existing.sl = setup.entry, setup.sl
                existing.tp1, existing.tp2, existing.tp3 = setup.tp1, setup.tp2, setup.tp3
                existing.grade, existing.score = setup.grade, setup.score
                existing.probability, existing.sample_size = setup.probability, setup.sample_size
            existing.last_seen_ts = time.time()
            return existing, False
        r = Record(
            id=setup.id, signal_ts=setup.signal_ts, created_at=time.time(), mode=setup.mode,
            pattern=setup.pattern, direction=setup.direction, session=setup.session,
            exec_tf=setup.anchors.get("ltf_tf", ""), data_quality=setup.data_quality,
            data_source=setup.data_source, price_at_signal=setup.price_at_signal,
            entry=setup.entry, entry_low=setup.entry_low, entry_high=setup.entry_high,
            entry_type=setup.entry_type, sl=setup.sl, tp1=setup.tp1, tp2=setup.tp2,
            tp3=setup.tp3, target_rr=setup.rr, sl_pips=setup.sl_pips, grade=setup.grade,
            score=setup.score, probability=setup.probability, sample_size=setup.sample_size,
            history_flag=setup.history_flag,
            anchors=dict(setup.anchors),
            state="ACTIVE" if setup.entry_type == "MARKET" else "PENDING",
            fill_price=setup.entry if setup.entry_type == "MARKET" else None,
            fill_ts=setup.signal_ts if setup.entry_type == "MARKET" else None,
            last_seen_ts=time.time())
        self.records[r.id] = r
        return r, True

    def invalidate(self, setup_id: str, reason: str):
        r = self.records.get(setup_id)
        if r is None or r.state in ("CLOSED", "INVALIDATED"):
            return
        r.state = "INVALIDATED"
        r.invalid_reason = reason
        r.outcome = r.outcome or "INVALIDATED"
        r.exit_ts = int(time.time())

    # -- tracking ----------------------------------------------------------
    def track(self, price: float, high: float, low: float, ts: int):
        """
        Advance every open record against the latest price action. Fills, TP1
        partials, breakeven runners and stops are resolved with the same rules
        the backtest uses, so live and historical R multiples are comparable.
        """
        for r in list(self.records.values()):
            if r.state in ("CLOSED", "INVALIDATED"):
                continue
            r.high_since = high if r.high_since is None else max(r.high_since, high)
            r.low_since = low if r.low_since is None else min(r.low_since, low)
            r.last_seen_ts = time.time()

            if r.state == "PENDING":
                hit = (low <= r.entry) if r.buy else (high >= r.entry)
                if not hit:
                    continue
                r.state, r.fill_price, r.fill_ts = "ACTIVE", r.entry, ts

            risk = r.risk
            if risk <= 0:
                continue
            fav = (high - r.fill_price) if r.buy else (r.fill_price - low)
            adv = (r.fill_price - low) if r.buy else (high - r.fill_price)
            r.mfe = max(r.mfe, max(0.0, fav))
            r.mae = min(r.mae, -max(0.0, adv))
            r.mfe_r, r.mae_r = round(r.mfe / risk, 3), round(r.mae / risk, 3)

            stop = r.fill_price if r.partial_taken else r.sl
            hit_sl = (low <= stop) if r.buy else (high >= stop)
            hit_tp1 = (high >= r.tp1) if r.buy else (low <= r.tp1)
            hit_tp2 = (high >= r.tp2) if r.buy else (low <= r.tp2)

            if hit_sl and (hit_tp1 or hit_tp2):
                self._close(r, stop, ts, "stop and target in the same window — booked as the stop")
                continue
            if hit_sl:
                self._close(r, stop, ts,
                            "runner stopped at breakeven after TP1" if r.partial_taken
                            else "stop loss hit")
                continue
            if hit_tp2:
                self._close(r, r.tp2, ts, "TP2 reached")
                continue
            if hit_tp1 and not r.partial_taken:
                r.partial_taken = True

    def _close(self, r: Record, price: float, ts: int, reason: str):
        risk = r.risk or 1e-9
        sign = 1 if r.buy else -1
        if r.partial_taken:
            r.r_multiple = round(0.5 * sign * (r.tp1 - r.fill_price) / risk
                                 + 0.5 * sign * (price - r.fill_price) / risk, 3)
        else:
            r.r_multiple = round(sign * (price - r.fill_price) / risk, 3)
        r.state, r.exit_price, r.exit_ts = "CLOSED", round(price, 2), ts
        r.outcome = "WIN" if r.r_multiple > 0.02 else ("LOSS" if r.r_multiple < -0.02 else "BREAKEVEN")
        r.invalid_reason = reason

    # -- reading -----------------------------------------------------------
    def open_records(self) -> list[Record]:
        return [r for r in self.records.values() if r.state in ("PENDING", "ACTIVE")]

    def resolved(self) -> list[dict]:
        return [r.as_stat_trade() for r in self.records.values()
                if r.state == "CLOSED" and r.outcome in ("WIN", "LOSS", "BREAKEVEN")]

    def today(self, day: str | None = None) -> list[Record]:
        day = day or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        return [r for r in self.records.values() if r.day == day]

    def count_today(self) -> int:
        return len(self.today())

    def consecutive_losses(self) -> int:
        closed = sorted([r for r in self.records.values() if r.state == "CLOSED"],
                        key=lambda r: r.exit_ts or 0)
        n = 0
        for r in reversed(closed):
            if r.outcome == "LOSS":
                n += 1
            else:
                break
        return n

    def realised_r_today(self) -> float:
        return round(sum(r.r_multiple for r in self.today() if r.state == "CLOSED"), 2)
