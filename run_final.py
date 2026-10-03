"""Final XAUUSD bot config: backtest 2019-01-01 -> latest bar, with yearly + perturbation checks."""
from xau_bot import *
CFG=dict(trend=100,rsi_n=3,rsi_buy=30,rsi_sell=70,shorts=False,sl_atr=4.0,tp_atr=2.5,max_hold=20,risk_pct=0.01)
df=load()
def run(cfg,a="2019-01-01",b="2026-12-31"):
    tr,cv=backtest(df,**cfg); return window(tr,cv,a,b)
tr,cv=run(CFG); print("FULL 2019->now",stats(tr,cv))
print("exits:",tr.why.value_counts().to_dict())
for y in range(2019,2027):
    t,c=run(CFG,f"{y}-01-01",f"{y}-12-31"); print(y,stats(t,c))
print("--- perturbation (each param moved, rest fixed)")
for k,vs in dict(trend=[80,120],rsi_buy=[25,35],sl_atr=[3,5],tp_atr=[2,3],max_hold=[15,25]).items():
    for v in vs:
        t,c=run({**CFG,**{k:v,**({'rsi_sell':100-v} if k=='rsi_buy' else {})}}); s=stats(t,c); print(k,v,s['n'],s['win'],s['pf'],s['maxdd'])
tr.to_csv("xau_trades.csv",index=False); cv.to_csv("xau_equity.csv")
