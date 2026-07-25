"""
Backtest harness for hp_trading_bot.py — spec-faithful, honest fills.

Runs the High-Probability bot over REAL historical data from a configurable
start (default 2026-01-01) to today, across all 7 markets, and prints + saves
full statistics.

DATA (must be real — this script never fabricates prices):
  1. If ./data/<SYMBOL>_M15.csv exists (cols: time,open,high,low,close), it is used.
  2. Otherwise it fetches M15 from TradeLocker using env vars
     TL_EMAIL, TL_PASSWORD, TL_SERVER, TL_ACCOUNT_ID (same as the live bot).
Higher timeframes (H1/H4/D1) are resampled from M15.

WARMUP: the D1 200-EMA bias needs ~200 daily bars BEFORE the start date, so the
fetch reaches back ~300 calendar days before `start`. Without that warmup the
first months would have no valid D1 bias and would be silently skipped.

Usage:
    python3 hp_bot_backtest.py                 # 2026-01-01 -> today, high_probability
    python3 hp_bot_backtest.py 2026-01-01 balanced
"""
import os
import sys
import json
import datetime as dt
import numpy as np
import pandas as pd

import hp_trading_bot as bot

START_BALANCE = 100_000.0
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_JSON = os.path.join(os.path.dirname(__file__), "hp_bot_backtest_results.json")


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def load_csv(symbol):
    p = os.path.join(DATA_DIR, f"{symbol}_M15.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time")[["open", "high", "low", "close"]].sort_index()
    return df[~df.index.duplicated(keep="first")]


def fetch_tradelocker(symbol, start, end):
    """Chunked M15 fetch from TradeLocker. Returns DataFrame or raises."""
    import requests
    BASE = "https://demo.tradelocker.com/backend-api"
    email = os.environ["TL_EMAIL"]
    pw = os.environ["TL_PASSWORD"]
    server = os.environ.get("TL_SERVER", "GenFX")
    acct = os.environ.get("TL_ACCOUNT_ID", "2265464")
    tok = requests.post(f"{BASE}/auth/jwt/token",
                        json={"email": email, "password": pw, "server": server},
                        timeout=20).json()
    access = tok["accessToken"]
    headers = {"Authorization": f"Bearer {access}", "accept": "application/json",
               "accNum": str(acct)}
    instruments = requests.get(f"{BASE}/trade/accounts/{acct}/instruments",
                               headers=headers, timeout=20).json()["d"]["instruments"]
    iid = None
    route = None
    for ins in instruments:
        if ins["name"] == symbol:
            iid = ins["tradableInstrumentId"]
            for r in ins.get("routes", []):
                if r.get("type") == "INFO":
                    route = r["id"]
            break
    if iid is None:
        raise RuntimeError(f"{symbol} not found on broker")
    frames = []
    cur = start
    step = dt.timedelta(days=20)
    while cur < end:
        nxt = min(cur + step, end)
        params = {"tradableInstrumentId": iid, "routeId": route, "resolution": "15m",
                  "from": int(cur.timestamp() * 1000), "to": int(nxt.timestamp() * 1000)}
        resp = requests.get(f"{BASE}/trade/history", headers=headers, params=params, timeout=30).json()
        bars = resp.get("d", {}).get("barDetails", [])
        for b in bars:
            frames.append((b["t"], b["o"], b["h"], b["l"], b["c"]))
        cur = nxt
    if not frames:
        raise RuntimeError(f"no bars returned for {symbol}")
    df = pd.DataFrame(frames, columns=["t", "open", "high", "low", "close"])
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df[["open", "high", "low", "close"]].sort_index()
    return df[~df.index.duplicated(keep="first")]


def get_data(symbol, start, end):
    df = load_csv(symbol)
    src = "csv"
    if df is None:
        df = fetch_tradelocker(symbol, start, end)
        src = "tradelocker"
    return df, src


def resample(m15, rule):
    o = m15["open"].resample(rule).first()
    h = m15["high"].resample(rule).max()
    l = m15["low"].resample(rule).min()
    c = m15["close"].resample(rule).last()
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c}).dropna()


def closed_slice(df, ts):
    """Bars that are fully CLOSED as of ts (no lookahead)."""
    return df[df.index < ts]


