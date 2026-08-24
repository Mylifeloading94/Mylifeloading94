"""
Kill switch / emergency halt. Any component can trip it; nothing except an
explicit reset can clear it. Used for UNKNOWN order state, data staleness,
API disconnection, and the forward-performance deviation monitor.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KillSwitch:
    tripped: bool = False
    reasons: list = field(default_factory=list)
    halt_new_trades_only: bool = False

    def trip(self, reason: str, close_positions: bool = False) -> None:
        self.tripped = True
        self.halt_new_trades_only = not close_positions
        self.reasons.append(reason)

    def allow_new_trades(self) -> bool:
        return not self.tripped

    def must_flatten(self) -> bool:
        return self.tripped and not self.halt_new_trades_only

    def reset(self, operator_ack: bool = False) -> None:
        if not operator_ack:
            raise PermissionError("kill switch reset requires explicit operator acknowledgement")
        self.tripped = False
        self.halt_new_trades_only = False
        self.reasons.clear()
