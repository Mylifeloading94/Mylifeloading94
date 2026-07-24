"""
90-day backtest for "Mylifeloading Portfolio" (Edge Model v3 STRICT) across
all 6 live instruments (XAUUSD, CADJPY, EURUSD, GBPCAD, GBPUSD, NZDUSD),
using each pair's locked live params from mylifeloading_portfolio_live.py.

Fetches 15m bars from TradeLocker (same source as live), finds every
BOS+FVG+retest signal in the window (not just the latest, unlike live),
simulates each trade bar-by-bar against its stop/target, and pools all
trades chronologically onto one $100k account at 2% risk/trade to match
the methodology described in mylifeloading_portfolio_live.py's docstring.

Run:
    python3 mylifeloading_portfolio_backtest.py
"""
import os
import sys
import datetime
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import live_monitor as lm
import mylifeloading_portfolio_live as mp

STARTING_BALANCE = 100_000.0
RISK_PCT = mp.RISK_PCT
MAX_HOLD_BARS = mp.MAX_HOLD_BARS
BACKTEST_DAYS = 90


def find_all_signals(df, params):
    """Same BOS+FVG+retest scan as mp.find_latest_signal, but collects every
    signal in the window instead of only the most recent one."""
    swing_left, swing_right = params["swing_left"], params["swing_right"]
    fixed_R = params["fixed_R"]
    min_fvg_atr = params["min_fvg_atr"]
    confirm_body_frac = params["confirm_body_frac"]
    max_risk_atr = params["max_risk_atr"]

    df = df.copy()
    df["atr"] = mp.atr(df, 14)
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    atr_ = df["atr"].values
    n = len(df)

    highs, lows = mp.find_fractals(df, swing_left, swing_right)
    piv = sorted([(ci, p, "H") for _, ci, p in highs] + [(ci, p, "L") for _, ci, p in lows])

    signals = []
    last_bos_i = -1
    piv_ptr = 0
    cur_high_pivot = cur_low_pivot = None
    cur_high_origin = cur_low_origin = None
    last_piv_price = {"H": None, "L": None}

    busy_until = 0
    i = swing_left + swing_right + 5
    while i < n - 1:
        while piv_ptr < len(piv) and piv[piv_ptr][0] <= i:
            ci, p, typ = piv[piv_ptr]
            if typ == "H":
                cur_high_origin = last_piv_price["L"]
                cur_high_pivot = p
            else:
                cur_low_origin = last_piv_price["H"]
                cur_low_pivot = p
            last_piv_price[typ] = p
            piv_ptr += 1

        if i < busy_until or np.isnan(atr_[i]) or atr_[i] <= 0:
            i += 1
            continue

        direction = origin = None
        if cur_high_pivot is not None and c[i] > cur_high_pivot and i > last_bos_i:
            direction, origin = 1, cur_low_origin
        elif cur_low_pivot is not None and c[i] < cur_low_pivot and i > last_bos_i:
            direction, origin = -1, cur_high_origin
        if direction is None or origin is None:
            i += 1
            continue

        bos_i = i
        fvg = None
        for k in range(bos_i, max(1, bos_i - 6), -1):
            if k - 2 < 0:
                continue
            if direction == 1 and h[k - 2] < l[k]:
                fvg = {"top": l[k], "bottom": h[k - 2]}
                break
            if direction == -1 and l[k - 2] > h[k]:
                fvg = {"top": l[k - 2], "bottom": h[k]}
                break
        if fvg is None:
            last_bos_i = bos_i
            i += 1
            continue
        if (fvg["top"] - fvg["bottom"]) < min_fvg_atr * atr_[bos_i]:
            last_bos_i = bos_i
            i += 1
            continue

        entry_i = None
        for j in range(bos_i + 1, min(n, bos_i + 1 + mp.RETEST_K)):
            bar_range = h[j] - l[j]
            body_ok = bar_range > 0 and abs(c[j] - o[j]) / bar_range >= confirm_body_frac
            if direction == 1:
                touched = l[j] <= fvg["top"]
                confirm = c[j] > o[j] and c[j] > fvg["top"] and body_ok
            else:
                touched = h[j] >= fvg["bottom"]
                confirm = c[j] < o[j] and c[j] < fvg["bottom"] and body_ok
            if direction == 1 and l[j] < origin:
                break
            if direction == -1 and h[j] > origin:
                break
            if touched and confirm:
                entry_i = j
                break
        last_bos_i = bos_i
        if entry_i is None:
            i += 1
            continue
        if not mp.in_session(df.index[entry_i]):
            i = entry_i + 1
            continue

        entry_price = c[entry_i]
        stop = origin - mp.STOP_BUF_ATR * atr_[entry_i] if direction == 1 else origin + mp.STOP_BUF_ATR * atr_[entry_i]
        risk = entry_price - stop if direction == 1 else stop - entry_price
        if risk <= 0:
            i = entry_i + 1
            continue
        if risk > max_risk_atr * atr_[entry_i]:
            i = entry_i + 1
            continue

        signals.append({
            "entry_i": entry_i, "entry_time": df.index[entry_i], "dir": direction,
            "bar_entry": entry_price, "stop": stop, "r_unit": risk, "target_R": fixed_R,
        })
        busy_until = entry_i + 1
        i = entry_i + 1

    return signals, df


