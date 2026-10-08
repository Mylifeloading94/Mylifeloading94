"""Re-run the account stats for the selected strategy with a FIXED 0.20 lot per trade.

P/L($) = R (net of spread) x stop distance (pips) x pip value of 0.20 lots in USD at fill time.
Pip value conversion uses the TradingView H1 close of the matching USD pair at the fill hour.
"""
import json, os, sys, bisect, statistics as st, datetime as dt
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
import engine as E, run as Rn

LOTS = 0.20
UNITS = 100_000 * LOTS          # FX / gold contract: 1 lot = 100k units (gold: 100 oz, pip 0.1 -> $10/lot)
SPX_USD_PER_POINT_PER_LOT = 1.0  # assumption: index CFD 1 lot = $1 per point (broker-dependent)
OUT = os.path.join(os.path.dirname(__file__), "out")
_cache = {}


def close_at(sym, ts):
    if sym not in _cache:
        b = E.load(sym, "1h"); _cache[sym] = ([x[0] for x in b], [x[4] for x in b])
    t, c = _cache[sym]; i = max(0, bisect.bisect_right(t, ts) - 1)
    return c[i]


def usd_per_quote(q, ts):
    if q == "USD": return 1.0
    if q in ("GBP", "AUD", "NZD", "EUR"): return close_at(q + "USD", ts)
    return 1.0 / close_at("USD" + q, ts)          # JPY, CHF, CAD


def pip_value_usd(sym, ts):
    if sym == "SPX500USD": return SPX_USD_PER_POINT_PER_LOT * LOTS
    if sym == "XAUUSD": return 10.0 * LOTS
    return E.pip(sym) * UNITS * usd_per_quote(sym[3:], ts)


def notional_usd(sym, ts, price):
    if sym == "SPX500USD": return price * SPX_USD_PER_POINT_PER_LOT * LOTS
    if sym == "XAUUSD": return price * 100 * LOTS
    base = sym[:3]
    return UNITS * (1.0 if base == "USD" else usd_per_quote(base, ts) if base != "EUR" else close_at("EURUSD", ts))


def main():
    raw = json.load(open(f"{OUT}/raw_trades.json"))
    best = json.load(open(f"{OUT}/selected.json"))
    EX = set(filter(None, os.environ.get("EXCLUDE", "").split(",")))
    tr = Rn.portfolio([t for t in raw[best["combo"]] if t["score"] >= best["tier"] and t["sym"] not in EX])
    for t in tr:
        pv = pip_value_usd(t["sym"], t["fill_t"])
        t["usd"] = t["r"] * t["risk_pips"] * pv
        t["risk_usd"] = t["risk_pips"] * pv
        t["notional"] = notional_usd(t["sym"], t["fill_t"], t["entry"])
    # concurrency / margin exposure
    ev = sorted([(t["fill_t"], 1, t["notional"]) for t in tr] + [(t["exit_t"], -1, t["notional"]) for t in tr])
    open_n = max_n = 0; open_not = max_not = 0.0
    for ts, k, nv in ev:
        open_n += k; open_not += k * nv; max_n = max(max_n, open_n); max_not = max(max_not, open_not)
    day = lambda ts: dt.datetime.fromtimestamp(ts, dt.UTC).date()
    res = {}
    for bal in (500, 1000):
        eq = bal; pk = bal; dd = 0; dd_usd = 0; daily = defaultdict(float); dn = defaultdict(lambda: [0, 0])
        for t in sorted(tr, key=lambda x: x["exit_t"]):
            eq += t["usd"]; pk = max(pk, eq); dd = max(dd, (pk - eq) / pk); dd_usd = max(dd_usd, pk - eq)
            d = day(t["exit_t"]); daily[d] += t["usd"]; dn[d][0 if t["r"] > 0 else 1] += 1
        weeks, months = defaultdict(lambda: [0.0, 0, 0]), defaultdict(lambda: [0.0, 0, 0, 0.0, 0.0])
        for t in tr:
            d = day(t["exit_t"]); w = weeks[d.isocalendar()[:2]]; m = months[(d.year, d.month)]
            w[0] += t["usd"]; w[1] += 1; w[2] += t["r"] > 0
            m[0] += t["usd"]; m[1] += 1; m[2] += t["r"] > 0
            if t["usd"] > 0: m[3] += t["usd"]
            else: m[4] -= t["usd"]
        dv = list(daily.values()); wins = [t["usd"] for t in tr if t["usd"] > 0]; losses = [t["usd"] for t in tr if t["usd"] <= 0]
        res[bal] = dict(end=eq, net=eq - bal, roi=(eq - bal) / bal, max_dd=dd, max_dd_usd=dd_usd,
                        pf=sum(wins) / -sum(losses), avg_win=st.mean(wins), avg_loss=st.mean(losses),
                        best_trade=max(t["usd"] for t in tr), worst_trade=min(t["usd"] for t in tr),
                        avg_daily=st.mean(dv), best_day=max(dv), worst_day=min(dv), active_days=len(dv),
                        risk_pct_median=st.median(t["risk_usd"] for t in tr) / bal,
                        risk_pct_max=max(t["risk_usd"] for t in tr) / bal,
                        weeks={f"{k[0]}-W{k[1]:02d}": (round(v[0], 2), v[1], v[2]) for k, v in sorted(weeks.items())},
                        months={f"{k[0]}-{k[1]:02d}": dict(pl=round(v[0], 2), n=v[1], wr=round(v[2] / v[1], 3),
                                pf=round(v[3] / v[4], 2) if v[4] else None, roi=round(v[0] / bal, 4)) for k, v in sorted(months.items())})
    summary = dict(lots=LOTS, trades=len(tr), wr=sum(t["r"] > 0 for t in tr) / len(tr),
                   net_usd=sum(t["usd"] for t in tr), avg_trade=st.mean(t["usd"] for t in tr),
                   risk_usd_median=st.median(t["risk_usd"] for t in tr), risk_usd_min=min(t["risk_usd"] for t in tr),
                   risk_usd_max=max(t["risk_usd"] for t in tr), max_open_positions=max_n, max_open_notional_usd=max_not,
                   by_symbol={s: round(sum(t["usd"] for t in tr if t["sym"] == s), 2) for s in sorted({t["sym"] for t in tr})},
                   accounts=res)
    json.dump(summary, open(f"{OUT}/fixed_lot_0.20" + ("_ex_" + "_".join(sorted(EX)) if EX else "") + ".json", "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in summary.items() if k != "accounts"}, indent=1, default=str))
    for b, v in res.items():
        print(b, {k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items() if k not in ("weeks", "months")})
        print("  months", v["months"])
        w = v["weeks"]; print("  weeks", len(w), "pos", sum(x[0] > 0 for x in w.values()), "best", max(w.items(), key=lambda kv: kv[1][0]), "worst", min(w.items(), key=lambda kv: kv[1][0]))


if __name__ == "__main__":
    main()
