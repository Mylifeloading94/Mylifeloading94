"""
Sniper-SMC backtest engine — FIXED COPY of the uploaded ``sniper_backtest.py``.

This file is a line-for-line port of the uploaded engine (diff it against
``sniper_backtest.py`` in this directory, which is preserved byte-identical to
the upload). Two categories of change, and nothing else:

A. FAITHFULNESS TO THE PACKAGE'S OWN FINAL CONFIG (applied to BOTH runs, so the
   A/B comparison stays apples-to-apples). The shipped ``sniper_backtest.py``
   __main__ block runs the *pre-final* parameter set (disp 0.6, TP2 2.0, wide
   sessions, no OTE gate), but the package's docstrings and
   ``smc_sniper/config.py`` state the validated config is
   "OTE 0.62-0.90 + prime KZ + disp 1.1xATR + TP 2.5R". We run that one, from
   ``sniper_smc.py`` constants and ``smc_sniper/config.py``:
       DISP_MULT 1.1 | SL_BUF 0.5 | TP1 1.0R/50% | TP2 2.5R
       OTE_BAND (0.62, 0.90) | RETRACE_BARS 8 | prime killzones only

B. THE FOUR FILL BUGS, each behind its own toggle in ``fixes`` so the cost of
   each can be measured in isolation:

   "fill"     Touch-fill -> trade-through fill.
              Shipped:  if swept=="bull" and ck["l"] <= zone_mid: entry=zone_mid
              A resting buy limit at P is only certainly filled if price trades
              THROUGH P. Merely printing a low equal to P is not a fill.
   "spread"   The shipped engine computes `entry_eff = entry + sign*sp` with the
              comment "pay spread on entry" and then NEVER USES IT — `entry_eff`
              appears exactly once in the whole file. tp1, tp2, the BE stop, the
              risk distance and the final mark-to-market `rr` all use raw
              `entry`, so the cost is computed and thrown away. Fixed: entry_eff
              is the entry price everywhere downstream.
   "sameber"  Same-bar TP1+SL. The shipped bar loop books the TP1 partial BEFORE
              it checks the stop, so a bar that traded through both scores as a
              partial win. Fixed: the stop is checked first.
   "denom"    Win rate denominator. Shipped: dec = wins+losses; scratches
              (`be_ct`) are dropped, inflating WR. Fixed: all closed trades count.

Everything else — entry sequence, HTF gate, sweep definition, MSS/displacement
test, zone construction, SL placement, TP ladder, time stop, bar iteration,
the non-overlap `last_exit` rule — is unchanged. No retuning, no reweighting.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PIP = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01, "USDCHF": 0.0001,
       "USDCAD": 0.0001, "AUDUSD": 0.0001, "NZDUSD": 0.0001, "GBPJPY": 0.01,
       "EURJPY": 0.01, "AUDJPY": 0.01, "EURGBP": 0.0001, "GBPCAD": 0.0001,
       "XAUUSD": 0.1, "NAS100": 1.0, "SPX500": 1.0}
SPREAD = {"EURUSD": 0.6, "GBPUSD": 0.9, "USDJPY": 0.7, "USDCHF": 1.0,
          "USDCAD": 1.2, "AUDUSD": 0.8, "NZDUSD": 1.2, "GBPJPY": 1.6,
          "EURJPY": 1.3, "AUDJPY": 1.4, "EURGBP": 1.0, "GBPCAD": 2.2,
          "XAUUSD": 2.5, "NAS100": 2.0, "SPX500": 1.5}  # pips
# $ per pip per 1.0 lot — smc_sniper/config.py INSTRUMENTS + trading_agent.MARKETS
PIP_VAL = {"EURUSD": 10.00, "GBPUSD": 10.00, "USDJPY": 6.70, "USDCHF": 10.00,
           "USDCAD": 7.30, "AUDUSD": 10.00, "NZDUSD": 10.00, "GBPJPY": 6.70,
           "EURJPY": 6.70, "AUDJPY": 6.70, "EURGBP": 12.50, "GBPCAD": 7.30,
           "XAUUSD": 1.00, "NAS100": 1.00, "SPX500": 1.00}

ALL_FIXES = ("fill", "spread", "sameber", "denom")


# --------------------------------------------------------------------------
# Indicators / structure — verbatim from the uploaded engine.
# --------------------------------------------------------------------------
def atr(bars, p=14):
    if len(bars) < 2:
        return 0
    trs = [max(bars[i]["h"] - bars[i]["l"],
               abs(bars[i]["h"] - bars[i - 1]["c"]),
               abs(bars[i]["l"] - bars[i - 1]["c"])) for i in range(1, len(bars))]
    return sum(trs[-p:]) / min(len(trs), p)


def swings(bars, s=3):
    out = []
    for i in range(s, len(bars) - s):
        hi = bars[i]["h"]; lo = bars[i]["l"]
        if all(bars[j]["h"] < hi for j in range(i - s, i)) and \
           all(bars[j]["h"] < hi for j in range(i + 1, i + s + 1)):
            out.append(("high", hi, i))
        if all(bars[j]["l"] > lo for j in range(i - s, i)) and \
           all(bars[j]["l"] > lo for j in range(i + 1, i + s + 1)):
            out.append(("low", lo, i))
    return sorted(out, key=lambda x: x[2])


def structure(bars, lb=120, s=3):
    r = bars[-lb:] if len(bars) >= lb else bars
    sw = swings(r, s)
    hs = [x for x in sw if x[0] == "high"]; ls = [x for x in sw if x[0] == "low"]
    if len(hs) >= 2 and len(ls) >= 2:
        hh = hs[-1][1] > hs[-2][1]; hl = ls[-1][1] > ls[-2][1]
        lh = hs[-1][1] < hs[-2][1]; ll = ls[-1][1] < ls[-2][1]
        if hh and hl: return "bullish"
        if lh and ll: return "bearish"
        if hh or hl: return "bullish"
        if lh or ll: return "bearish"
    return "ranging"


def hour_of(ms):
    return int((ms // 3600000) % 24)


def bars_before(bars, ts, k):
    out = [b for b in bars if b["t"] <= ts]
    return out[-k:] if len(out) > k else out


def in_prime_kz(ms):
    """sniper_smc.in_sniper_session / config.SESSIONS_UTC — the validated
    prime killzones: 07:00-08:59 and 12:30-14:30 UTC."""
    h = hour_of(ms); m = int((ms // 60000) % 60)
    if 7 <= h <= 8: return True
    if h == 12 and m >= 30: return True
    if h == 13: return True
    if h == 14 and m <= 30: return True
    return False


# --------------------------------------------------------------------------
# The engine.
# --------------------------------------------------------------------------
def sniper_bt(name, bars, lo_ts=None, hi_ts=None, fixes=(), disp_mult=1.1,
              sl_buf=0.5, tp1_R=1.0, tp1_close=0.5, tp2_R=2.5, be=True,
              max_hold=48, retrace_bars=8, require_htf=True, sess_only=True,
              ote_band=(0.62, 0.90)):
    """Full sniper sequence. ``fixes`` is any subset of ALL_FIXES."""
    fx = set(fixes)
    pip = PIP[name]; sp = SPREAD[name] * pip
    b15 = bars["15m"]; b4 = bars["4H"]

    lo_i = 0
    if lo_ts is not None:
        while lo_i < len(b15) and b15[lo_i]["t"] < lo_ts:
            lo_i += 1
    hi_i = len(b15)
    if hi_ts is not None:
        hi_i = 0
        while hi_i < len(b15) and b15[hi_i]["t"] <= hi_ts:
            hi_i += 1

    wins = losses = be_ct = 0
    gW = gL = R = 0.0
    trades = 0
    trade_log = []
    i = max(210, lo_i); last_exit = 0
    lim = min(hi_i, len(b15) - max_hold - 1)
    while i < lim:
        if i < last_exit:
            i += 1; continue
        bar = b15[i]; ts = bar["t"]
        if sess_only and not in_prime_kz(ts):
            i += 1; continue
        w = b15[max(0, i - 60):i + 1]
        if len(w) < 40:
            i += 1; continue
        a = atr(w[-20:])
        if a <= 0:
            i += 1; continue
        # --- HTF bias -----------------------------------------------------
        if require_htf:
            h4 = bars_before(b4, ts, 120)
            if len(h4) < 40:
                i += 1; continue
            bias4 = structure(h4)
            if bias4 == "ranging":
                i += 1; continue
        # --- 1) liquidity sweep of the prior 20-bar extreme, close back in --
        prior = w[-21:-1]; c = w[-1]
        swept = None; sweep_ext = None
        loh = min(b["l"] for b in prior); hih = max(b["h"] for b in prior)
        if c["l"] < loh and c["c"] > loh:
            swept = "bull"; sweep_ext = c["l"]
        elif c["h"] > hih and c["c"] < hih:
            swept = "bear"; sweep_ext = c["h"]
        if swept is None:
            i += 1; continue
        if require_htf:
            if swept == "bull" and bias4 != "bullish":
                i += 1; continue
            if swept == "bear" and bias4 != "bearish":
                i += 1; continue
        # --- 2) MSS: displacement candle breaks micro-structure -------------
        entry = sl = None
        sign = 1 if swept == "bull" else -1
        mss_j = None; fvg = None
        for j in range(i + 1, min(i + 5, len(b15))):
            cj = b15[j]; body = abs(cj["c"] - cj["o"])
            if body < disp_mult * a:
                continue
            if swept == "bull" and cj["c"] > cj["o"] and \
               cj["c"] > max(b["h"] for b in b15[j - 3:j]):
                mss_j = j; fvg = (b15[j - 1]["l"], b15[j - 1]["h"]); break
            if swept == "bear" and cj["c"] < cj["o"] and \
               cj["c"] < min(b["l"] for b in b15[j - 3:j]):
                mss_j = j; fvg = (b15[j - 1]["l"], b15[j - 1]["h"]); break
        if mss_j is None:
            i += 1; continue
        zone_mid = (fvg[0] + fvg[1]) / 2
        # --- OTE golden-pocket gate (sniper_smc.py / config.OTE_BAND) -------
        ote_depth = None
        if ote_band:
            leg = b15[i:mss_j + 1]
            leg_lo = min(b["l"] for b in leg); leg_hi = max(b["h"] for b in leg)
            if leg_hi > leg_lo:
                ote_depth = ((leg_hi - zone_mid) / (leg_hi - leg_lo) if swept == "bull"
                             else (zone_mid - leg_lo) / (leg_hi - leg_lo))
                if not (ote_band[0] <= ote_depth <= ote_band[1]):
                    i += 1; continue
        # --- 3) return-to-origin: limit fill at the zone midpoint -----------
        # BUG 1 (fill): shipped uses <= / >= (a touch fills). Honest fill
        # requires price to trade THROUGH the resting limit.
        filled_k = None
        for k in range(mss_j + 1, min(mss_j + 1 + retrace_bars, len(b15))):
            ck = b15[k]
            if swept == "bull":
                hit = ck["l"] < zone_mid if "fill" in fx else ck["l"] <= zone_mid
            else:
                hit = ck["h"] > zone_mid if "fill" in fx else ck["h"] >= zone_mid
            if hit:
                entry = zone_mid; filled_k = k; break
        if entry is None:
            i += 1; continue
        # --- 4) SL beyond the sweep extreme + buffer ------------------------
        sl = sweep_ext - sl_buf * a if swept == "bull" else sweep_ext + sl_buf * a

        # BUG 2 (spread): shipped computes entry_eff and never uses it.
        entry_eff = entry + sign * sp
        px = entry_eff if "spread" in fx else entry
        risk = abs(px - sl)
        if risk < max(6 * pip, sp * 3):
            i += 1; continue
        tp1 = px + risk * tp1_R * sign
        tp2 = px + risk * tp2_R * sign

        realR = 0.0; part = False; at_be = False
        outcome = None; exit_j = None; exit_px = None; reason = None
        for j in range(filled_k, min(filled_k + max_hold, len(b15))):
            hb = b15[j]

            def stop_hit():
                # evaluated against `sl` AS IT STANDS — the shipped engine
                # re-reads sl after a possible same-bar move to BE, and that
                # behaviour is preserved verbatim in both runs.
                return (sign == 1 and hb["l"] <= sl) or (sign == -1 and hb["h"] >= sl)

            def book_stop(jj):
                nonlocal realR, outcome, exit_j, exit_px, reason
                realR += 0.0 if (part and at_be) else -1.0 * (1 - (tp1_close if part else 0))
                outcome = "done"; exit_j = jj; exit_px = sl
                reason = "BE stop" if (part and at_be) else ("SL after TP1" if part else "SL")

            # BUG 3 (sameber): shipped books the TP1 partial BEFORE checking the
            # stop, so a bar that traded through both scores as a partial win.
            # Fixed: the initial stop is tested first, on the same bar.
            if "sameber" in fx and stop_hit():
                book_stop(j); break

            if be and not part and ((sign == 1 and hb["h"] >= tp1) or
                                    (sign == -1 and hb["l"] <= tp1)):
                realR += tp1_R * tp1_close; part = True; sl = px; at_be = True
            if stop_hit():
                book_stop(j); break
            if (sign == 1 and hb["h"] >= tp2) or (sign == -1 and hb["l"] <= tp2):
                realR += tp2_R * (1 - (tp1_close if part else 0))
                outcome = "done"; exit_j = j; exit_px = tp2
                reason = "TP2" if part else "TP2 (no TP1 partial)"
                break
        if outcome is None:
            exit_j = min(filled_k + max_hold, len(b15) - 1)
            lp = b15[exit_j]["c"]
            realR += ((lp - px) / risk) * sign * (1 - (tp1_close if part else 0))
            exit_px = lp; reason = "time stop"

        trades += 1; R += realR
        if realR > 0.05:
            wins += 1; gW += realR
        elif realR < -0.05:
            losses += 1; gL += abs(realR)
        else:
            be_ct += 1
        trade_log.append({
            "symbol": name,
            "direction": "long" if sign == 1 else "short",
            "entry_ts": b15[filled_k]["t"], "exit_ts": b15[exit_j]["t"],
            "entry": px, "raw_entry": entry, "sl_initial": (sweep_ext - sl_buf * a
                                                            if swept == "bull"
                                                            else sweep_ext + sl_buf * a),
            "tp1": tp1, "tp2": tp2, "exit_px": exit_px,
            "risk_price": risk, "risk_pips": risk / pip,
            "R": realR, "reason": reason, "partial": part,
            "ote_depth": ote_depth, "session_hour": hour_of(b15[filled_k]["t"]),
        })
        last_exit = filled_k + 1
        i = last_exit

    # BUG 4 (denom): shipped drops scratches from the win-rate denominator.
    dec = (wins + losses + be_ct) if "denom" in fx else (wins + losses)
    wr = wins / dec * 100 if dec else 0.0
    pf = gW / gL if gL > 0 else (999.0 if gW > 0 else 0.0)
    return {"n": trades, "WR": wr, "PF": pf, "wins": wins, "losses": losses,
            "scratches": be_ct, "expR": (R / trades) if trades else 0.0,
            "totR": R, "trades": trade_log}


def load_data(path=None):
    path = path or os.path.join(HERE, "data_90d.json")
    with open(path) as fh:
        return json.load(fh)
