#!/usr/bin/env python3
"""Trade statistics + Aquafunded evaluation headroom for the account. See SKILL.md."""
import argparse, json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LOG = os.path.join(ROOT, "data", "trade_log.csv")
PROFIT = ["profit", "pnl", "net p&l", "net pnl", "realized pnl", "realized p&l", "closed p/l", "p/l", "profit/loss"]
TIME = ["close time", "closed", "close date", "closing time", "time", "date", "timestamp"]
SYM = ["symbol", "instrument", "ticker"]


def pick(cols, names):
    low = {c.lower().strip(): c for c in cols}
    for n in names:
        if n in low:
            return low[n]
    return None


def load(path):
    raw = pd.read_csv(path)
    pc, tc, sc = pick(raw.columns, PROFIT), pick(raw.columns, TIME), pick(raw.columns, SYM)
    if pc is None:
        raise SystemExit(f"no profit column in {path}; columns: {list(raw.columns)}")
    df = pd.DataFrame({"pnl": pd.to_numeric(raw[pc].astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")})
    df["time"] = pd.to_datetime(raw[tc], errors="coerce", utc=True) if tc else pd.NaT
    df["symbol"] = raw[sc].astype(str) if sc else "?"
    df = df.dropna(subset=["pnl"])
    return df.sort_values("time", kind="stable").reset_index(drop=True)


def append_log(df):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    old = pd.read_csv(LOG, parse_dates=["time"]) if os.path.exists(LOG) else pd.DataFrame(columns=df.columns)
    if len(old):
        old["time"] = pd.to_datetime(old["time"], utc=True)
    out = pd.concat([old, df]).drop_duplicates(subset=["time", "symbol", "pnl"])
    out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
    out = out.sort_values("time", kind="stable")
    out.to_csv(LOG, index=False)
    return out.reset_index(drop=True)


def stats(df, start):
    p = df.pnl.to_numpy(float)
    n = len(p)
    if n == 0:
        return dict(n=0)
    w, l = p[p > 0], p[p < 0]
    eq = start + np.cumsum(p)
    peak = np.maximum.accumulate(np.r_[start, eq])[1:]
    streak = best = 0
    for x in p:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    pf = w.sum() / -l.sum() if l.size and l.sum() else float("inf") if w.size else 0.0
    return dict(n=n, win_rate=100 * len(w) / n, pf=pf, avg_win=w.mean() if w.size else 0.0, avg_loss=l.mean() if l.size else 0.0,
                payoff=(w.mean() / -l.mean()) if w.size and l.size else float("nan"), expectancy=p.mean(), net=p.sum(),
                max_dd=float((peak - eq).max()), max_losing_streak=best, best=p.max(), worst=p.min(),
                balance=float(eq[-1]), peak_balance=float(peak.max()))


def live_snapshot():
    from tradelocker import TLAPI
    miss = [k for k in ("TL_USERNAME", "TL_PASSWORD", "TL_SERVER") if not os.environ.get(k)]
    if miss:
        raise SystemExit(f"--live needs environment variables: {', '.join(miss)}")
    api = TLAPI(environment=os.environ.get("TL_ENV", "https://demo.tradelocker.com"), username=os.environ["TL_USERNAME"],
                password=os.environ["TL_PASSWORD"], server=os.environ["TL_SERVER"],
                account_id=int(os.environ.get("TL_ACCOUNT_ID", 0)), acc_num=int(os.environ.get("TL_ACC_NUM", 0)), log_level="warning")
    st = api.get_account_state()
    pos = api.get_all_positions()
    floats = []
    if pos is not None and len(pos):
        col = pick(pos.columns, ["pnl", "unrealizedpnl", "profit", "unrealized pnl"]) or next((c for c in pos.columns if "pnl" in c.lower()), None)
        floats = [float(x) for x in pos[col]] if col else []
    return dict(balance=float(st.get("balance", np.nan)), equity=float(st.get("balance", np.nan)) + float(st.get("openGrossPnL", 0) or 0),
                open_positions=0 if pos is None else len(pos), floats=floats)


def status(s, start, a, live=None):
    target, dd, fl, daily = start * a.target_pct / 100, start * a.dd_pct / 100, start * a.float_pct / 100, start * a.daily_pct / 100
    bal = s.get("balance", start)
    peak = s.get("peak_balance", start)
    if live:
        bal = live["balance"]; peak = max(peak, live["equity"], bal)
    floor = peak - dd
    eq_now = live["equity"] if live else bal
    worst_float = min(live["floats"]) if live and live["floats"] else 0.0
    head = eq_now - floor
    out = dict(balance=bal, equity=eq_now, target_balance=start + target, to_target=start + target - bal, progress_pct=100 * (bal - start) / target,
               trailing_floor=floor, dd_headroom=head, dd_headroom_pct=100 * head / dd, worst_open_float=worst_float, float_limit=-fl,
               daily_limit=-daily)
    if head <= 0 or worst_float <= -fl:
        v = "STOP"
    elif head < 0.4 * dd or worst_float <= -0.6 * fl:
        v = "CAUTION"
    else:
        v = "OK"
    if bal >= start + target:
        v += " (target balance reached)"
    out["verdict"] = v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv"); ap.add_argument("--live", action="store_true"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--start", type=float, default=25000.0); ap.add_argument("--target-pct", type=float, default=3.0)
    ap.add_argument("--dd-pct", type=float, default=5.0); ap.add_argument("--float-pct", type=float, default=1.0)
    ap.add_argument("--daily-pct", type=float, default=3.0)
    a = ap.parse_args()
    if a.csv:
        df = append_log(load(a.csv))
    elif os.path.exists(LOG):
        df = pd.read_csv(LOG); df["time"] = pd.to_datetime(df["time"], utc=True)
    else:
        df = pd.DataFrame(columns=["pnl", "time", "symbol"])
    s = stats(df, a.start)
    live = live_snapshot() if a.live else None
    st = status(s, a.start, a, live)
    days = None
    if len(df) and df.time.notna().any():
        d = df.dropna(subset=["time"]).assign(day=lambda x: x.time.dt.date)
        days = d.groupby("day").pnl.sum()
        st["worst_day"] = float(days.min()); st["trading_days"] = int(len(days))
        st["worst_day_vs_limit"] = "BREACH" if days.min() <= st["daily_limit"] else "ok"
    per_sym = df.groupby("symbol").pnl.agg(["count", "sum"]).round(2).to_dict("index") if len(df) else {}
    if a.json:
        print(json.dumps(dict(stats=s, status=st, per_symbol=per_sym), default=float, indent=2)); return
    if not s["n"]:
        print("No closed trades loaded (use --csv <history export>)."); 
    else:
        print(f"Closed trades {s['n']}  WR {s['win_rate']:.1f}%  PF {s['pf']:.2f}  avg win {s['avg_win']:.2f}  avg loss {s['avg_loss']:.2f}  payoff {s['payoff']:.2f}")
        print(f"Net {s['net']:.2f}  expectancy/trade {s['expectancy']:.2f}  max DD {s['max_dd']:.2f}  longest losing streak {s['max_losing_streak']}  best {s['best']:.2f}  worst {s['worst']:.2f}")
        if s["n"] < 30:
            print(f"NOTE: only {s['n']} trades - win rate / PF are statistically meaningless below ~30.")
        for k, v in per_sym.items():
            print(f"  {k}: {v['count']} trades, net {v['sum']:.2f}")
    print(f"\nEvaluation status: {st['verdict']}")
    print(f"  balance {st['balance']:.2f}  equity {st['equity']:.2f}  target {st['target_balance']:.2f}  to go {st['to_target']:.2f}  ({st['progress_pct']:.0f}% of target)")
    print(f"  trailing floor {st['trailing_floor']:.2f}  headroom {st['dd_headroom']:.2f} ({st['dd_headroom_pct']:.0f}% of drawdown budget)")
    print(f"  worst open float {st['worst_open_float']:.2f} (limit {st['float_limit']:.2f})" + ("" if live else "   [no --live: open positions not checked]"))
    if "worst_day" in st:
        print(f"  trading days {st['trading_days']}  worst day {st['worst_day']:.2f} (daily limit {st['daily_limit']:.2f}: {st['worst_day_vs_limit']})")


if __name__ == "__main__":
    main()
