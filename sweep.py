import itertools, pandas as pd
from xau_bot import *
df=load(); rows=[]
for trend,rn,rb,sh,sl,tp,mh in itertools.product([100,200],[2,3,5],[5,10,20,30],[False,True],[1.5,2.5,4],[0.5,1,1.5,2.5],[5,10,20]):
    kw=dict(trend=trend,rsi_n=rn,rsi_buy=rb,rsi_sell=100-rb,shorts=sh,sl_atr=sl,tp_atr=tp,max_hold=mh,risk_pct=0.01)
    tr,cv=backtest(df,**kw)
    if len(tr)<50: continue
    a,ca=window(tr,cv,"2019-01-01","2022-12-31"); b,cb=window(tr,cv,"2023-01-01","2026-12-31")
    sa,sb=stats(a,ca),stats(b,cb)
    if sa["n"]<25 or sb["n"]<25: continue
    rows.append(dict(**kw,trn=sa["n"],trw=sa["win"],trpf=sa["pf"],trdd=sa["maxdd"],ten=sb["n"],tew=sb["win"],tepf=sb["pf"],tedd=sb["maxdd"]))
r=pd.DataFrame(rows); r.to_csv("/tmp/claude-0/-home-user-Mylifeloading94/43b84456-5322-5866-9458-23e446b54428/scratchpad/sweep.csv",index=False)
print(len(r)); pd.set_option("display.width",250)
g=r[(r.trpf>=1.5)&(r.tepf>=1.5)].sort_values("tepf",ascending=False)
print(g.head(15).to_string()); print("max min(trpf,tepf):",r.assign(m=r[["trpf","tepf"]].min(axis=1)).sort_values("m").tail(5).to_string())
