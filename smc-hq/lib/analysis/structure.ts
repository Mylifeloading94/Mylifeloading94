import type { Candle } from '@/types';

export interface Swing { i: number; price: number; type: 'H' | 'L'; t: number }
export type Dir = 'bullish' | 'bearish';
export interface StructureEvent { type: 'BOS' | 'CHOCH'; dir: Dir; i: number; level: number; swingIndex: number; displacement: boolean; t: number }
export type Trend = 'bullish' | 'bearish' | 'ranging';

/** Fractal pivots (k bars each side), cleaned so highs and lows strictly alternate. */
export function findSwings(c: Candle[], k = 2): Swing[] {
  const raw: Swing[] = [];
  for (let i = k; i < c.length - k; i++) {
    let isH = true, isL = true;
    for (let j = 1; j <= k; j++) {
      if (!(c[i].h > c[i - j].h && c[i].h >= c[i + j].h)) isH = false;
      if (!(c[i].l < c[i - j].l && c[i].l <= c[i + j].l)) isL = false;
    }
    if (isH) raw.push({ i, price: c[i].h, type: 'H', t: c[i].t });
    if (isL) raw.push({ i, price: c[i].l, type: 'L', t: c[i].t });
  }
  raw.sort((a, b) => a.i - b.i || (a.type === 'H' ? -1 : 1));
  const out: Swing[] = [];
  for (const s of raw) {
    const prev = out[out.length - 1];
    if (prev && prev.type === s.type) {
      if ((s.type === 'H' && s.price > prev.price) || (s.type === 'L' && s.price < prev.price)) out[out.length - 1] = s;
    } else out.push(s);
  }
  return out;
}

export function labelSwingTrend(swings: Swing[]): Trend {
  const hs = swings.filter((s) => s.type === 'H').slice(-2);
  const ls = swings.filter((s) => s.type === 'L').slice(-2);
  if (hs.length < 2 || ls.length < 2) return 'ranging';
  const hh = hs[1].price > hs[0].price, hl = ls[1].price > ls[0].price;
  if (hh && hl) return 'bullish';
  if (!hh && !hl) return 'bearish';
  return 'ranging';
}

export interface StructureResult {
  trend: Trend;
  events: StructureEvent[];
  swings: Swing[];
  lastHigh: Swing | null; // most recent confirmed swing high
  lastLow: Swing | null;
}

/**
 * Walks candles in order. A close beyond the most recent (unbroken) swing is a break:
 * BOS if it continues the prevailing trend, CHoCH/MSS if it flips it.
 */
export function analyzeStructure(c: Candle[], atrArr: number[], k = 2): StructureResult {
  const swings = findSwings(c, k);
  const events: StructureEvent[] = [];
  let state: Trend = 'ranging';
  let hi: Swing | null = null, lo: Swing | null = null;
  let sp = 0;
  for (let i = 0; i < c.length; i++) {
    while (sp < swings.length && swings[sp].i + k <= i) {
      const s = swings[sp++];
      if (s.type === 'H') hi = s; else lo = s;
    }
    const body = Math.abs(c[i].c - c[i].o);
    const disp = body >= 1.2 * atrArr[i];
    if (hi && c[i].c > hi.price) {
      events.push({ type: state === 'bearish' ? 'CHOCH' : 'BOS', dir: 'bullish', i, level: hi.price, swingIndex: hi.i, displacement: disp, t: c[i].t });
      state = 'bullish'; hi = null;
    } else if (lo && c[i].c < lo.price) {
      events.push({ type: state === 'bullish' ? 'CHOCH' : 'BOS', dir: 'bearish', i, level: lo.price, swingIndex: lo.i, displacement: disp, t: c[i].t });
      state = 'bearish'; lo = null;
    }
  }
  const swingTrend = labelSwingTrend(swings);
  // Structure is close-based: a wick through a swing (a sweep) does not change it.
  const trend: Trend = state === 'ranging' ? swingTrend : state;
  const hs = swings.filter((s) => s.type === 'H'), ls = swings.filter((s) => s.type === 'L');
  return { trend, events, swings, lastHigh: hs[hs.length - 1] ?? null, lastLow: ls[ls.length - 1] ?? null };
}