# ----------------------------------------------------------------------------
# Simulation
# ----------------------------------------------------------------------------
def simulate(cfg, start, end):
    warm = start - dt.timedelta(days=300)
    data = {}
    print(f"Loading data for {len(bot.MARKETS)} markets ({warm.date()} -> {end.date()}) ...")
    for sym in bot.MARKETS:
        m15, src = get_data(sym, warm, end)
        data[sym] = {
            "m15": m15,
            "h1": resample(m15, "1h"),
            "h4": resample(m15, "4h"),
            "d1": resample(m15, "1D"),
        }
        print(f"  {sym}: {len(m15)} M15 bars via {src}")

    # master chronological timeline over the trading window
    ts_all = sorted(set().union(*[
        set(d["m15"].index[(d["m15"].index >= start) & (d["m15"].index <= end)])
        for d in data.values()]))
    print(f"Simulating {len(ts_all)} M15 timestamps ...")

    state = {"balance": START_BALANCE, "open": [], "trades_today": 0,
             "daily_loss": 0.0, "weekly_loss": 0.0, "consecutive_losses": 0,
             "day": None, "week": None}
    trades = []
    equity_curve = []

    # index pointer per symbol for fast bar lookup
    m15idx = {s: data[s]["m15"] for s in bot.MARKETS}

    for ts in ts_all:
        d = ts.date()
        wk = ts.isocalendar()[:2]
        if state["day"] != d:
            state["day"] = d
            state["trades_today"] = 0
            state["daily_loss"] = 0.0
        if state["week"] != wk:
            state["week"] = wk
            state["weekly_loss"] = 0.0

        # 1) manage open trades on this bar
        still_open = []
        for tr in state["open"]:
            bar = m15idx[tr["symbol"]]
            if ts not in bar.index:
                still_open.append(tr)
                continue
            row = bar.loc[ts]
            outcome = _update_trade(tr, row)
            if outcome is None:
                still_open.append(tr)
            else:
                r_mult, reason, exit_px = outcome
                pnl = r_mult * tr["risk_dollars"]
                state["balance"] += pnl
                state["daily_loss"] += pnl / state["balance"] if pnl < 0 else 0
                state["weekly_loss"] += pnl / state["balance"] if pnl < 0 else 0
                state["consecutive_losses"] = state["consecutive_losses"] + 1 if r_mult < 0 else 0
                tr.update({"exit_time": str(ts), "exit_price": exit_px, "r_multiple": round(r_mult, 3),
                           "pnl": round(pnl, 2), "exit_reason": reason, "balance_after": round(state["balance"], 2)})
                trades.append(tr)
        state["open"] = still_open
        equity_curve.append((str(ts), round(state["balance"] + sum(0 for _ in state["open"]), 2)))

        # 2) look for new entries (one position per symbol at a time)
        open_syms = {o["symbol"] for o in state["open"]}
        for sym in bot.MARKETS:
            if sym in open_syms:
                continue
            bar = m15idx[sym]
            if ts not in bar.index:
                continue
            i = bar.index.get_loc(ts)
            if i < 20:
                continue
            m15_slice = bar.iloc[:i + 1]
            d1 = closed_slice(data[sym]["d1"], ts)
            h4 = closed_slice(data[sym]["h4"], ts)
            h1 = closed_slice(data[sym]["h1"], ts)
            if len(d1) < cfg.ema_slow + 2:
                continue
            trade = bot.evaluate(sym, d1, h4, h1, m15_slice, cfg, ts, spread_pips=0.0)
            if trade is None:
                continue
            allowed, reason = bot.risk_gate(trade, state, cfg)
            if not allowed:
                continue
            lots, risk_dollars = bot.position_size(sym, trade, state["balance"], cfg, state["consecutive_losses"])
            trade.update({"lots": lots, "risk_dollars": risk_dollars, "entry_time": str(ts),
                          "tp1_hit": False, "be": False})
            state["open"].append(trade)
            state["trades_today"] += 1

    return trades, equity_curve, state


