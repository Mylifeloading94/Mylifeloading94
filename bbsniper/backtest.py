"""Module 12 - backtesting: signal generation + outcomes per symbol/TF, pair-level selection
(one position per pair, daily caps) and account-level portfolio simulation with real lot sizing."""
import functools
from .config import cfg as make_cfg, INSTRUMENTS
from .entries import signals
from .manage import simulate
from .risk import passes, position_size, DailyGuard

SIG_KEYS = ("bb_len", "bb_dev", "sl_buf_atr", "piv_liq", "piv_micro", "arm_window", "spread_mult", "tp_through_pips", "min_score")


@functools.lru_cache(maxsize=None)
def _run(sym, tf, key):
    c = make_cfg(**dict(key)); c["min_score"] = 0
    ctx, sigs = signals(sym, tf, c)
    for s in sigs: s.update(simulate(ctx, s, c))
    t0 = int(ctx.x["t"][250] + ctx.sec) if len(ctx.x["t"]) > 250 else None
    return sigs, t0, int(ctx.x["t"][-1] + ctx.sec)


def run(sym, tf, cfg):
    """All candidate signals (any score) with their simulated outcome, plus the usable window."""
    key = tuple((k, cfg[k]) for k in SIG_KEYS if k != "min_score")
    return _run(sym, tf, key)


def window(tf, cfg, syms=INSTRUMENTS):
    """Common evaluation window for a timeframe (latest start, earliest end across symbols)."""
    s = [run(x, tf, cfg) for x in syms]
    return max(w[1] for w in s if w[1]), min(w[2] for w in s)


def select_pair(sigs, cfg, t0, t1):
    """Pair-level trade list: filters, one open position at a time, daily caps (in R at the cfg risk)."""
    g = DailyGuard(cfg); out = []; busy = 0
    for s in sigs:
        if not (t0 <= s["t"] < t1) or s["t"] < busy or not passes(s, cfg): continue
        g.roll(s["t"], 100.0)
        if not g.allow(): continue
        g.opened(); g.closed(s["r"] * cfg["risk_pct"]); out.append(s); busy = s["exit_t"]
    return out


def account(tf, cfg, balance, risk_pct, t0, t1, syms=INSTRUMENTS):
    """Portfolio simulation across all symbols: chronological entries, exits realised before each
    new entry, per-account daily caps, lot sizing from current realised equity (compounding)."""
    cands = []
    for sym in syms:
        sigs, _, _ = run(sym, tf, cfg)
        cands += [s for s in sigs if t0 <= s["t"] < t1 and passes(s, cfg)]
    cands.sort(key=lambda s: (s["t"], -s["score"]))
    eq = balance; g = DailyGuard(cfg); open_ = {}; ledger = []; skipped_small = 0

    def realise(upto):
        nonlocal eq
        for sym in sorted([k for k, v in open_.items() if v["exit_t"] <= upto], key=lambda k: open_[k]["exit_t"]):
            tr = open_.pop(sym); g.roll(tr["exit_t"], eq); eq += tr["usd"]; g.closed(tr["usd"]); tr["equity"] = round(eq, 2)
            ledger.append(tr)

    for s in cands:
        realise(s["t"])
        if s["sym"] in open_: continue
        g.roll(s["t"], eq)
        if not g.allow(): continue
        lots, usd_risk = position_size(eq, risk_pct, s["entry"], s["stop"], s["sym"], s["t"], cfg)
        if lots == 0: skipped_small += 1; continue
        g.opened()
        open_[s["sym"]] = dict(s, lots=lots, usd_risk=round(usd_risk, 2), usd=round(s["r"] * usd_risk, 2))
    realise(float("inf"))
    ledger.sort(key=lambda x: x["exit_t"])
    return ledger, skipped_small
