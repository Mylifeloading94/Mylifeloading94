"""$25,000 account backtest, $1,250 maximum-drawdown breaker, Brad-Gold strategy: as written (E1, E2) and the best
improved config under the pre-registered rule (max of min(train PF, validation PF), n >= 100 / 40)."""
import json, os
import numpy as np, pandas as pd
import xau_engine as E, liq_scalp as LS, liq_exec as X, account_sim as A

HERE = os.path.dirname(os.path.abspath(__file__))
m1 = E.load_m1(); b15 = E.to_tf(m1, "15min"); b1h = E.to_tf(m1, "1h")
grid = json.load(open(os.path.join(HERE, "results", "liq_improve.json")))
el = [r for r in grid if r["tr"]["n"] >= 100 and r["va"]["n"] >= 40]
best = max(el, key=lambda r: min(r["tr"]["pf"], r["va"]["pf"]))["cfg"]
print("best improved config by the pre-registered rule:", best, "\n")


def ledger(c):
    sg = LS.generate(b15, b1h, entry=c["entry"].split("-")[0], e2_mode=("loose" if c["entry"] == "E2-loose" else "strict"),
                     aligned=c["aligned"], stop_buf=c["buf"], min_risk_atr=c["min_risk"], tp_min_r=c["tp_min_r"], kz=c["kz"])
    return X.run(m1, b15, sg)


VERS = {"as written: E1 aggressive": dict(entry="E1", buf=0.1, min_risk=0.5, tp_min_r=0.0, kz=False, aligned=True),
        "as written: E2 (Brad's candle)": dict(entry="E2", buf=0.1, min_risk=0.5, tp_min_r=0.0, kz=False, aligned=True),
        "best improved (rule-selected)": best}
print(f"$25,000 start | drawdown breaker $1,250 | real 0.01-lot sizing | spread paid from the feed")
print(f"{'version':32s} {'risk/trade':>10s} | {'trades':>6s} {'WR%':>5s} {'net $':>9s} {'return':>8s} {'max DD $':>9s} | breaker")
out = {}
for name, c in VERS.items():
    t = ledger(c)
    for rp in (0.25, 0.5, 1.0):
        led, st = A.simulate(m1, t, rp)
        out[(name, rp)] = (led, st)
        br = f"HIT {st['breach_at']:%Y-%m-%d} after {st['trades']} trades" if st["breached"] else "not hit"
        print(f"{name:32s} {rp:9.2f}% | {st['trades']:6d} {st['wr']:5.1f} {st['net']:+9.0f} {st['ret_pct']:+7.2f}% {st['max_dd']:9.0f} | {br}")
    s0 = E.stats(t); print(f"{'':32s} (ledger: {len(t)} trades, PF {s0['pf']:.2f}, mean R {s0['exp_r']:+.3f})")
# the same without the breaker, to show what the cap prevented
print("\nSAME TRADES WITHOUT the breaker (what the account would have done), 0.5% risk:")
for name, c in VERS.items():
    led, st = A.simulate(m1, ledger(c), 0.5, halt_on_breach=False)
    print(f"  {name:32s} net {st['net']:+9.0f} ({st['ret_pct']:+.1f}%)  max DD ${st['max_dd']:,.0f}  final ${st['final']:,.0f}")
json.dump({f"{k[0]}|{k[1]}": {kk: (str(vv) if isinstance(vv, pd.Timestamp) else vv) for kk, vv in v[1].items()} for k, v in out.items()},
          open(os.path.join(HERE, "results", "liq_account.json"), "w"), indent=1, default=str)
try:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 5))
    for name in VERS:
        led = out[(name, 0.5)][0]
        if len(led): ax.plot(led.exit_time, led.equity, label=name)
    ax.axhline(25000, color="gray", lw=.8); ax.axhline(25000 - 1250, color="red", ls="--", lw=.8, label="USD 1,250 below start")
    ax.set_title("Brad-Gold liquidity scalping on gold: USD 25k account, 0.5% risk, DD breaker USD 1,250"); ax.set_ylabel("equity (USD)"); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "results", "liq_account_equity.png"), dpi=110); print("wrote results/liq_account_equity.png")
except ImportError:
    pass
