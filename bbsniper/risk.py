"""Modules 9 & 10 - risk management (filters, daily limits) and position sizing."""
import bisect, datetime as dt, math
from .data import load
from .entries import session_enabled

QUOTE_USD = {"USD": None, "JPY": ("USDJPY", True), "CHF": ("USDCHF", True), "CAD": ("USDCAD", True),
             "GBP": ("GBPUSD", False), "AUD": ("AUDUSD", False), "EUR": ("EURUSD", False), "NZD": ("NZDUSD", False)}
_conv = {}


def _close_at(sym, ts):
    if sym not in _conv:
        b = load(sym, "5m") or load(sym, "1h"); _conv[sym] = (list(b["t"]), list(b["c"]))
    t, c = _conv[sym]; return c[max(0, bisect.bisect_right(t, ts) - 1)]


def value_per_unit_move(sym, ts):
    """USD P/L of a 1.0-lot position for a price move of 1.0 (quote currency units)."""
    if sym == "XAUUSD": return 100.0                       # 100 oz per lot
    q = sym[3:]; m = QUOTE_USD[q]
    usd = 1.0 if m is None else (1.0 / _close_at(m[0], ts) if m[1] else _close_at(m[0], ts))
    return 100_000 * usd


def position_size(equity, risk_pct, entry, stop, sym, ts, cfg):
    """Lots from equity x risk / (stop distance x value per unit move). Rounded DOWN to the lot step.
    Returns (lots, usd_at_risk). 0 lots = trade skipped (below broker minimum)."""
    vpu = value_per_unit_move(sym, ts); dist = abs(entry - stop)
    if cfg.get("fixed_lot"): lots = cfg["fixed_lot"]
    else:
        raw = equity * risk_pct / 100 / (dist * vpu)
        lots = math.floor(raw / cfg["lot_step"] + 1e-9) * cfg["lot_step"]
        if lots < cfg["min_lot"]: return 0.0, 0.0
    return round(lots, 2), lots * dist * vpu


def passes(sig, cfg):
    """Static per-signal filters: score, spread, stop size, minimum RR room, session."""
    return (sig["score"] >= cfg["min_score"] and spread_ok(sig, cfg) and sl_ok(sig, cfg) and sig["room_r"] >= cfg["min_rr"]
            and session_enabled(sig["session"], cfg["sessions"]))


def spread_ok(sig, cfg):
    return sig["spread"] <= cfg["max_spread_pct_atr"] / 100 * sig["atr"]


def sl_ok(sig, cfg):
    return 0 < sig["risk"] <= cfg["max_sl_atr"] * sig["atr"] and sig["risk"] >= cfg["min_sl_spreads"] * sig["spread"]


def day_of(ts):
    return dt.datetime.fromtimestamp(ts, dt.UTC).date()


class DailyGuard:
    """Max trades/day, stop after N losses/day, daily loss limit (% of start-of-day equity)."""
    def __init__(self, cfg):
        self.cfg = cfg; self.day = None

    def roll(self, ts, equity):
        d = day_of(ts)
        if d != self.day: self.day, self.n, self.losses, self.pl, self.sod = d, 0, 0, 0.0, equity

    def allow(self):
        c = self.cfg
        return (self.n < c["max_trades_day"] and self.losses < c["max_losses_day"]
                and -self.pl < c["daily_loss_pct"] / 100 * self.sod)

    def opened(self): self.n += 1

    def closed(self, pl):
        self.pl += pl
        if pl < 0: self.losses += 1