def simulate_trade(df, sig):
    """Walk forward from entry, bar-by-bar, checking stop/target against
    high/low first (stop-priority on ambiguous bars), else 24h time-stop
    exit at that bar's close."""
    direction = sig["dir"]
    entry_i = sig["entry_i"]
    entry_price = sig["bar_entry"]
    stop = sig["stop"]
    r_unit = sig["r_unit"]
    target = entry_price + sig["target_R"] * r_unit if direction == 1 else entry_price - sig["target_R"] * r_unit

    h, l, c = df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    deadline_i = min(n - 1, entry_i + MAX_HOLD_BARS)

    for j in range(entry_i + 1, deadline_i + 1):
        if direction == 1:
            hit_stop = l[j] <= stop
            hit_target = h[j] >= target
        else:
            hit_stop = h[j] >= stop
            hit_target = l[j] <= target
        if hit_stop and hit_target:
            # ambiguous same-bar hit -- assume stop first (conservative)
            return -1.0, df.index[j], "stop(ambiguous)", j
        if hit_stop:
            return -1.0, df.index[j], "stop", j
        if hit_target:
            return sig["target_R"], df.index[j], "target", j

    exit_price = c[deadline_i]
    r_multiple = (exit_price - entry_price) / r_unit if direction == 1 else (entry_price - exit_price) / r_unit
    return r_multiple, df.index[deadline_i], "time_stop", deadline_i


