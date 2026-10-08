"""Render a trade chart. Usage: trade_chart.py TRADE_ID BARS_CSV OUT_PNG [--event tp1|tp2|sl|be|setup]
BARS_CSV columns: t(unix s),o,h,l,c  (M15 bars from TradingView get_ohlcv)."""
import csv, json, sys, argparse, datetime as dt
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

def pip(pair): return 0.01 if "JPY" in pair else 0.1 if pair == "XAUUSD" else 0.0001
ap = argparse.ArgumentParser(); ap.add_argument("trade_id"); ap.add_argument("bars"); ap.add_argument("out")
ap.add_argument("--event", default="setup"); ap.add_argument("--trades", default="trades/trades.json")
a = ap.parse_args()
T = next(t for t in json.load(open(a.trades)) if t["id"] == a.trade_id)
bars = [tuple(map(float, r)) for r in csv.reader(open(a.bars)) if r and r[0][0].isdigit()]
P = pip(T["pair"]); sell = T["side"] == "SELL"
risk = abs(T["stop"] - T["entry"]) / P
p1 = abs(T["entry"] - T["tp1"]) / P; p2 = abs(T["entry"] - T["tp2"]) / P
head = {"setup": "SETUP", "tp1": "🎯 TP1 HIT", "tp2": "🎯 TP2 HIT", "sl": "🛑 STOP LOSS HIT", "be": "STOPPED AT BREAKEVEN (after TP1)"}[a.event]
head = head.replace("🎯 ", "TARGET ").replace("🛑 ", "")  # matplotlib fonts lack emoji
fig, ax = plt.subplots(figsize=(12, 7), dpi=130)
for i, (t, o, h, l, c) in enumerate(bars):
    col = "#26a69a" if c >= o else "#ef5350"
    ax.plot([i, i], [l, h], color="black", lw=1, zorder=2)
    ax.add_patch(Rectangle((i-.35, min(o, c)), .7, max(abs(c-o), P/10), facecolor=col, edgecolor="black", lw=.8, zorder=3))
x1 = len(bars) + 14
def line(y, col, lab):
    ax.axhline(y, color=col, lw=1.2); ax.text(x1-.5, y, lab, color=col, ha="right", va="bottom", fontsize=8.5, fontweight="bold")
line(T["entry"], "#e08a00", f"ENTRY {T['entry']:.5f}"); line(T["stop"], "#ef5350", f"STOP {T['stop']:.5f}")
line(T["tp1"], "#2e7d32", f"TP1 {T['tp1']:.5f}"); line(T["tp2"], "#2e7d32", f"TP2 {T['tp2']:.5f}")
res = {"setup": "", "tp1": f"+{p1:.1f} pips (TP1, half closed)", "tp2": f"+{p2:.1f} pips (TP2)  |  blended {(p1+p2)/2:.1f} pips",
       "sl": f"-{risk:.1f} pips", "be": f"0 pips on 2nd half  |  blended +{p1/2:.1f} pips"}[a.event]
ax.set_title(f"{'DEMO — ' if T['demo'] else ''}{T['pair']} {T['side']} | {head} | {res}", loc="left", fontsize=11)
ax.set_xlim(-1, x1); ax.yaxis.tick_right(); ax.set_xticks([]); ax.grid(axis="y", color="#e3e3e3", lw=.5)
for s in ax.spines.values(): s.set_color("black")
plt.tight_layout(); plt.savefig(a.out); print("saved", a.out)
