"""
4H SMC Market-Structure chart generator.
Draws: most recent 4H FVG (cyan #00bcd4), BOS + CHoCH labels,
and swing labels HH/HL/LH/LL. No arrows — text labels only.
Locked-in style to match trading_agent.py charts.
"""
import os, time
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import trading_agent as ta


def build_structure_chart(pair, headers, save_path, window=90):
    cfg = ta.MARKETS[pair]; pip = cfg["pip"]
    bars = ta.fetch_bars(headers, cfg["id"], "4H", 60)
    disp = bars[-window:] if len(bars) >= window else bars
    n = len(disp)

    # ── Swings ────────────────────────────────────────────────────────────────
    sw = ta.find_swings(disp, 3)
    highs = [s for s in sw if s["type"] == "high"]
    lows  = [s for s in sw if s["type"] == "low"]
    labeled = []
    for k, s in enumerate(highs):
        if k == 0: continue
        labeled.append({**s, "label": "HH" if s["price"] > highs[k-1]["price"] else "LH"})
    for k, s in enumerate(lows):
        if k == 0: continue
        labeled.append({**s, "label": "HL" if s["price"] > lows[k-1]["price"] else "LL"})
    labeled.sort(key=lambda x: x["idx"])

    # ── Most recent 4H FVG ────────────────────────────────────────────────────
    fvg = None
    for i in range(n-1, 1, -1):
        if disp[i]["l"] > disp[i-2]["h"]:
            fvg = {"type": "bullish", "top": disp[i]["l"], "bot": disp[i-2]["h"], "idx": i-2}; break
        if disp[i]["h"] < disp[i-2]["l"]:
            fvg = {"type": "bearish", "top": disp[i-2]["l"], "bot": disp[i]["h"], "idx": i-2}; break

    # ── BOS & CHoCH ───────────────────────────────────────────────────────────
    trend = ta.market_structure(disp, len(disp), 3)
    bos_mark = None; choch_mark = None
    if highs and trend == "bullish":
        ref = highs[-2]["price"] if len(highs) >= 2 else highs[-1]["price"]
        refidx = highs[-2]["idx"] if len(highs) >= 2 else highs[-1]["idx"]
        for i in range(refidx+1, n):
            if disp[i]["c"] > ref:
                bos_mark = {"idx": i, "price": ref}; break
    if lows and trend == "bearish":
        ref = lows[-2]["price"] if len(lows) >= 2 else lows[-1]["price"]
        refidx = lows[-2]["idx"] if len(lows) >= 2 else lows[-1]["idx"]
        for i in range(refidx+1, n):
            if disp[i]["c"] < ref:
                bos_mark = {"idx": i, "price": ref}; break
    for j in range(len(sw)-1, 0, -1):
        s = sw[j]
        if s["type"] == "low":
            prev_low = next((x for x in reversed(sw[:j]) if x["type"] == "low"), None)
            if prev_low:
                for i in range(s["idx"]+1, n):
                    if disp[i]["c"] < prev_low["price"]:
                        choch_mark = {"idx": i, "price": prev_low["price"]}; break
        if choch_mark: break

    # ══ CHART ═════════════════════════════════════════════════════════════════
    BG="white"; BULL="#90bff9"; BEAR="#f48fb1"; FVG_COL="#00bcd4"
    fig, ax = plt.subplots(figsize=(15, 8), facecolor=BG); ax.set_facecolor(BG)
    W = 0.6
    for i, b in enumerate(disp):
        col = BULL if b["c"] >= b["o"] else BEAR
        ax.plot([i, i], [b["l"], b["h"]], color="black", linewidth=0.8, zorder=2)
        blo = min(b["o"], b["c"]); bhi = max(b["o"], b["c"]); ht = max(bhi-blo, (b["h"]-b["l"])*0.002)
        ax.add_patch(Rectangle((i-W/2, blo), W, ht, facecolor=col, edgecolor="black", linewidth=0.5, zorder=3))

    if fvg:
        x0 = fvg["idx"]
        ax.add_patch(Rectangle((x0-0.5, fvg["bot"]), (n-x0)+0.5, fvg["top"]-fvg["bot"],
                     facecolor=FVG_COL, edgecolor=FVG_COL, alpha=0.35, zorder=2))
        ax.text(n-0.5, (fvg["top"]+fvg["bot"])/2, "  FVG (4H)", color="#006c75",
                fontsize=10, fontweight="bold", va="center", ha="left")

    # Swing labels — text only, no arrows
    for s in labeled:
        if s["type"] == "high":
            ax.text(s["idx"], s["price"], s["label"], color="#c62828", fontsize=10,
                    fontweight="bold", ha="center", va="bottom", zorder=6)
        else:
            ax.text(s["idx"], s["price"], s["label"], color="#2e7d32", fontsize=10,
                    fontweight="bold", ha="center", va="top", zorder=6)

    if bos_mark:
        x, y = bos_mark["idx"], bos_mark["price"]
        ax.plot([max(0, x-12), x], [y, y], color="#1565c0", linewidth=1.3, linestyle="--", zorder=5)
        ax.text(x, y, "  BOS", color="#1565c0", fontsize=11, fontweight="bold", va="bottom", zorder=7)
    if choch_mark:
        x, y = choch_mark["idx"], choch_mark["price"]
        ax.plot([max(0, x-12), x], [y, y], color="#ef6c00", linewidth=1.3, linestyle="--", zorder=5)
        ax.text(x, y, "  CHoCH", color="#ef6c00", fontsize=11, fontweight="bold", va="top", zorder=7)

    ax.yaxis.set_tick_params(labelcolor="#0000ff")
    ax.grid(axis="y", color="#e0e0e0", linewidth=0.5, zorder=1)
    ax.set_xlim(-1, n+6)
    allp = [b["h"] for b in disp] + [b["l"] for b in disp]
    pad = (max(allp)-min(allp))*0.06
    ax.set_ylim(min(allp)-pad, max(allp)+pad)
    ax.set_xticks([]); ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.text(0.01, 0.98, f"{pair} · 4H · Market Structure", transform=ax.transAxes,
            fontsize=14, fontweight="bold", color="black", va="top")
    ax.text(0.01, 0.94, "FVG", transform=ax.transAxes, color="#006c75", fontsize=9, fontweight="bold", va="top")
    ax.text(0.045, 0.94, "BOS", transform=ax.transAxes, color="#1565c0", fontsize=9, fontweight="bold", va="top")
    ax.text(0.085, 0.94, "CHoCH", transform=ax.transAxes, color="#ef6c00", fontsize=9, fontweight="bold", va="top")
    ax.text(0.14, 0.94, "HH/HL", transform=ax.transAxes, color="#2e7d32", fontsize=9, fontweight="bold", va="top")
    ax.text(0.20, 0.94, "LH/LL", transform=ax.transAxes, color="#c62828", fontsize=9, fontweight="bold", va="top")

    plt.tight_layout()
    plt.savefig(save_path, dpi=140, bbox_inches="tight", facecolor=BG)
    plt.close()
    return {"trend": trend, "fvg": bool(fvg), "bos": bool(bos_mark), "choch": bool(choch_mark),
            "swings": len(labeled)}


if __name__ == "__main__":
    headers, account_id, balance = ta.auth()
    pair = os.environ.get("CHART_PAIR", "EURJPY")
    info = build_structure_chart(pair, headers, f"/tmp/{pair.lower()}_4h_smc.png")
    print(f"{pair}: {info}")
