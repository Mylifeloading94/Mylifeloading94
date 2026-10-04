"""
Aquafunded 'Pay After Pass' challenge simulator (rules from help.aquafunded.com/en/articles/13322298):
  start $25,000 | target +3% ($750, balance) | max drawdown 5% TRAILING on equity incl. floating P&L (level = peak - $1,250)
  | account permanently closed if floating P&L falls below -1% of the starting balance (-$250)
  | evaluation daily-drawdown / time limit / news / bot rules: NOT stated on that page (see README)
Each simulated challenge starts on a calendar day and trades the strategy's ledger one trade at a time with a FIXED dollar
risk per trade. A trade's adverse excursion (MAE) comes from the worst bid/ask extreme of every bar it was open.
The drawdown level uses the PEAK equity including each trade's best excursion (MFE), which is the stricter reading.
"""
import numpy as np, pandas as pd
from numba import njit

START, TARGET_USD, DD_USD, FLOAT_CAP = 25_000.0, 750.0, 1_250.0, 250.0


def excursions(h1, t):
    """MAE / MFE of each trade, in R. A stopped trade cannot float below its stop, so the exit bar is excluded for stops."""
    bl, bh, al, ah = (h1[c].to_numpy("float64") for c in ("bl", "bh", "al", "ah"))
    ao, bo = h1.ao.to_numpy("float64"), h1.bo.to_numpy("float64")
    ix = h1.index
    i0 = ix.get_indexer(pd.DatetimeIndex(t.entry_time)); i1 = ix.get_indexer(pd.DatetimeIndex(t.exit_time))
    mae = np.zeros(len(t)); mfe = np.zeros(len(t))
    for k, (a, b, d, risk, r, why) in enumerate(zip(i0, i1, t.dir.to_numpy(), t.risk.to_numpy(), t.r.to_numpy(), t.reason.to_numpy())):
        if a < 0 or b < 0:
            mae[k] = max(-r, 0); continue
        hi_end = b if why == 1 else b + 1                      # stops: exclude the exit bar's own extreme
        sl = slice(a, max(hi_end, a))
        if d == 1:
            ent = ao[a]; adv = ent - bl[sl].min() if hi_end > a else 0.0; fav = bh[sl].max() - ent if hi_end > a else 0.0
        else:
            ent = bo[a]; adv = ah[sl].max() - ent if hi_end > a else 0.0; fav = ent - al[sl].min() if hi_end > a else 0.0
        mae[k] = max(adv / risk, -r if r < 0 else 0.0, 0.0); mfe[k] = max(fav / risk, r if r > 0 else 0.0, 0.0)
    return mae, mfe


@njit(cache=True)
def _challenge(first, ent, ext, r, mae, mfe, risk_usd, start_min, horizon_min, trailing, float_cap, out_code, out_days, out_trades):
    n = len(r)
    for s in range(len(first)):
        bal = 25000.0; peak = 25000.0; code = 3; days = 0.0; cnt = 0
        for k in range(first[s], n):
            if ent[k] - start_min[s] > horizon_min:
                code = 0; break
            adverse = mae[k] * risk_usd; fav = mfe[k] * risk_usd
            floor = (peak - 1250.0) if trailing else (25000.0 - 1250.0)
            cnt += 1
            if adverse >= float_cap or bal - adverse <= floor:
                code = 2; days = (ent[k] - start_min[s]) / 1440.0; break
            before = bal
            bal += r[k] * risk_usd
            peak = max(peak, before + fav, bal)
            if bal >= 25750.0:
                if ext[k] - start_min[s] > horizon_min:
                    code = 0
                else:
                    code = 1; days = (ext[k] - start_min[s]) / 1440.0
                break
        out_code[s] = code; out_days[s] = days; out_trades[s] = cnt


def run(trades, mae, mfe, starts, risk_usd, horizon_days, trailing=True, float_cap=FLOAT_CAP):
    """trades: DataFrame sorted by entry_time. starts: DatetimeIndex. Returns (code, days, ntrades) arrays.
    codes: 1 passed, 2 breached, 0 not passed within the horizon, 3 ran out of data."""
    ent = (pd.DatetimeIndex(trades.entry_time).as_unit("ns").asi8 // 60_000_000_000).astype(np.int64)
    ext = (pd.DatetimeIndex(trades.exit_time).as_unit("ns").asi8 // 60_000_000_000).astype(np.int64)
    sm = (starts.as_unit("ns").asi8 // 60_000_000_000).astype(np.int64)
    first = np.searchsorted(ent, sm).astype(np.int64)
    n = len(starts); code = np.zeros(n, np.int64); days = np.zeros(n); cnt = np.zeros(n, np.int64)
    _challenge(first, ent, ext, trades.r.to_numpy("float64"), mae, mfe, float(risk_usd), sm, int(horizon_days * 1440), bool(trailing), float(float_cap), code, days, cnt)
    return code, days, cnt


def summarize(code, days):
    n = len(code)
    if n == 0:
        return dict(n=0, pass_=np.nan, fail=np.nan, open_=np.nan, med_days=np.nan)
    return dict(n=n, pass_=100 * np.mean(code == 1), fail=100 * np.mean(code == 2), open_=100 * np.mean((code == 0) | (code == 3)),
                med_days=float(np.median(days[code == 1])) if (code == 1).any() else np.nan)
