"""Representative winning / losing trades, plus setups the bot REJECTED,
with the reason in each case. Drawn from the out-of-sample 2026 window."""
import numpy as np, pandas as pd
import tl_data, strategy as st, signal_sim as ss, config

p=config.locked_params()
S=pd.Timestamp(config.OOS_START,tz="UTC"); E=pd.Timestamp(config.OOS_END,tz="UTC")
wl=open("watchlist.txt").read().split()
rows=[]
for s in wl: rows+=ss.simulate_symbol(s, tl_data.load(s), p, S, E)
df=pd.DataFrame(rows)
print(f"population: {len(df)} trades\n")

def show(r, tag):
    pip=st.PIP[r["symbol"]]
    d="LONG" if r["direction"]>0 else "SHORT"
    print(f"--- {tag}: {r['symbol']} {d} ---")
    print(f"  signal bar   : {r['time']}   fill: {r['entry_time']}")
    print(f"  entry {r['entry']:.5f}  stop {r['stop']:.5f}  target {r['target']:.5f}"
          f"   (stop = {abs(r['entry']-r['stop'])/pip:.1f} pips)")
    print(f"  quality score: {r['score']}/100  -> " +
          ", ".join(f"{k}={v}" for k,v in r["parts"].items()))
    print(f"  outcome      : {r['reason']}  {r['r']:+.3f}R after costs"
          f"   (MFE {r['mfe']:+.2f}R / MAE {r['mae']:+.2f}R, held {r['bars']} bars)")
    print()

w=df[df.r>0].sort_values("score",ascending=False)
l=df[df.r<=0].sort_values("score",ascending=False)
for i in range(min(2,len(w))): show(w.iloc[i],"WINNER")
for i in range(min(3,len(l))): show(l.iloc[i],"LOSER")

print("=== does a higher score mean a better trade, out of sample? ===")
df["band"]=pd.cut(df.score,[0,65,70,75,100])
g=df.groupby("band",observed=True).agg(n=("r","size"),win_rate=("r",lambda x:(x>0).mean()*100),exp_R=("r","mean"))
print(g.round(3).to_string())
if df.score.std()>0:
    print(f"\ncorrelation(score, R) out of sample = {np.corrcoef(df.score,df.r)[0,1]:+.3f}")

print("\n=== REJECTED SETUPS: why the bot stood down ===")
# re-walk one symbol and tally rejection causes
from strategy import _find_sweep
sym="EURUSD"; f=tl_data.load(sym); ctx=st.Context(sym,f,p)
idx=f.index
lo=int(np.searchsorted(idx.values,np.datetime64(S.tz_localize(None)),"left"))
hi=int(np.searchsorted(idx.values,np.datetime64(E.tz_localize(None)),"right"))
reasons={}
def bump(k): reasons[k]=reasons.get(k,0)+1
for i in range(lo,min(hi,len(idx)-1)):
    if not ctx.session_ok(i): bump("outside the two trading sessions"); continue
    a=ctx.atr15[i]; price=ctx.c[i]
    if not np.isfinite(a) or a<=0: continue
    ap=a/price
    if ap<p.min_atr_pct or ap>p.max_atr_pct: bump("volatility outside the tradable band"); continue
    if ctx.spread>p.max_spread_atr*a: bump("spread too wide vs volatility"); continue
    if ctx.d1_bias(i)==0: bump("no clear daily trend"); continue
    d=ctx.d1_bias(i)
    h4=ctx.h4_bias(i)
    if h4!=0 and h4!=d: bump("H4 disagrees with the daily bias"); continue
    fnd=_find_sweep(ctx,i,d)
    if not fnd: bump("no liquidity sweep to trade"); continue
    sb,sx=fnd
    ra=max(0,sb-p.mss_ref)
    lvl=(ctx.h[ra:sb].max() if sb>ra else ctx.h[sb]) if d>0 else (ctx.l[ra:sb].min() if sb>ra else ctx.l[sb])
    if (d>0 and not ctx.c[i]>lvl) or (d<0 and not ctx.c[i]<lvl): bump("sweep never reclaimed (no structure shift)"); continue
    if abs(ctx.c[i]-ctx.o[i])<p.disp_body_atr*a: bump("confirmation candle too weak"); continue
    if st.evaluate(ctx,i) is None: bump("failed location / extension / score gate"); continue
    bump("ACCEPTED")
tot=sum(reasons.values())
for k,v in sorted(reasons.items(),key=lambda x:-x[1]):
    print(f"  {k:45s} {v:7d}  ({100*v/tot:5.2f}%)")
