"""Centralised configuration loader.

Every tunable in the system lives in ``config.yaml``. Nothing in the strategy
code is allowed to hard-code a threshold; modules ask the :class:`Config`
object for values, and per-instrument overrides are resolved here.
"""
from __future__ import annotations

import copy
import os
from typing import Any

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(_HERE, "config.yaml")
REPO_ROOT = os.path.dirname(_HERE)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into a copy of ``base``."""
    out = copy.deepcopy(base)
    for key, val in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


class Config:
    """Dotted-path access to the config tree, with instrument overrides."""

    def __init__(self, data: dict):
        self._data = data
        self._instrument_cache: dict[str, dict] = {}

    # -- construction ---------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        path = path or DEFAULT_CONFIG_PATH
        with open(path, "r") as fh:
            return cls(yaml.safe_load(fh))

    def copy(self) -> "Config":
        return Config(copy.deepcopy(self._data))

    # -- access ---------------------------------------------------------
    @property
    def data(self) -> dict:
        return self._data

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        """Set a dotted path (used by perturbation / robustness checks)."""
        parts = dotted.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self._instrument_cache.clear()

    def with_override(self, dotted: str, value: Any) -> "Config":
        clone = self.copy()
        clone.set(dotted, value)
        return clone

    # -- instrument resolution -----------------------------------------
    def for_instrument(self, symbol: str) -> "InstrumentConfig":
        """Return the effective config for ``symbol`` (globals + overrides)."""
        if symbol not in self._instrument_cache:
            over = self.get(f"instrument_overrides.{symbol}", {}) or {}
            merged = _deep_merge(self._data, over)
            self._instrument_cache[symbol] = merged
        return InstrumentConfig(symbol, self._instrument_cache[symbol], self)

    # -- convenience ----------------------------------------------------
    @property
    def symbols(self) -> list[str]:
        return list(self.get("markets", {}).keys())

    @property
    def score_threshold(self) -> float:
        profile = self.get("scoring.active_profile", "standard")
        explicit = self.get("scoring.threshold")
        if explicit is not None:
            return float(explicit)
        return float(self.get(f"scoring.profiles.{profile}", 80))

    @property
    def stack(self) -> dict:
        name = self.get("active_stack", "long")
        return dict(self.get(f"stacks.{name}", {}), name=name)

    def use_stack(self, name: str) -> "Config":
        clone = self.copy()
        clone.set("active_stack", name)
        return clone

    def apply_profile(self, name: str) -> "Config":
        """Return a copy with the named ``profiles.<name>`` overrides applied.

        A profile is a flat map of dotted paths to values. It exists so a whole
        strategy variant (the v3 scalper) can be selected without editing the
        defaults that the v2 swing stack is validated against -- the two must
        stay independently reproducible, and "I changed a default and forgot"
        is how a validated result quietly stops being the result it claims.
        """
        overrides = self.get(f"profiles.{name}")
        if not overrides:
            raise KeyError(f"no config profile named {name!r}")
        clone = self.copy()
        for dotted, value in overrides.items():
            clone.set(dotted, value)
        return clone

    def resolve_path(self, path: str | None) -> str | None:
        if not path:
            return None
        return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)


class InstrumentConfig:
    """A per-symbol view of the config with market metadata attached."""

    def __init__(self, symbol: str, data: dict, parent: Config):
        self.symbol = symbol
        self._data = data
        self.parent = parent
        self.market = data.get("markets", {}).get(symbol, {})

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # -- market metadata ------------------------------------------------
    @property
    def pip(self) -> float:
        return float(self.market.get("pip", 0.0001))

    @property
    def yahoo_symbol(self) -> str:
        return self.market.get("yahoo", f"{self.symbol}=X")

    @property
    def broker_symbol(self) -> str:
        return self.market.get("broker", self.symbol)

    @property
    def instrument_type(self) -> str:
        return self.market.get("type", "fx_major")

    @property
    def spread_pips(self) -> float:
        default = self.get("execution.max_spread_pips_default", 2.0)
        return float(self.get(f"execution.spreads.{self.symbol}", default))

    @property
    def max_spread_pips(self) -> float:
        return float(self.get("execution.max_spread_pips_default", 2.0))

    @property
    def allowed_sessions(self) -> list[str]:
        return list(self.get("sessions.allowed", []) or [])

    @property
    def risk_per_trade_pct(self) -> float:
        pct = float(self.get("risk.risk_per_trade_pct", 0.5))
        lo = float(self.get("risk.risk_per_trade_min_pct", 0.25))
        hi = float(self.get("risk.risk_per_trade_max_pct", 1.0))
        return min(max(pct, lo), hi)

    def price_to_pips(self, price_delta: float) -> float:
        return price_delta / self.pip

    def pips_to_price(self, pips: float) -> float:
        return pips * self.pip


def load_config(path: str | None = None) -> Config:
    return Config.load(path)