def _update_trade(tr, row):
    """Bar-by-bar exit sim with TP1(50% @1R)+breakeven+TP2(@2R). Conservative:
    if both stop and target are inside the same bar, assume stop hit first.
    Returns (r_multiple, reason, exit_price) or None if still open."""
    d = tr["direction"]
    hi, lo = row["high"], row["low"]
    entry, stop, tp1, tp2 = tr["entry"], tr["stop"], tr["tp1"], tr["tp2"]
    risk = tr["risk"]
    # current effective stop (breakeven after TP1)
    eff_stop = entry if tr["be"] else stop

    hit_stop = lo <= eff_stop if d == 1 else hi >= eff_stop
    hit_tp1 = (hi >= tp1 if d == 1 else lo <= tp1)
    hit_tp2 = (hi >= tp2 if d == 1 else lo <= tp2)

    if not tr["tp1_hit"]:
        if hit_stop:
            return (-1.0, "stop", eff_stop)
        if hit_tp2:                       # gap straight through both
            return (1.5, "tp2", tp2)      # 0.5*1R + 0.5*2R
        if hit_tp1:
            tr["tp1_hit"] = True
            tr["be"] = True               # move to breakeven
            return None
        return None
    else:
        # half runner: BE stop or TP2
        if (lo <= entry if d == 1 else hi >= entry):
            return (0.5, "tp1+be", entry)  # 0.5*1R + 0.5*0
        if hit_tp2:
            return (1.5, "tp2", tp2)
        return None


# ----------------------------------------------------------------------------
# Statistics (spec section 15)
# ----------------------------------------------------------------------------
def stats(trades, equity_curve, cfg, start, end):
    if not trades:
        return {"error": "no trades taken in window", "window": f"{start.date()}..{end.date()}"}
    df = pd.DataFrame(trades)
    wins = df[df["r_multiple"] > 0]
    losses = df[df["r_multiple"] <= 0]
    gross_win = wins["pnl"].sum()
    gross_loss = abs(losses["pnl"].sum())
    eq = pd.Series([b for _, b in equity_curve])
    peak = eq.cummax()
    dd = ((eq - peak) / peak).min() if len(eq) else 0.0

    def grp(col):
        g = df.groupby(col)
        return {str(k): {"trades": int(len(v)),
                          "win_rate": round((v["r_multiple"] > 0).mean() * 100, 1),
                          "avg_R": round(v["r_multiple"].mean(), 3),
                          "pnl": round(v["pnl"].sum(), 2)} for k, v in g}

    df["month"] = pd.to_datetime(df["exit_time"]).dt.to_period("M").astype(str)
    out = {
        "window": f"{start.date()}..{end.date()}",
        "mode": cfg.mode,
        "start_balance": START_BALANCE,
        "end_balance": round(equity_curve[-1][1], 2) if equity_curve else START_BALANCE,
        "return_pct": round((equity_curve[-1][1] / START_BALANCE - 1) * 100, 2) if equity_curve else 0,
        "total_trades": int(len(df)),
        "win_rate": round((df["r_multiple"] > 0).mean() * 100, 1),
        "loss_rate": round((df["r_multiple"] <= 0).mean() * 100, 1),
        "avg_win_R": round(wins["r_multiple"].mean(), 3) if len(wins) else 0,
        "avg_loss_R": round(losses["r_multiple"].mean(), 3) if len(losses) else 0,
        "avg_R": round(df["r_multiple"].mean(), 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "max_drawdown_pct": round(dd * 100, 2),
        "by_pair": grp("symbol"),
        "by_score": grp("score"),
        "by_session": grp("session"),
        "by_month": grp("month"),
    }
    return out


def main():
    start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-01-01", tz="UTC")
    mode = sys.argv[2] if len(sys.argv) > 2 else "high_probability"
    end = pd.Timestamp(dt.datetime.utcnow(), tz="UTC")
    cfg = bot.BotConfig(mode=mode)

    trades, equity, state = simulate(cfg, start, end)
    result = stats(trades, equity, cfg, start, end)
    json.dump({"summary": result, "trades": trades}, open(OUT_JSON, "w"), indent=2, default=str)

    print("\n" + "=" * 60)
    print(f" HP BOT BACKTEST — {result.get('window')} — mode={mode}")
    print("=" * 60)
    for k in ("total_trades", "win_rate", "loss_rate", "profit_factor", "avg_R",
              "avg_win_R", "avg_loss_R", "max_drawdown_pct", "return_pct",
              "start_balance", "end_balance"):
        if k in result:
            print(f"  {k:18}: {result[k]}")
    for dim in ("by_pair", "by_score", "by_session", "by_month"):
        if dim in result:
            print(f"\n  {dim}:")
            for kk, vv in result[dim].items():
                print(f"    {kk:18} {vv}")
    print(f"\nSaved -> {OUT_JSON}")


if __name__ == "__main__":
    main()
