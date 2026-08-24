import sys; sys.path.insert(0,'.')
import pandas as pd
from xauusd_bot.data.histdata_provider import HistDataProvider
p = HistDataProvider()
frames = []
for y in range(2015, 2026):
    try:
        d = p.year(y)
        print(f"  {y}: {len(d):>8,} bars  {d.index[0].date()} -> {d.index[-1].date()}", flush=True)
        frames.append(d)
    except Exception as e:
        print(f"  {y}: FAILED {e}", flush=True)
d26 = p.range('2026-01-01','2026-08-25'); frames.append(d26)
print(f"  2026: {len(d26):>8,} bars")
df = pd.concat(frames).sort_index()
df = df[~df.index.duplicated(keep='first')]
df.to_pickle('data_cache/m1_full.pkl')
print(f"TOTAL {len(df):,} M1 bars  {df.index[0]} -> {df.index[-1]}")
