"""
Sniper-SMC — high-intelligence Smart Money Concepts strategy (v1).
====================================================================
STATUS: EXPERIMENTAL — NOT validated for live trading.
A first backtest showed 66-82% win rates, but that was a FILL ARTIFACT.
Re-running with honest fills (trade-through required, spread paid, same-bar
TP+SL counted as a loss) collapsed the edge: AUDJPY 82%->56%, USDCAD 77%->54%,
GBPCAD/XAUUSD/EURUSD flipped to LOSING. Only AUDJPY (55.6% WR, PF 1.58) and
USDJPY (small sample) survived, and both are below Fable's >=25-trade bar.
DO NOT trade this live until it re-qualifies at PF>1.3 on 25+ honest-fill
trades per pair. Sample sizes here (9-21 trades/90d) are too small to rank.

The sniper entry is the full institutional sequence — NOT a naive pullback:
  1. HTF BIAS      : 4H market structure (BOS/CHoCH via fractal swings).
  2. LIQUIDITY SWEEP: a 15M candle takes the prior 20-bar extreme and CLOSES
                      back inside (stop-hunt of resting liquidity).
  3. MSS           : within 4 bars, a displacement candle (body >= 0.6*ATR)
                      breaks the micro-structure in the sweep-reversal direction.
  4. RETURN-TO-ORIGIN: price retraces into the FVG / order block left by the
                      displacement — LIMIT entry at the zone midpoint (sniper fill).
  5. SL beyond the sweep extreme + 0.5*ATR buffer; TP1 +1.0R (close 50% -> BE),
     TP2 +2.0R runner. Time-stop 48 bars.

Backtest ranking (win rate / profit factor / OOS-stable):
  AUDJPY 81.8% / 4.41 ✅   USDCAD 76.9% / 2.91 ✅   GBPCAD 66.7% / 2.30 ✅
  XAUUSD 66.7% / 1.63 ✅   EURUSD 66.7% / 1.67 ✅
Portfolio of the top 4: 57 trades, +21R over 90 days, positive in both halves.

Honest caveats:
  • Sniper = selective: ~1 trade / pair / week. Do not expect frequent signals.
  • Small per-pair samples (9-18 trades/90d). Validate live on demo; the
    go-live gate is PF > 1.3 out-of-sample, not a win-rate number.
  • Sessions only (07:00-10:45 / 12:30-15:45 UTC). Risk 0.5-1% (hard-capped).
"""
import time
import trading_agent as ta

# HONEST-FILL backtest survivors only (still small-sample — demo validation required).
# Numbers below are the HARDENED results (trade-through fills + spread + same-bar=loss).
SNIPER_PAIRS = ["AUDJPY", "USDCAD"]   # the only two with PF >= 1 on honest fills
PAIR_STATS = {  # 90d HONEST-fill backtest (WR%, PF) — treat as unproven hypotheses
    "AUDJPY": (55.6, 1.58), "USDCAD": (53.8, 1.04),
}

# Parameters (validated)
DISP_MULT   = 0.6    # displacement body >= 0.6*ATR
SL_BUF      = 0.5    # SL beyond sweep extreme by 0.5*ATR
TP1_R       = 1.0
TP1_CLOSE   = 0.50
TP2_R       = 2.0
RETRACE_BARS = 8     # zone must be mitigated within 8 bars of the MSS
MAX_RISK_PCT = 0.01
HARD_MAX_LOTS = 0.50


def in_sniper_session(now=None):
    import datetime
    n = now or datetime.datetime.utcnow()
    h, m = n.hour, n.minute
    if 7 <= h <= 9: return True
    if h == 10 and m <= 45: return True
    if h == 12 and m >= 30: return True
    if 13 <= h <= 14: return True
    if h == 15 and m <= 45: return True
    return False


def safe_lots(risk_pips, pip_val, balance):
    if risk_pips <= 0 or pip_val <= 0: return 0.01
    raw = (balance * MAX_RISK_PCT) / (risk_pips * pip_val)
    return round(max(0.01, min(raw, HARD_MAX_LOTS)), 2)


def _htf_bias(headers, cfg):
    b4 = ta.fetch_bars(headers, cfg["id"], "4H", 60)
    if len(b4) < 40: return None
    return ta.market_structure(b4, 120, 3)


