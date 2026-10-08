"""Module 15 - live signals & alerts.

    python3 -m bbsniper.live --tf 5m                 # scan the watchlist on the latest stored bars
    python3 -m bbsniper.live --tf 1m --syms XAUUSD EURUSD --json

Reads the newest bars from backtest_tv/data (refresh them from TradingView first). Only a setup on
the LAST CLOSED bar that passes every filter is printed as a signal; otherwise: NO TRADE."""
import argparse, json, os
import numpy as np
from .config import cfg as make_cfg, INSTRUMENTS, pip
from .entries import signals
from .risk import passes
from . import liquidity as LQ, structure as ST

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest_tv", "out", "bbsniper")
REASON = [("bias", "HTF {dir}"), ("sweep", "Liquidity sweep / liquidity taken"), ("bbx", "Bollinger extreme / location"),
          ("mss", "{dir2} MSS"), ("rsi", "RSI confirmation"), ("rsi_div", "RSI divergence"), ("pctb", "%B confirmation"),
          ("adx", "ADX / volatility confirmation"), ("setup_trend", "Setup-TF trend aligned")]
SETUP_NAME = {"MR": "BB LIQUIDITY REVERSAL", "TC": "BB TREND CONTINUATION", "SB": "BB SQUEEZE BREAKOUT"}


def state(score):
    return "🟢 A+" if score >= 9 else "🟢 A" if score == 8 else "🟡 WATCH" if score == 7 else "🔴 NO TRADE"


def backtest_wr(sym, tf, setup):
    p = os.path.join(OUT, "results.json")
    if not os.path.exists(p): return None
    r = json.load(open(p)).get("winrate_lookup", {})
    return r.get(f"{sym}|{tf}|{setup}") or r.get(f"{sym}|{tf}")


def format_signal(s, risk_pct=1.0):
    d = pip(s["sym"]); nd = 2 if s["sym"] == "XAUUSD" else (3 if "JPY" in s["sym"] else 5)
    side = "BUY" if s["side"] == 1 else "SELL"; dirw = "bullish" if s["side"] == 1 else "bearish"
    tps = [s["entry"] + s["side"] * r * s["risk"] for r in (1, 2, 3)]
    wr = backtest_wr(s["sym"], s["tf"], s["setup"])
    lines = ["━━━━━━━━━━━━━━━━━━", "🔥 BB SNIPER SIGNAL", "━━━━━━━━━━━━━━━━━━", "",
             f"PAIR: {s['sym']}", f"DIRECTION: {side}", f"TIMEFRAME: {s['tf'].upper()}",
             f"BIAS: {'BULLISH' if s['bias'] == 1 else 'BEARISH' if s['bias'] == -1 else 'NEUTRAL'}",
             f"SETUP: {SETUP_NAME[s['setup']]}", f"SCORE: {s['score']}/10  ({state(s['score'])})",
             f"WIN-RATE BACKTEST: {wr if wr else 'n/a (sample too small)'}", "",
             f"ENTRY: {s['entry']:.{nd}f}", f"STOP LOSS: {s['stop']:.{nd}f}  ({s['risk'] / d:.1f} pips)"]
    lines += [f"TP{k + 1}: {tp:.{nd}f} — {k + 1}R" for k, tp in enumerate(tps)]
    lines += [f"RISK: {risk_pct:g}%", f"SESSION: {s['session']}", f"REGIME: {s['regime']}", "", "REASON:"]
    flags = dict(s, bias=s["bias"] != 0)
    for k, txt in REASON:
        if flags.get(k): lines.append("✓ " + txt.format(dir=dirw, dir2=dirw.capitalize()))
    return "\n".join(lines + ["", "━━━━━━━━━━━━━━━━━━"])


def market_alerts(ctx):
    """State alerts on the last closed bar: BB squeeze, liquidity sweep, market structure shift."""
    x, xi, c = ctx.x, ctx.xi, ctx.cfg; i = len(x["c"]) - 1; out = []
    if xi["bw_pct"][i] == xi["bw_pct"][i] and xi["bw_pct"][i] < c["squeeze_pct"]: out.append("BB SQUEEZE")
    for side, lo, hi in ((1, x["l"], x["h"]), (-1, -x["h"], -x["l"])):
        piv = [p for p in LQ.pivot_lows(lo, c["piv_liq"], c["piv_liq"]) if p[0] <= i - 1 and p[1] >= i - c["liq_lookback"]]
        if any(lo[i] < p[2] and min(lo[p[1] + 1:i]) >= p[2] for p in piv if p[1] + 1 < i):
            out.append("LIQUIDITY SWEEP " + ("(sell-side)" if side == 1 else "(buy-side)"))
        cl = x["c"] if side == 1 else -x["c"]
        ph, _ = ST.last_pivot_high(i + 1, LQ.pivot_highs(hi, c["piv_micro"], c["piv_micro"]))
        if ST.bullish_mss(cl, i, ph[i]): out.append("MARKET STRUCTURE SHIFT " + ("(bullish)" if side == 1 else "(bearish)"))
    return out


def scan_watchlist(tf, syms=INSTRUMENTS, c=None):
    c = c or make_cfg(); res = []
    for sym in syms:
        try: ctx, sigs = signals(sym, tf, c)
        except FileNotFoundError: res.append(dict(sym=sym, error="missing data")); continue
        last = len(ctx.x["c"]) - 1
        live = [s for s in sigs if s["i"] == last]
        res.append(dict(sym=sym, bar_t=int(ctx.x["t"][last] + ctx.sec), alerts=market_alerts(ctx),
                        signals=[s for s in live if passes(s, c)], watch=[s for s in live if not passes(s, c)]))
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--tf", default="5m"); ap.add_argument("--syms", nargs="*")
    ap.add_argument("--risk", type=float, default=1.0); ap.add_argument("--json", action="store_true"); a = ap.parse_args()
    res = scan_watchlist(a.tf, a.syms or INSTRUMENTS, make_cfg(risk_pct=a.risk))
    if a.json: print(json.dumps(res, default=lambda o: o.item() if isinstance(o, np.generic) else str(o), indent=1)); return
    any_sig = False
    for r in res:
        for s in r.get("signals", []): any_sig = True; print(format_signal(s, a.risk)); print()
    if not any_sig: print("NO TRADE")
    for r in res:
        if r.get("alerts"): print(f"[alert] {r['sym']}: " + ", ".join(r["alerts"]))


if __name__ == "__main__":
    main()
