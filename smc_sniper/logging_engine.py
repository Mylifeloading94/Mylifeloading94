"""Decision logging.

The spec asks for a full decision log "including every REJECTED setup with
reason, score and state". That is the point of this module: the log of what the
bot *declined* is more diagnostic than the log of what it took, and it is the
main defence against a strategy that looks selective but is actually just
lucky.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone


def _default(obj):
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "item"):
        try:
            return obj.item()
        except (ValueError, AttributeError):
            pass
    return str(obj)


class DecisionLog:
    """Append-only JSONL log of signals, rejections, fills and errors."""

    def __init__(self, cfg, name: str = "decisions"):
        self.cfg = cfg
        directory = cfg.resolve_path(cfg.get("logging.dir", "reports"))
        os.makedirs(directory, exist_ok=True)
        self.path = os.path.join(directory, f"{name}.jsonl")
        self.log_rejected = bool(cfg.get("logging.log_rejected_setups", True))
        self.records: list[dict] = []

    def _write(self, record: dict) -> None:
        record["ts"] = datetime.now(timezone.utc).isoformat()
        self.records.append(record)
        with open(self.path, "a") as fh:
            fh.write(json.dumps(record, default=_default) + "\n")

    def signal(self, sig) -> None:
        self._write({"type": "signal", "symbol": sig.symbol, "time": sig.time,
                     "direction": sig.direction, "score": sig.score,
                     "setup_id": sig.setup_id, "signal_id": sig.signal_id,
                     "explanation": sig.explanation})

    def rejection(self, rej) -> None:
        if not self.log_rejected:
            return
        self._write({"type": "rejection", "symbol": rej.symbol, "time": rej.time,
                     "direction": rej.direction, "step": rej.step,
                     "reason": rej.reason, "score": rej.score,
                     "session": rej.session, "state": rej.state})

    def fill(self, trade) -> None:
        self._write({"type": "fill", "symbol": trade.symbol,
                     "entry_time": trade.entry_time, "entry": trade.entry,
                     "stop": trade.stop, "size_lots": trade.size_lots})

    def close(self, trade) -> None:
        self._write({"type": "close", "symbol": trade.symbol,
                     "exit_time": trade.exit_time, "exit_price": trade.exit_price,
                     "reason": trade.exit_reason, "r": trade.r_multiple,
                     "pnl": trade.pnl})

    def error(self, message: str, **extra) -> None:
        self._write({"type": "error", "message": message, **extra})

    def reset(self) -> None:
        if os.path.exists(self.path):
            os.remove(self.path)
        self.records = []
