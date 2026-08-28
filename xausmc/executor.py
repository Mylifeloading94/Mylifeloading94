"""
Automatic execution loop.

Scans on an interval, and when the engine publishes a setup that passes the
execution filter, sends it to the broker with its protection attached.

The design points that matter when this runs unattended:

  * Orders are calibrated to the BROKER'S OWN QUOTE. The analysis may run on a
    proxy feed whose prices sit several dollars from spot; every level is
    shifted by the measured broker-vs-feed basis before it is sent, so a stop
    lands where the analysis meant it to and not eight dollars away.
  * Stop loss and take profit go with the order, in the same request. If this
    process dies, the broker still holds them. Nothing is left naked.
  * Risk gates are re-checked against live equity every cycle, and the day's
    loss limit is measured from the equity recorded at the start of the day.
  * `dry_run` is the default. Sending real orders takes a deliberate flag.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .broker import Account, Position, TradeLockerBroker
from .engine import GRADE_RANK, Engine, ScanResult
from .setups import Setup

# XAUUSD contract: 1.00 lot = 100 oz, so a 1.00 USD move is 100 USD per lot and
# one pip (0.10) is 10 USD per lot.
XAU_USD_PER_PIP_PER_LOT = 10.0


@dataclass
class ExecConfig:
    symbol: str = "XAUUSD"
    modes: tuple[str, ...] = ("SCALP",)
    min_grade: str = "A"
    risk_pct: float = 0.02
    max_open: int = 1
    max_trades_per_day: int = 6
    daily_loss_pct: float = 0.06          # of start-of-day equity
    max_consecutive_losses: int = 3
    max_lots: float = 5.0
    poll_sec: int = 60
    dry_run: bool = True
    take_partial_at_tp1: bool = True
    max_basis: float = 25.0               # refuse to trade if feed and broker disagree by more

    @property
    def env(self) -> str:
        return os.environ.get("TL_ENV", "demo").lower()


@dataclass
class ExecState:
    day: str = ""
    day_start_equity: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    realised_today: float = 0.0
    halted: bool = False
    halt_reason: str = ""

    def roll_day(self, equity: float):
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        if self.day != today:
            self.day = today
            self.day_start_equity = equity
            self.trades_today = 0
            self.realised_today = 0.0
            if self.halted and "loss limit" in self.halt_reason:
                self.halted, self.halt_reason = False, ""


class Executor:
    def __init__(self, engine: Engine, broker: TradeLockerBroker, cfg: ExecConfig):
        self.engine = engine
        self.broker = broker
        self.cfg = cfg
        self.state = ExecState()
        self.account: Account | None = None
        self.state_path = engine.cfg.path("executor_state.json")
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path) as fh:
                    d = json.load(fh)
                known = set(ExecState.__dataclass_fields__)
                self.state = ExecState(**{k: v for k, v in d.items() if k in known})
            except (OSError, json.JSONDecodeError, TypeError):
                pass

    def _save(self):
        with open(self.state_path, "w") as fh:
            json.dump(self.state.__dict__, fh, indent=2)

    # -- calibration -------------------------------------------------------
    def basis(self, res: ScanResult) -> tuple[float | None, str]:
        """
        How far the analysis feed sits from the broker's own mid. Every level is
        shifted by this before it is sent, so the order lands where the analysis
        meant it to.

        Returns None when the offset cannot be established. That is a REFUSAL,
        not a zero: treating an unknown offset as zero would send proxy-derived
        levels straight through — on gold that is roughly a nine dollar error,
        which puts the stop on the wrong side of the zone it was placed behind.
        A calibration you cannot verify is worse than no trade.
        """
        if res.feed.is_true_xauusd:
            return 0.0, "feed is the broker's own XAUUSD — no calibration needed"
        if res.price is None:
            return None, "no feed price to calibrate from"
        try:
            bid, ask = self.broker.quote(self.cfg.symbol)
        except Exception as exc:                      # noqa: BLE001 - absence is the answer
            return None, f"broker quote failed: {type(exc).__name__}: {exc}"
        if not bid or not ask:
            return None, ("broker returned no quote, and the analysis feed is a proxy — "
                          "the offset between them is unknown")
        mid = (bid + ask) / 2.0
        return round(mid - res.price, 2), f"broker mid {mid:,.2f} vs feed {res.price:,.2f}"

    def size(self, sl_pips: float, equity: float) -> tuple[float, float]:
        """Lots and dollars at risk. Rounded DOWN, so rounding never adds risk."""
        risk_dollars = equity * self.cfg.risk_pct
        if sl_pips <= 0:
            return 0.0, 0.0
        raw = risk_dollars / (sl_pips * XAU_USD_PER_PIP_PER_LOT)
        lots = min(raw, self.cfg.max_lots)
        lots = int(lots * 100) / 100.0                 # floor to 0.01
        return lots, round(risk_dollars, 2)

    # -- gates -------------------------------------------------------------
    def gates(self, open_positions: list[Position]) -> list[str]:
        s, c = self.state, self.cfg
        blocks: list[str] = []
        if s.halted:
            blocks.append(f"HALTED — {s.halt_reason}")
        if len(open_positions) >= c.max_open:
            blocks.append(f"max open positions ({len(open_positions)}/{c.max_open})")
        if s.trades_today >= c.max_trades_per_day:
            blocks.append(f"max trades today ({s.trades_today}/{c.max_trades_per_day})")
        if s.consecutive_losses >= c.max_consecutive_losses:
            blocks.append(f"{s.consecutive_losses} consecutive losses — standing down")
        if s.day_start_equity > 0:
            limit = -c.daily_loss_pct * s.day_start_equity
            if s.realised_today <= limit:
                blocks.append(f"daily loss limit hit ({s.realised_today:+.2f} of {limit:.2f})")
        return blocks

    def eligible(self, res: ScanResult) -> list[Setup]:
        c = self.cfg
        return [s for s in res.setups
                if s.mode in c.modes
                and s.status == "VALID"
                and GRADE_RANK[s.grade] >= GRADE_RANK[c.min_grade]]

    # -- reconciliation ----------------------------------------------------
    def reconcile(self, positions: list[Position]) -> list[str]:
        """Match broker reality to the journal; book results for anything closed."""
        notes: list[str] = []
        live_ids = {p.id for p in positions}
        for rec in self.engine.journal.records.values():
            if not rec.executed or not rec.broker_position_id:
                continue
            if rec.state in ("CLOSED", "INVALIDATED"):
                continue
            if rec.broker_position_id not in live_ids:
                rec.state = "CLOSED"
                rec.exit_ts = int(time.time())
                rec.outcome = rec.outcome or "CLOSED_AT_BROKER"
                notes.append(f"position {rec.broker_position_id} closed at the broker [{rec.id}]")
                if rec.r_multiple < -0.02:
                    self.state.consecutive_losses += 1
                elif rec.r_multiple > 0.02:
                    self.state.consecutive_losses = 0
        return notes

    def manage(self, positions: list[Position]) -> list[str]:
        """Take the TP1 partial and move the runner's stop to breakeven."""
        if not self.cfg.take_partial_at_tp1:
            return []
        notes: list[str] = []
        by_pos = {r.broker_position_id: r for r in self.engine.journal.records.values()
                  if r.broker_position_id}
        bid, ask = self.broker.quote(self.cfg.symbol)
        if not bid or not ask:
            return notes
        px = (bid + ask) / 2.0
        for p in positions:
            rec = by_pos.get(p.id)
            if rec is None or rec.partial_taken:
                continue
            hit = (px >= rec.tp1) if p.is_buy else (px <= rec.tp1)
            if not hit:
                continue
            half = int((p.qty / 2) * 100) / 100.0
            if half < 0.01:
                continue
            if self.cfg.dry_run:
                notes.append(f"[dry run] would close {half} lots at TP1 and move the stop "
                             f"to breakeven on {p.id}")
            elif self.broker.close_position(p.id, half):
                self.broker.modify_position(p.id, stop_loss=p.open_price)
                rec.partial_taken = True
                notes.append(f"TP1 hit — closed {half} lots and moved the stop to breakeven "
                             f"on {p.id}")
        return notes

    # -- placing -----------------------------------------------------------
    def submit(self, setup: Setup, equity: float, basis: float) -> dict:
        side = "buy" if setup.direction == "BUY" else "sell"
        entry = round(setup.entry + basis, 2)
        sl = round(setup.sl + basis, 2)
        tp = round(setup.tp2 + basis, 2)
        lots, risk_usd = self.size(setup.sl_pips, equity)
        plan = {"symbol": self.cfg.symbol, "side": side, "qty": lots, "entry": entry,
                "stop_loss": sl, "take_profit": tp, "tp1": round(setup.tp1 + basis, 2),
                "sl_pips": setup.sl_pips, "risk_usd": risk_usd, "basis": basis,
                "setup_id": setup.id, "grade": setup.grade, "mode": setup.mode,
                "probability": setup.probability, "sample_size": setup.sample_size,
                "order_type": "market" if setup.entry_state == "ARMED" else "limit"}
        if lots < 0.01:
            plan["error"] = f"computed size {lots} is below the 0.01 minimum"
            return plan
        if self.cfg.dry_run:
            plan["dry_run"] = True
            return plan

        res = self.broker.place(
            symbol=self.cfg.symbol, side=side, qty=lots, stop_loss=sl, take_profit=tp,
            order_type=plan["order_type"],
            price=entry if plan["order_type"] == "limit" else None)
        plan["order_id"] = res["order_id"]

        rec = self.engine.journal.records.get(setup.id)
        if rec is not None:
            rec.executed = True
            rec.broker_env = self.cfg.env
            rec.broker_order_id = str(res["order_id"])
            rec.lots = lots
            known = {r.broker_position_id for r in self.engine.journal.records.values()
                     if r.broker_position_id}
            for p in self.broker.positions(self.cfg.symbol):
                if p.id not in known and p.stop_loss and abs(p.stop_loss - sl) < 0.5:
                    rec.broker_position_id = p.id
                    break
            self.engine.journal.flush()
        self.state.trades_today += 1
        self._save()
        return plan

    # -- one cycle ---------------------------------------------------------
    def cycle(self) -> dict:
        out: dict = {"ts": time.time(), "notes": [], "placed": [], "blocked": []}
        self.account = self.broker.refresh_account()
        equity = self.account.equity or self.account.balance
        self.state.roll_day(equity)

        positions = self.broker.positions(self.cfg.symbol)
        out["notes"] += self.reconcile(positions)
        out["notes"] += self.manage(positions)
        out["open_positions"] = len(positions)
        out["equity"] = equity

        res = self.engine.scan()
        out["scan"] = res
        if not res.live:
            out["blocked"].append(res.feed.banner)
            return out

        basis, basis_note = self.basis(res)
        out["basis"], out["basis_note"] = basis, basis_note
        if basis is None:
            out["blocked"].append(
                f"cannot calibrate the analysis feed to the broker — {basis_note}. "
                f"Refusing to send orders at prices that may be several dollars off. "
                f"Set TL_EMAIL/TL_PASSWORD/TL_SERVER so the engine reads the broker's "
                f"own XAUUSD feed and no calibration is needed.")
            return out
        if abs(basis) > self.cfg.max_basis:
            out["blocked"].append(
                f"feed and broker disagree by {basis:+.2f} (limit {self.cfg.max_basis}) — "
                f"refusing to trade on a suspect calibration")
            return out

        blocks = self.gates(positions)
        if blocks:
            out["blocked"] += blocks
            return out

        for setup in self.eligible(res):
            out["placed"].append(self.submit(setup, equity, basis))
            positions = self.broker.positions(self.cfg.symbol)
            if len(positions) >= self.cfg.max_open:
                break
        if not out["placed"] and not out["blocked"]:
            out["notes"].append("no setup met the execution filter")
        return out

    def halt(self, reason: str):
        self.state.halted = True
        self.state.halt_reason = reason
        self._save()
