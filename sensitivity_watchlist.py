"""
Sensitivity + cross-section checks for the watchlist screen (writes results/watchlist_sensitivity.txt).
  A. plateau test: 48 neighbouring momentum configs on each qualifying instrument
  B. cross-section: the SAME RSI>80 / 8h momentum rule on every instrument on disk, with permutation p
"""
import itertools, os, sys, io, contextlib
import numpy as np, pandas as pd
import xau_engine as E, xau_strategies as S, screen_watchlist as W

HERE = os.path.dirname(os.path.abspath(__file__))
buf = io.StringIO()
def out(*a):
    print(*a); print(*a, file=buf)

def plateau(sym):
    h1 = W.load_h1(sym); b = E.to_tf(h1, "1h"); rows = []
    for thr, hold, sl in itertools.product((65, 70, 75, 80), (240, 480, 720, 1440), (2.0, 3.0, 4.0)):
        L, Sh, R = S.momentum(b, bo_len=20, rsi_thr=float(thr), sl_atr=sl, side="both")
        t = E.run(h1, b, "1h", L, Sh, R, hold_min=hold, tp_mult=0.0, **W.GAP)
        tr, va, te, al = W.split_stats(t)
        rows.append(dict(thr=thr, hold=hold // 60, sl=sl, pf=al["pf"], tr=tr["pf"], va=va["pf"], te=te["pf"]))
    g = pd.DataFrame(rows)
    piv = g[g.sl == 3.0].pivot(index="thr", columns="hold", values="pf").round(2)
    piv.columns = [f"{c}h" for c in piv.columns]; piv.index = [f"RSI>{i}" for i in piv.index]
    out(f"\n== {sym}: momentum, 48 neighbouring configs (PF over all trades, stop-3-ATR slice) ==")
    out(piv.to_string())
    out(f"  PF>1 overall: {(g.pf > 1).sum()}/48 | PF>1 in train AND valid AND test: {((g.tr > 1) & (g.va > 1) & (g.te > 1)).sum()}/48 | median PF {g.pf.median():.2f} | range {g.pf.min():.2f}-{g.pf.max():.2f}")

def cross():
    cfg = dict(name="mom rsi80 h8", fam="momentum", hold=480, p=dict(bo_len=20, rsi_thr=80., sl_atr=3., side="both"))
    rng = np.random.default_rng(3)
    out("\n== same rule (RSI>80, 8h hold, 3 ATR stop, both sides) on every instrument on disk ==")
    out(f"{'instr':8s} {'n':>4} {'WR%':>5} {'PF':>5} {'R':>7} {'t':>5} | {'long':>5} {'short':>5} | {'train':>5} {'valid':>5} {'test':>5} | perm p")
    for s in [x for x in list(__import__("fetch_candles").INDICES) + __import__("fetch_candles").FOREX + ["XAUUSD"] if W.h1_path(x)]:
        h1 = W.load_h1(s); b, L, Sh, R = W.signals(h1, cfg); t = W.evaluate(h1, b, L, Sh, R, cfg)
        tr, va, te, al = W.split_stats(t); lg = E.stats(t[t.dir == 1]); sh = E.stats(t[t.dir == -1])
        null = [W.evaluate(h1, b, np.roll(L, int(k)), np.roll(Sh, int(k)), R, cfg).r.sum() for k in rng.integers(300, len(L) - 300, 200)]
        p = (1 + sum(x >= t.r.sum() for x in null)) / 201
        out(f"{s:8s} {al['n']:4d} {al['wr']:5.1f} {al['pf']:5.2f} {al['tot_r']:+7.1f} {al['t']:+5.2f} | {lg['pf']:5.2f} {sh['pf']:5.2f} | {tr['pf']:5.2f} {va['pf']:5.2f} {te['pf']:5.2f} | {p:.3f}")

if __name__ == "__main__":
    for s in ("USDJPY", "USDCHF", "EURJPY"):
        if W.h1_path(s):
            plateau(s)
    cross()
    open(os.path.join(HERE, "results", "watchlist_sensitivity.txt"), "w").write(buf.getvalue())
