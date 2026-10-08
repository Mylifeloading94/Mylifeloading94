"""Weekly review. Usage: weekly_review.py [--since ISO] [--until ISO]. Defaults to the last 7 days."""
import json, argparse, datetime as dt
def pip(pair): return 0.01 if "JPY" in pair else 0.1 if pair == "XAUUSD" else 0.0001
ap = argparse.ArgumentParser(); ap.add_argument("--trades", default="trades/trades.json")
ap.add_argument("--since"); ap.add_argument("--until"); a = ap.parse_args()
now = dt.datetime.now(dt.timezone.utc)
parse = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
since = parse(a.since) if a.since else now - dt.timedelta(days=7); until = parse(a.until) if a.until else now
rows = [t for t in json.load(open(a.trades)) if since <= parse(t["created_utc"]) <= until]
print(f"WEEKLY REVIEW  {since:%Y-%m-%d %H:%M} -> {until:%Y-%m-%d %H:%M} UTC\n")
tot = {"live": 0.0, "demo": 0.0}; w = l = 0
for t in rows:
    r = t["result_pips"]; tag = "DEMO" if t["demo"] else "LIVE"
    print(f"{t['flag']} {t['pair']:7} {t['side']:4} [{tag}] {t['status'].upper():8} "
          f"{'n/a' if r is None else f'{r:+.1f} pips'}  ({t['id']})")
    if r is not None:
        tot["demo" if t["demo"] else "live"] += r
        if r > 0: w += 1
        elif r < 0: l += 1
print(f"\nSignals: {len(rows)} | Wins: {w} | Losses: {l} | Open/pending/expired: {len(rows)-w-l-sum(1 for t in rows if t['result_pips']==0)}")
print(f"LIVE total: {tot['live']:+.1f} pips | DEMO total: {tot['demo']:+.1f} pips")
