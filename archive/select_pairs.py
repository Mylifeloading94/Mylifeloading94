"""Pair selection on IN-SAMPLE 2025 data only, then frozen.

Selecting a watchlist on the 2026 test data would be selection bias -- it is
the single easiest way to fake a good backtest, so it is not done here.
"""
import numpy as np, pandas as pd
import tl_data, strategy as st, signal_sim as ss, config

p = config.locked_params()
IS_START=pd.Timestamp(config.IS_START,tz="UTC"); IS_END=pd.Timestamp(config.IS_END,tz="UTC")

rows=[]
for s in tl_data.SYMBOLS:
    r = ss.simulate_symbol(s, tl_data.load(s), p, IS_START, IS_END)
    k = ss.stats(r)
    rows.append(dict(symbol=s, **k))
df=pd.DataFrame(rows).sort_values("pf",ascending=False)

# ---- rejection rules, applied mechanically -------------------------------
MIN_TRADES=4; MIN_WR=60.0; MIN_PF=1.15; MIN_EXP=0.02
def verdict(r):
    if r.n < MIN_TRADES:  return "REJECT", f"insufficient setups ({int(r.n)} < {MIN_TRADES})"
    if r.wr < MIN_WR:     return "REJECT", f"win rate {r.wr:.1f}% < {MIN_WR:.0f}%"
    if r.pf < MIN_PF:     return "REJECT", f"profit factor {r.pf:.2f} < {MIN_PF}"
    if r.exp < MIN_EXP:   return "REJECT", f"expectancy {r.exp:+.3f}R below floor"
    return "APPROVE", "meets all in-sample minimums"

df[["verdict","reason"]]=df.apply(lambda r: pd.Series(verdict(r)),axis=1)
pd.set_option("display.width",200)
print("=== IN-SAMPLE 2025 PER-PAIR (selection basis) ===")
print(df[["symbol","n","wr","pf","exp","total_r","verdict","reason"]].round(3).to_string(index=False))
appr=df[df.verdict=="APPROVE"].symbol.tolist()
print(f"\nAPPROVED ({len(appr)}): {appr}")
df.to_csv("pair_selection_insample.csv",index=False)
open("watchlist.txt","w").write("\n".join(appr))