def main():
    env = lm.load_env()
    headers = lm.auth(env)
    account_id = env["TL_ACCOUNT_ID"]
    instruments = lm.get_instruments(headers, account_id)

    all_trades = []
    per_instrument = {}

    for name, cfg in mp.INSTRUMENTS.items():
        if name not in instruments:
            print(f"{name}: not found on broker, skipping")
            continue
        print(f"Fetching {BACKTEST_DAYS}d of 15m bars for {name}...")
        df = mp.fetch_bars(headers, instruments[name], days=BACKTEST_DAYS)
        signals, df = find_all_signals(df, cfg["params"])
        trades = []
        busy_until_i = -1
        skipped = 0
        for sig in signals:
            if sig["entry_i"] <= busy_until_i:
                # one position at a time per instrument, same as live
                skipped += 1
                continue
            r_multiple, exit_time, exit_reason, exit_i = simulate_trade(df, sig)
            direction = sig["dir"]
            target_price = (sig["bar_entry"] + sig["target_R"] * sig["r_unit"] if direction == 1
                             else sig["bar_entry"] - sig["target_R"] * sig["r_unit"])
            stop_pips = sig["r_unit"] / cfg["pip"]
            trades.append({
                "pair": name, "dir": "LONG" if direction == 1 else "SHORT",
                "entry_time": sig["entry_time"], "exit_time": exit_time,
                "entry_price": sig["bar_entry"], "stop_price": sig["stop"], "target_price": target_price,
                "r_unit": sig["r_unit"], "stop_pips": stop_pips, "target_R": sig["target_R"],
                "r_multiple": r_multiple, "exit_reason": exit_reason,
                "pip": cfg["pip"], "pip_val": cfg["pip_val"],
            })
            busy_until_i = exit_i
        per_instrument[name] = trades
        all_trades.extend(trades)
        wins = sum(1 for t in trades if t["r_multiple"] > 0)
        skip_note = f", {skipped} skipped (position open)" if skipped else ""
        print(f"  {name}: {len(signals)} signals, {len(trades)} taken{skip_note}, "
              f"{wins} wins ({wins/len(trades)*100:.1f}%)" if trades
              else f"  {name}: {len(signals)} signals, 0 taken")

    all_trades.sort(key=lambda t: t["entry_time"])

    balance = STARTING_BALANCE
    peak = balance
    max_dd = 0.0
    gross_win = gross_loss = 0.0
    wins = losses = 0
    equity_curve = [balance]

    for t in all_trades:
        dollar_risk = balance * RISK_PCT
        pnl = dollar_risk * t["r_multiple"]
        qty = round(dollar_risk / (t["stop_pips"] * t["pip_val"]), 2) if t["stop_pips"] > 0 else 0.01
        qty = max(qty, 0.01)
        t["balance_before"] = round(balance, 2)
        t["dollar_risk"] = round(dollar_risk, 2)
        t["qty_lots"] = qty
        t["pnl_dollars"] = round(pnl, 2)
        balance += pnl
        t["balance_after"] = round(balance, 2)
        equity_curve.append(balance)
        if pnl > 0:
            gross_win += pnl
            wins += 1
        else:
            gross_loss += -pnl
            losses += 1
        peak = max(peak, balance)
        dd = (peak - balance) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    n_trades = len(all_trades)
    win_rate = wins / n_trades * 100 if n_trades else 0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    print(f"\n=== {BACKTEST_DAYS}-day combined backtest ({datetime.datetime.utcnow().isoformat()} UTC) ===")
    print(f"Instruments: {', '.join(per_instrument.keys())}")
    print(f"Total signals taken: {n_trades}")
    print(f"Win rate: {win_rate:.1f}% ({wins}W / {losses}L)")
    print(f"Profit factor: {pf:.2f}")
    print(f"${STARTING_BALANCE:,.0f} -> ${balance:,.2f} ({(balance/STARTING_BALANCE-1)*100:+.1f}%)")
    print(f"Max drawdown: {max_dd*100:.2f}%")

    print("\nPer-instrument breakdown:")
    for name, trades in per_instrument.items():
        if not trades:
            print(f"  {name}: 0 signals")
            continue
        w = sum(1 for t in trades if t["r_multiple"] > 0)
        gw = sum(t["r_multiple"] for t in trades if t["r_multiple"] > 0)
        gl = -sum(t["r_multiple"] for t in trades if t["r_multiple"] <= 0)
        pf_i = gw / gl if gl > 0 else float("inf")
        print(f"  {name}: {len(trades)} signals, {w}/{len(trades)} wins ({w/len(trades)*100:.1f}%), PF={pf_i:.2f}")

    out_path = os.path.join(os.path.dirname(__file__), "mylifeloading_portfolio_backtest_90d.csv")
    pd.DataFrame(all_trades).to_csv(out_path, index=False)
    print(f"\nTrade log written to {out_path}")


if __name__ == "__main__":
    main()
