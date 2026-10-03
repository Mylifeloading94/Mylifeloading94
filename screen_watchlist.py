"""
Screen the full watchlist (28 FX pairs + SPX500 + NAS100, gold as reference) with a
FIXED set of strategies -- no per-instrument tuning -- on H1 bid/ask bars, 2019 -> today.

Pre-registered rules (set before looking at any result):
  * 10 fixed configs applied identically to every instrument:
        fade  bb3.0/RSI20 and bb2.5/RSI25, each with a 4h and an 8h hold
        momentum  20-bar break + EMA stack, RSI>70 and RSI>75, 8h hold
    plus the 4 fade configs long-only; stop 3 ATR, time exit, spread from the feed.
  * Per instrument, the config with the best TRAIN (2019-22) profit factor (n>=100) is chosen.
  * An instrument QUALIFIES only if that config has PF > 1.05 on train AND PF > 1.05 on
    validation (2023-24, n>=40).
  * Qualifiers are ranked by min(train PF, validation PF). Test (2025+) is reported last
    and never used to choose.
  * NULL CONTROL: the identical procedure is run on randomly time-shifted copies of the
    signals (same frequency, no information) to measure how many instruments "qualify" by luck.
"""
import json, os, sys
import numpy as np, pandas as pd
import xau_engine as E, xau_strategies as S
import fetch_candles as F

HERE = os.path.dirname(os.path.abspath(__file__))
TR_END = pd.Timestamp("2023-01-01", tz="UTC"); VA_END = pd.Timestamp("2025-01-01", tz="UTC")
CONFIGS = [
    dict(name="fade3.0/20 h4",  fam="fade", hold=240, p=dict(bb_k=3.0, rsi_thr=20., adx_max=99., sl_atr=3., side="both")),
    dict(name="fade3.0/20 h8",  fam="fade", hold=480, p=dict(bb_k=3.0, rsi_thr=20., adx_max=99., sl_atr=3., side="both")),
    dict(name="fade2.5/25 h4",  fam="fade", hold=240, p=dict(bb_k=2.5, rsi_thr=25., adx_max=99., sl_atr=3., side="both")),
    dict(name="fade2.5/25 h8",  fam="fade", hold=480, p=dict(bb_k=2.5, rsi_thr=25., adx_max=99., sl_atr=3., side="both")),
    # long-only variants, added BEFORE any full-watchlist result was seen: gold's one surviving
    # edge was long-only, and dip-buying is the classic equity-index effect.
    dict(name="fade3.0/20 h4 L", fam="fade", hold=240, p=dict(bb_k=3.0, rsi_thr=20., adx_max=99., sl_atr=3., side="long")),
    dict(name="fade3.0/20 h8 L", fam="fade", hold=480, p=dict(bb_k=3.0, rsi_thr=20., adx_max=99., sl_atr=3., side="long")),
    dict(name="fade2.5/25 h4 L", fam="fade", hold=240, p=dict(bb_k=2.5, rsi_thr=25., adx_max=99., sl_atr=3., side="long")),
    dict(name="fade2.5/25 h8 L", fam="fade", hold=480, p=dict(bb_k=2.5, rsi_thr=25., adx_max=99., sl_atr=3., side="long")),
    dict(name="mom rsi70 h8",   fam="momentum", hold=480, p=dict(bo_len=20, rsi_thr=70., sl_atr=3., side="both")),
    dict(name="mom rsi75 h8",   fam="momentum", hold=480, p=dict(bo_len=20, rsi_thr=75., sl_atr=3., side="both")),
]
GAP = dict(bar_min=60, gap_min=90, max_delay=30)


def h1_path(sym):
    """data/h1 (fresh download) wins; results/h1 is the committed copy so a fresh checkout works."""
    for d in ("data", "results"):
        p = os.path.join(HERE, d, "h1", f"{sym}.parquet")
        if os.path.exists(p):
            return p
    return None


def load_h1(sym):
    return pd.read_parquet(h1_path(sym))


def signals(h1, cfg):
    b = E.to_tf(h1, "1h")
    L, Sh, R = S.STRATEGIES[cfg["fam"]](b, **cfg["p"])
    return b, L, Sh, R


def split_stats(t):
    return (E.stats(t[t.entry_time < TR_END]), E.stats(t[(t.entry_time >= TR_END) & (t.entry_time < VA_END)]),
            E.stats(t[t.entry_time >= VA_END]), E.stats(t))


def evaluate(h1, b, L, Sh, R, cfg):
    return E.run(h1, b, "1h", L, Sh, R, hold_min=cfg["hold"], tp_mult=0.0, **GAP)


def qualifies(tr, va):
    return tr["n"] >= 100 and va["n"] >= 40 and tr["pf"] > 1.05 and va["pf"] > 1.05


def screen_symbol(sym, shift=0):
    h1 = load_h1(sym)
    res = []
    for cfg in CONFIGS:
        b, L, Sh, R = signals(h1, cfg)
        if shift:                                   # NULL: same signal frequency, no information
            L, Sh = np.roll(L, shift), np.roll(Sh, shift)
        t = evaluate(h1, b, L, Sh, R, cfg)
        tr, va, te, al = split_stats(t)
        res.append(dict(cfg=cfg["name"], tr=tr, va=va, te=te, al=al))
    cand = [r for r in res if r["tr"]["n"] >= 100]
    best = max(cand, key=lambda r: r["tr"]["pf"]) if cand else None
    return dict(sym=sym, all=res, best=best, qualifies=bool(best and qualifies(best["tr"], best["va"])))


def main():
    syms = [s for s in list(F.INDICES) + F.FOREX + ["XAUUSD"] if h1_path(s)]
    print(f"{len(syms)} instruments on disk", flush=True)
    real = [screen_symbol(s) for s in syms]
    rng = np.random.default_rng(42)
    nulls = []
    for k in range(5):
        sh = int(rng.integers(500, 5000))
        nulls.append(sum(screen_symbol(s, sh)["qualifies"] for s in syms))
        print(f"  null shift {sh}: {nulls[-1]} of {len(syms)} instruments 'qualify' by luck", flush=True)
    json.dump(dict(real=real, null_qualifiers=nulls), open(os.path.join(HERE, "results", "screen_watchlist.json"), "w"), indent=1, default=float)
    f = lambda s: f"n={s['n']:4d} WR {s['wr']:4.1f} PF {s['pf']:4.2f}"
    print(f"\n{'instrument':8s} {'best-on-train config':16s} | {'train 2019-22':^24s} | {'valid 2023-24':^24s} | qual")
    for r in sorted(real, key=lambda r: -(min(r['best']['tr']['pf'], r['best']['va']['pf']) if r['best'] else 0)):
        b = r["best"]
        if b is None:
            print(f"{r['sym']:8s} (too few trades)"); continue
        print(f"{r['sym']:8s} {b['cfg']:16s} | {f(b['tr']):24s} | {f(b['va']):24s} | {'YES' if r['qualifies'] else '-'}")
    q = [r for r in real if r["qualifies"]]
    print(f"\nQUALIFIERS: {len(q)} of {len(real)}   |  chance level (null, 5 runs): {nulls}  mean {np.mean(nulls):.1f}")
    print("\nTEST (2025 -> today), qualifiers only, scored once:")
    for r in sorted(q, key=lambda r: -min(r['best']['tr']['pf'], r['best']['va']['pf'])):
        b = r["best"]; print(f"  {r['sym']:8s} {b['cfg']:16s} {f(b['te'])}   ALL {f(b['al'])}")


if __name__ == "__main__":
    main()
