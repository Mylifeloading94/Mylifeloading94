import type { Candle, Timeframe } from '@/types';

export const TF_MS: Record<Timeframe, number> = {
  M5: 5 * 60_000, M15: 15 * 60_000, H1: 3_600_000, H4: 4 * 3_600_000, D1: 86_400_000,
};

/** Aggregate lower-timeframe candles into `tf` buckets (UTC-aligned). */
export function resample(src: Candle[], tf: Timeframe): Candle[] {
  const ms = TF_MS[tf];
  const out: Candle[] = [];
  let cur: Candle | null = null;
  for (const c of src) {
    const bucket = Math.floor(c.t / ms) * ms;
    if (!cur || cur.t !== bucket) {
      if (cur) out.push(cur);
      cur = { t: bucket, o: c.o, h: c.h, l: c.l, c: c.c, v: c.v };
    } else {
      cur.h = Math.max(cur.h, c.h);
      cur.l = Math.min(cur.l, c.l);
      cur.c = c.c;
      cur.v += c.v;
    }
  }
  if (cur) out.push(cur);
  return out;
}
