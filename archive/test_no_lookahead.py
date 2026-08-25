"""
Definitive look-ahead test.

For a sample of bars, evaluate the signal twice:
  (a) with the full history available, and
  (b) with the frame TRUNCATED immediately after that bar, so no future data
      physically exists.
If any field of the two signals differs, the strategy is reading the future.
"""
import numpy as np, pandas as pd
import tl_data, strategy as st, config

p = config.locked_params()
bad = checked = sigs = 0
detail = []

for sym in ["EURUSD", "USDJPY", "XAUUSD", "GBPJPY"]:
    raw = tl_data.load(sym)
    full = st.Context(sym, raw, p)
    n = len(full.idx)
    # Target bars that ACTUALLY produce signals -- testing quiet bars proves
    # little. Also keep a stride of ordinary bars so "signal appears only with
    # future data" would still be caught.
    sig_bars = [i for i in range(2000, n - 1) if st.evaluate(full, i) is not None]
    quiet = list(range(n - 600, n - 1, 11))
    for i in sorted(set(sig_bars + quiet)):
        checked += 1
        a = st.evaluate(full, i)
        # rebuild from a feed that ENDS at this signal bar's close
        cut_ts = full.idx[i] + pd.Timedelta(minutes=p.tf_minutes)
        raw_cut = raw[raw.index < cut_ts]
        if len(raw_cut) < 5000:
            continue
        trunc = st.Context(sym, raw_cut, p)
        if len(trunc.idx) == 0 or trunc.idx[-1] != full.idx[i]:
            continue
        b = st.evaluate(trunc, len(trunc.idx) - 1)
        if (a is None) != (b is None):
            bad += 1
            detail.append(f"{sym} {full.idx[i]}: full={'sig' if a else 'None'} trunc={'sig' if b else 'None'}")
            continue
        if a is None:
            continue
        sigs += 1
        for f in ("direction", "entry_ref", "stop", "target", "score"):
            va, vb = getattr(a, f), getattr(b, f)
            if isinstance(va, float):
                if not np.isclose(va, vb, rtol=1e-9, atol=1e-12):
                    bad += 1
                    detail.append(f"{sym} {full.idx[i]}: {f} {va} != {vb}")
                    break
            elif va != vb:
                bad += 1
                detail.append(f"{sym} {full.idx[i]}: {f} {va} != {vb}")
                break

print(f"bars checked      : {checked}")
print(f"signals compared  : {sigs}")
print(f"mismatches        : {bad}")
if detail:
    print("\nFIRST MISMATCHES:")
    for d in detail[:10]:
        print("  " + d)
    print("\nLOOK-AHEAD DETECTED")
else:
    print("\nPASS - identical with and without future data. No look-ahead.")
