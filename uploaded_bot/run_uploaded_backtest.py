#!/usr/bin/env python3
"""Run the uploaded bot over 90 days of real TradeLocker history, twice:

  Run A  "as uploaded"    — the shipped engine, all four fill bugs intact.
  Run B  "honest fills"   — the same entry/exit logic, four bugs corrected.

Plus four single-fix isolation runs so each bug's cost can be attributed.

Money basis: $100,000, RISK_PER_TRADE = 2% (smc_sniper/config.py), sized by
smc_sniper/risk.py::position_size (lots floored to 0.01), compounding trade by
trade in entry-time order across the pooled pair universe.

Writes ``uploaded_bot/results.json``. READ-ONLY on the broker: it consumes the
JSON that build_data.py already fetched. Nothing here can place an order.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sniper_backtest_honest import (ALL_FIXES, PIP, PIP_VAL, load_data,  # noqa: E402
                                    sniper_bt)

START_BALANCE = 100_000.0
RISK_PER_TRADE = 0.02      # smc_sniper/config.py :: SniperConfig.RISK_PER_TRADE
MIN_LOT = 0.01


def size_lots(risk_pips: float, pip_val: float, equity: float) -> float:
    """smc_sniper/risk.py::position_size — floor to 0.01, never round up."""
    dollar_risk = equity * RISK_PER_TRADE
    raw = dollar_risk / (risk_pips * pip_val) if risk_pips * pip_val > 0 else 0.0
    return max(MIN_LOT, math.floor(raw * 100) / 100)


def ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def build_ledger(trades: list) -> dict:
    """Pool the per-pair trades, order by entry time, compound the account."""
    rows = sorted(trades, key=lambda t: t["entry_ts"])
    bal = START_BALANCE
    peak = bal
    max_dd = 0.0
    ledger = []
    total_pips = 0.0
    for t in rows:
        pip = PIP[t["symbol"]]; pv = PIP_VAL[t["symbol"]]
        risk_pips = t["risk_pips"]
        lots = size_lots(risk_pips, pv, bal)
        dollar_risk = lots * risk_pips * pv
        profit = t["R"] * dollar_risk
        pips = t["R"] * risk_pips
        total_pips += pips
        bal += profit
        peak = max(peak, bal)
        dd = (peak - bal) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        ledger.append({
            "entry_time": ts(t["entry_ts"]), "exit_time": ts(t["exit_ts"]),
            "pair": t["symbol"], "direction": t["direction"], "lots": round(lots, 2),
            "entry_price": round(t["entry"], 5), "stop": round(t["sl_initial"], 5),
            "target": round(t["tp2"], 5), "exit_price": round(t["exit_px"], 5),
            "risk_pips": round(risk_pips, 1), "pips": round(pips, 1),
            "profit": round(profit, 2), "R": round(t["R"], 4),
            "result": "WIN" if t["R"] > 0.05 else ("LOSS" if t["R"] < -0.05 else "SCRATCH"),
            "reason": t["reason"], "balance": round(bal, 2),
            "entry_ms": t["entry_ts"],
        })
    return {"ledger": ledger, "end_balance": bal, "max_dd_pct": max_dd * 100,
            "total_pips": total_pips, "profit": bal - START_BALANCE,
            "roi_pct": (bal - START_BALANCE) / START_BALANCE * 100}


def bootstrap_ci(rs: list, n=10000, seed=7):
    if len(rs) < 2:
        return (float("nan"), float("nan"))
    rnd = random.Random(seed)
    k = len(rs)
    means = []
    for _ in range(n):
        means.append(sum(rs[rnd.randrange(k)] for _ in range(k)) / k)
    means.sort()
    return means[int(0.025 * n)], means[int(0.975 * n)]


def _wide_sess(ms):
    """The shipped sniper_backtest.in_sess() — 07:00-10:45 / 12:30-15:45 UTC."""
    h = (ms // 3600000) % 24; m = (ms // 60000) % 60
    if 7 <= h <= 9: return True
    if h == 10 and m <= 45: return True
    if h == 12 and m >= 30: return True
    if 13 <= h <= 14: return True
    if h == 15 and m <= 45: return True
    return False


# The package ships TWO parameter sets. `final` is the one its docstrings and
# smc_sniper/config.py call validated ("70.0% WR, PF 2.17"). `shipdefaults` is
# what `python3 sniper_backtest.py` actually executes — the pre-OTE defaults in
# the function signature. Both are the package's own; neither is retuned here.
PARAMS = {
    "final": dict(disp_mult=1.1, tp2_R=2.5, ote_band=(0.62, 0.90), sess_only=True),
    "shipdefaults": dict(disp_mult=0.6, tp2_R=2.0, ote_band=None, sess_only=True,
                         wide_sessions=True),
}


def run(data, pairs, lo_ts, hi_ts, fixes, params=None):
    """Run the engine over every pair; return pooled stats + trade list."""
    import sniper_backtest_honest as eng
    kw = dict(params or PARAMS["final"])
    wide = kw.pop("wide_sessions", False)
    saved = eng.in_prime_kz
    if wide:   # the shipped engine's own wider in_sess() window
        eng.in_prime_kz = _wide_sess
    all_trades = []
    per_pair = {}
    for name in pairs:
        r = sniper_bt(name, data["bars"][name], lo_ts=lo_ts, hi_ts=hi_ts,
                      fixes=fixes, **kw)
        per_pair[name] = {k: r[k] for k in ("n", "WR", "PF", "expR", "totR",
                                            "wins", "losses", "scratches")}
        all_trades.extend(r["trades"])
    eng.in_prime_kz = saved

    Rs = [t["R"] for t in all_trades]
    wins = sum(1 for r in Rs if r > 0.05)
    losses = sum(1 for r in Rs if r < -0.05)
    scr = len(Rs) - wins - losses
    gW = sum(r for r in Rs if r > 0.05)
    gL = -sum(r for r in Rs if r < -0.05)
    dec = (wins + losses + scr) if "denom" in set(fixes) else (wins + losses)
    return {
        "n": len(Rs), "wins": wins, "losses": losses, "scratches": scr,
        "WR": (wins / dec * 100) if dec else 0.0,
        "PF": (gW / gL) if gL > 0 else (999.0 if gW > 0 else 0.0),
        "expR": (sum(Rs) / len(Rs)) if Rs else 0.0,
        "totR": sum(Rs), "per_pair": per_pair, "trades": all_trades,
    }


def main() -> int:
    data = load_data()
    pairs = list(data["bars"])
    lo_ts = data["trade_window_start_ms"]
    hi_ts = data["now_ms"]
    days = (hi_ts - lo_ts) / 86400_000

    print(f"window {ts(lo_ts)} -> {ts(hi_ts)} UTC  ({days:.0f} days)")
    print(f"pairs: {pairs}   unavailable: {data['unavailable'] or 'none'}")
    print(f"basis ${START_BALANCE:,.0f} @ {RISK_PER_TRADE:.0%}/trade, compounding\n")

    out = {"window": {"from": ts(lo_ts), "to": ts(hi_ts), "days": days},
           "pairs": pairs, "unavailable": data["unavailable"],
           "start_balance": START_BALANCE, "risk_per_trade": RISK_PER_TRADE,
           "runs": {}}

    variants = [("as_uploaded", (), "final"), ("honest", ALL_FIXES, "final")]
    variants += [(f"only_{f}", (f,), "final") for f in ALL_FIXES]
    # Same engine, same data, the package's OTHER shipped parameter set —
    # reported separately because n=7 on the "final" config decides nothing.
    variants += [("as_uploaded_shipdefaults", (), "shipdefaults"),
                 ("honest_shipdefaults", ALL_FIXES, "shipdefaults")]
    variants += [(f"shipdefaults_only_{f}", (f,), "shipdefaults") for f in ALL_FIXES]

    for label, fixes, pset in variants:
        r = run(data, pairs, lo_ts, hi_ts, fixes, PARAMS[pset])
        led = build_ledger(r["trades"])
        lo, hi = bootstrap_ci([t["R"] for t in r["trades"]])
        r.update(led)
        r["ci95"] = [lo, hi]
        r["trades_per_day"] = r["n"] / days
        r["fixes"] = list(fixes)
        r["param_set"] = pset
        out["runs"][label] = r
        print(f"{label:14s} n={r['n']:3d}  WR={r['WR']:5.1f}%  PF={r['PF']:5.2f}  "
              f"exp={r['expR']:+.3f}R [{lo:+.3f},{hi:+.3f}]  "
              f"P/L=${r['profit']:>+11,.0f}  ROI={r['roi_pct']:+7.2f}%  "
              f"pips={r['total_pips']:+8.1f}  maxDD={r['max_dd_pct']:5.2f}%")

    path = os.path.join(HERE, "results.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
