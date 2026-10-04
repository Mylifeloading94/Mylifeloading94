"""Pass-probability study for the Aquafunded evaluation: 9 FX pairs x 10 pre-registered configs x fixed $-risk x horizon.
Design starts 2019-2024, held-out starts 2025+. Rolling start every 3 days."""
import json, sys
import numpy as np, pandas as pd
import screen_watchlist as W, prop_sim as P, fetch_candles as F

SYMS = F.FOREX if hasattr(F, "FOREX") else []
SYMS = [s for s in SYMS if W.h1_path(s)]
RISKS = [50, 75, 100, 125, 150, 200]
HORIZ = [30, 60, 90, 365]
HOLD_OUT = pd.Timestamp("2025-01-01", tz="UTC")


def ledger(sym, cfg, shift=0):
    h1 = W.load_h1(sym)
    b, L, Sh, R = W.signals(h1, cfg)
    if shift:
        L, Sh = np.roll(L, shift), np.roll(Sh, shift)
    t = W.evaluate(h1, b, L, Sh, R, cfg).sort_values("entry_time").reset_index(drop=True)
    mae, mfe = P.excursions(h1, t)
    return h1, t, mae, mfe


def study(shift=0):
    rows = []
    for sym in SYMS:
        for cfg in W.CONFIGS:
            h1, t, mae, mfe = ledger(sym, cfg, shift)
            end = t.exit_time.max()
            wr = 100 * (t.r > 0).mean()
            for H in HORIZ:
                st = pd.date_range(pd.Timestamp("2019-02-01", tz="UTC"), end - pd.Timedelta(days=H if H < 365 else 270), freq="3D")
                for risk in RISKS:
                    code, days, cnt = P.run(t, mae, mfe, st, risk, H)
                    for part, m in (("design", st < HOLD_OUT), ("hold", st >= HOLD_OUT)):
                        s = P.summarize(code[m], days[m])
                        rows.append(dict(sym=sym, cfg=cfg["name"], H=H, risk=risk, part=part, wr=wr, ntr=len(t), **s))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print(SYMS, flush=True)
    real = study()
    real.to_csv("results/prop_study.csv", index=False)
    null = study(shift=7919)
    null.to_csv("results/prop_study_null.csv", index=False)
    print("done")
