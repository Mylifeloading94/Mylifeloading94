"""
Account-level backtest of a trade ledger: $25,000 start, real lot sizing, mark-to-market drawdown, hard drawdown cap.

  * size = floor( equity * risk% / (stop distance * 100 oz) / 0.01 ) * 0.01 lots (min 0.01, max 5.00), from REALISED equity at entry
  * P&L  = direction * (exit - entry) * lots * 100  - commission
  * drawdown is measured on equity INCLUDING the open trade's worst adverse excursion (bid low for longs / ask high for
    shorts on every M1 bar), against the equity PEAK reached before that trade: deliberately conservative
  * CIRCUIT BREAKER: if drawdown reaches `dd_cap` the open trade is closed at that level and trading STOPS for good
Entry price, exit price and stop come from the executor, so this is the same fill model as the strategy backtest.
"""
import numpy as np, pandas as pd

CONTRACT = 100.0


def simulate(m1, trades, risk_pct, equity0=25_000.0, dd_cap=1_250.0, commission_per_lot=0.0, max_lots=5.0, halt_on_breach=True):
    bl, ah = m1.bl.to_numpy("float64"), m1.ah.to_numpy("float64")
    bh, al = m1.bh.to_numpy("float64"), m1.al.to_numpy("float64")
    eq, peak, maxdd = equity0, equity0, 0.0
    rows, halted, breach_at, skipped = [], False, None, 0
    for _, t in trades.sort_values("entry_time").iterrows():
        if halted:
            break
        d = int(t.dir); stop_dist = d * (t.entry_px - t.stop)
        if stop_dist <= 0:
            skipped += 1; continue
        lots = np.floor(eq * risk_pct / 100 / (stop_dist * CONTRACT) / 0.01) * 0.01
        lots = min(lots, max_lots)
        if lots < 0.01:
            skipped += 1; continue
        a, b = int(t.fill_i), int(t.exit_i)
        adverse = ((bl[a:b + 1] - t.entry_px) if d == 1 else (t.entry_px - ah[a:b + 1])).min()
        favour = ((bh[a:b + 1] - t.entry_px) if d == 1 else (t.entry_px - al[a:b + 1])).max()
        usd = d * (t.exit_px - t.entry_px) * lots * CONTRACT - commission_per_lot * lots
        trough = eq + min(adverse, 0.0) * lots * CONTRACT
        dd_in = peak - trough
        if dd_in >= dd_cap and halt_on_breach:                 # breaker: close at the cap and stop trading
            usd = (peak - dd_cap) - eq; halted = True; breach_at = t.entry_time
            maxdd = max(maxdd, dd_cap)
        else:
            maxdd = max(maxdd, dd_in)
        eq += usd
        peak = max(peak, eq - usd + max(favour, 0.0) * lots * CONTRACT if not halted else peak, eq)
        maxdd = max(maxdd, peak - eq)
        rows.append((t.entry_time, t.exit_time, d, lots, usd, eq))
    led = pd.DataFrame(rows, columns=["entry_time", "exit_time", "dir", "lots", "usd", "equity"])
    return led, dict(trades=len(led), skipped=skipped, net=eq - equity0, ret_pct=100 * (eq / equity0 - 1), final=eq,
                     max_dd=maxdd, breached=breach_at is not None, breach_at=breach_at,
                     wr=100 * float((led.usd > 0).mean()) if len(led) else 0.0)