def analyze_sniper(name, cfg, headers):
    """
    Detect a live sniper setup. Because entry is a LIMIT at the FVG midpoint,
    this returns a PENDING setup (limit order params) when the sweep+MSS have
    formed and price has not yet mitigated the zone — OR a ready market entry
    if price is currently in the zone. Returns None if no sequence present.
    """
    pip = cfg["pip"]
    b15 = ta.fetch_bars(headers, cfg["id"], "15m", 6)
    if len(b15) < 60: return None
    bias4 = ta.market_structure(ta.fetch_bars(headers, cfg["id"], "4H", 60), 120, 3)
    if bias4 == "ranging": return None
    w = b15[-60:]
    a = ta.atr(w[-20:])
    if a <= 0: return None

    # Look back over the last ~12 bars for a completed sweep -> MSS, zone unmitigated
    n = len(w)
    for s_idx in range(n - 12, n - 2):
        prior = w[s_idx-20:s_idx] if s_idx >= 20 else None
        if not prior: continue
        c = w[s_idx]
        loh = min(b["l"] for b in prior); hih = max(b["h"] for b in prior)
        swept = None; sweep_ext = None
        if c["l"] < loh and c["c"] > loh: swept, sweep_ext = "bull", c["l"]
        elif c["h"] > hih and c["c"] < hih: swept, sweep_ext = "bear", c["h"]
        if swept is None: continue
        if swept == "bull" and bias4 != "bullish": continue
        if swept == "bear" and bias4 != "bearish": continue
        # MSS within next 4 bars
        for j in range(s_idx+1, min(s_idx+5, n)):
            cj = w[j]; body = abs(cj["c"] - cj["o"])
            if body < DISP_MULT * a: continue
            if swept == "bull" and cj["c"] > cj["o"] and cj["c"] > max(b["h"] for b in w[j-3:j]):
                fvg = (w[j-1]["l"], w[j-1]["h"]); sign = 1
            elif swept == "bear" and cj["c"] < cj["o"] and cj["c"] < min(b["l"] for b in w[j-3:j]):
                fvg = (w[j-1]["l"], w[j-1]["h"]); sign = -1
            else:
                continue
            zone_mid = round((fvg[0] + fvg[1]) / 2, 5)
            # zone must not already be mitigated between MSS and now (still pending/fresh)
            price = w[-1]["c"]
            bars_since = n - 1 - j
            if bars_since > RETRACE_BARS: continue  # stale
            if swept == "bull":
                sl = round(sweep_ext - SL_BUF * a, 5)
                if price <= zone_mid * 1.0005:   # in/near zone -> ready
                    entry = zone_mid
                    risk = abs(entry - sl)
                    if risk < max(6*pip, 3*pip): continue
                    return _mk(name, "bullish", entry, sl, risk, sign, pip, cfg, b15, zone_mid, "ready")
                else:
                    return _mk(name, "bullish", zone_mid, sl, abs(zone_mid-sl), sign, pip, cfg, b15, zone_mid, "pending")
            else:
                sl = round(sweep_ext + SL_BUF * a, 5)
                if price >= zone_mid * 0.9995:
                    entry = zone_mid
                    risk = abs(entry - sl)
                    if risk < max(6*pip, 3*pip): continue
                    return _mk(name, "bearish", entry, sl, risk, sign, pip, cfg, b15, zone_mid, "ready")
                else:
                    return _mk(name, "bearish", zone_mid, sl, abs(zone_mid-sl), sign, pip, cfg, b15, zone_mid, "pending")
    return None


def _mk(name, direction, entry, sl, risk, sign, pip, cfg, b15, zone_mid, state):
    tp1 = round(entry + risk*TP1_R*sign, 5)
    tp2 = round(entry + risk*TP2_R*sign, 5)
    wr, pf = PAIR_STATS.get(name, (0, 0))
    return {
        "name": name, "direction": direction, "state": state,
        "entry": round(entry, 5), "sl": round(sl, 5), "tp1": tp1, "tp2": tp2,
        "zone_mid": zone_mid, "risk_pips": round(risk/pip, 1),
        "bt_wr": wr, "bt_pf": pf, "cfg": cfg, "bars_15m": b15,
    }


def scan_sniper(headers):
    """Scan validated pairs during session; return sniper setups (ready first)."""
    if not in_sniper_session():
        return []
    out = []
    for name in SNIPER_PAIRS:
        cfg = ta.MARKETS[name]
        try:
            s = analyze_sniper(name, cfg, headers)
            if s: out.append(s)
        except Exception as e:
            print(f"  {name} err {e}")
        time.sleep(0.3)
    out.sort(key=lambda x: (0 if x["state"] == "ready" else 1, -x["bt_pf"]))
    return out


if __name__ == "__main__":
    import datetime
    headers, account_id, balance = ta.auth()
    print(f"Sniper-SMC scan {datetime.datetime.utcnow().strftime('%H:%M UTC')} | "
          f"session={in_sniper_session()} | bal ${balance:,.2f}")
    for s in scan_sniper(headers):
        print(f"  {s['state'].upper():7} {s['name']} {s['direction'].upper()} "
              f"entry {s['entry']} SL {s['sl']} TP1 {s['tp1']} TP2 {s['tp2']} "
              f"({s['risk_pips']}p) [bt {s['bt_wr']}%/{s['bt_pf']}]")
