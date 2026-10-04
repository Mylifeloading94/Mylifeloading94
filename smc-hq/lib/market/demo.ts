import type { Candle, Timeframe } from '@/types';
import { resample } from '@/lib/analysis/resample';
import { sessionAt } from '@/lib/analysis/sessions';
import type { MarketDataProvider } from './types';

/* Deterministic PRNG so demo runs are reproducible. */
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const hash = (s: string) => { let h = 2166136261; for (const ch of s) h = Math.imul(h ^ ch.charCodeAt(0), 16777619); return h >>> 0; };
const gauss = (r: () => number) => Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r());

const BASE: Record<string, { p: number; daily: number }> = {
  EURUSD: { p: 1.085, daily: 0.0045 }, GBPUSD: { p: 1.27, daily: 0.005 }, USDJPY: { p: 150, daily: 0.0055 },
  USDCHF: { p: 0.88, daily: 0.0045 }, USDCAD: { p: 1.36, daily: 0.0042 }, AUDUSD: { p: 0.66, daily: 0.005 },
  NZDUSD: { p: 0.61, daily: 0.005 }, EURJPY: { p: 163, daily: 0.0058 }, GBPJPY: { p: 190, daily: 0.0065 },
  CADJPY: { p: 110, daily: 0.0055 }, AUDJPY: { p: 99, daily: 0.006 }, XAUUSD: { p: 3340, daily: 0.011 },
};
export const DEMO_BASE = BASE;

const M5 = 5 * 60_000;
const BARS = 30 * 288; // 30 days of M5

/** Leg: move linearly to `to` over `bars` M5 bars with `wig` × (price scale) noise. */
interface Leg { bars: number; to: number; wig?: number }

function renderPath(start: number, legs: Leg[], scale: number, r: () => number): number[] {
  const out: number[] = [];
  let p = start, ar = 0;
  for (const leg of legs) {
    const step = (leg.to - p) / leg.bars;
    const target = leg.to;
    for (let i = 0; i < leg.bars; i++) {
      ar = ar * 0.55 + gauss(r) * (leg.wig ?? 1) * scale * 0.35;
      const base = p + step;
      out.push(i === leg.bars - 1 ? target : base + ar);
      p = base;
    }
    p = target;
  }
  return out;
}

function pathToCandles(path: number[], endT: number, scale: number, r: () => number, digits: number): Candle[] {
  const q = (v: number) => Number(v.toFixed(digits));
  const n = path.length;
  const out: Candle[] = [];
  let prev = path[0];
  for (let i = 0; i < n; i++) {
    const c = path[i];
    const o = prev;
    const ext = Math.abs(gauss(r)) * scale * 0.45;
    const h = Math.max(o, c) + ext * r() * 1.4;
    const l = Math.min(o, c) - ext * r() * 1.4;
    out.push({ t: endT - (n - 1 - i) * M5, o: q(o), h: q(h), l: q(l), c: q(c), v: Math.round(100 + r() * 900) });
    prev = q(c);
  }
  return out;
}

/**
 * XAUUSD "bullish sweep → MSS → FVG" scenario, scripted at M5 resolution. The analysis engine still
 * has to *find* every element in these candles — nothing is hard-coded into the report.
 */
function xauScenario(): { start: number; legs: Leg[] } {
  const d = 288;
  return {
    start: 3200,
    legs: [
      { bars: 3 * d, to: 3240 }, { bars: 1.5 * d, to: 3222 }, { bars: 3 * d, to: 3270 }, { bars: 1.5 * d, to: 3250 },
      { bars: 3 * d, to: 3300 }, { bars: 1.5 * d, to: 3282 }, { bars: 3 * d, to: 3352 }, { bars: 1.5 * d, to: 3318 },
      { bars: 3.4 * d, to: 3392 }, { bars: 1.3 * d, to: 3326 },
      // rally to a lower-timeframe high, shallow pullback (H1 higher-low), then the sweep sequence
      { bars: 1.1 * d, to: 3366 }, { bars: 0.4 * d, to: 3334 },
      { bars: 300, to: 3353, wig: 0.4 }, { bars: 180, to: 3341, wig: 0.3 },   // M15 lower-high area, equal lows begin
      { bars: 60, to: 3346, wig: 0.25 }, { bars: 48, to: 3340.6, wig: 0.2 },
      { bars: 30, to: 3343, wig: 0.2 }, { bars: 30, to: 3340.7, wig: 0.2 },    // second touch of the equal lows
      { bars: 20, to: 3343.5, wig: 0.2 },
      { bars: 6, to: 3337.4, wig: 0.2 },                                        // sweep: wick below the equal lows, closes back above
      { bars: 9, to: 3350.2, wig: 0.2 },                                        // displacement up → MSS + bullish FVG
      { bars: 40, to: 3354.5, wig: 0.2 }, { bars: 16, to: 3341.1, wig: 0.2 },   // retrace into the imbalance
      { bars: 5, to: 3342.5, wig: 0.15 },                                       // M5 reaction off the zone
    ],
  };
}

export interface DemoOptions { anchor?: number; variant?: number }

/** Simulated "now": the most recent weekday during the New York session (never the real weekend). */
export function demoAnchor(real = Date.now(), shiftMinutes = 0): number {
  let t = Math.floor(real / M5) * M5;
  const sess = sessionAt(t);
  if (!(sess === 'NEW YORK' || sess === 'LONDON/NEW YORK')) {
    const d = new Date(t);
    d.setUTCHours(15, 20, 0, 0);
    if (d.getTime() > t) d.setUTCDate(d.getUTCDate() - 1);
    while (d.getUTCDay() === 0 || d.getUTCDay() === 6) d.setUTCDate(d.getUTCDate() - 1);
    t = d.getTime();
  }
  return t + shiftMinutes * 60_000;
}

export class DemoMarketProvider implements MarketDataProvider {
  readonly name = 'DEMO DATA (simulated)';
  readonly mode = 'DEMO' as const;
  private cache = new Map<string, Record<Timeframe, Candle[]>>();
  private anchor: number;
  private variant: number;
  private startedAt = Date.now();

  constructor(opts: DemoOptions = {}) {
    this.anchor = opts.anchor ?? demoAnchor();
    this.variant = opts.variant ?? 0;
  }

  now() { return this.anchor; }

  private series(pair: string): Record<Timeframe, Candle[]> {
    const hit = this.cache.get(pair);
    if (hit) return hit;
    const base = BASE[pair] ?? { p: 1, daily: 0.005 };
    const r = mulberry32(hash(`${pair}:${this.variant}`));
    const scale = (base.p * base.daily) / Math.sqrt(288) * 0.9;
    let path: number[];
    if (pair === 'XAUUSD') {
      const sc = xauScenario();
      path = renderPath(sc.start, sc.legs, scale * 0.5, r);
      if (path.length > BARS) path = path.slice(path.length - BARS);
    } else {
      // Regime-switching random walk. Setups appear only when the engine genuinely finds them.
      const legs: Leg[] = [];
      let p = base.p * (0.97 + r() * 0.04);
      let left = BARS;
      while (left > 0) {
        const bars = Math.min(left, Math.floor(150 + r() * 700));
        const drift = (r() - 0.5) * 0.02 * base.p;
        p += drift; left -= bars;
        legs.push({ bars, to: p, wig: 1.6 });
      }
      path = renderPath(base.p, legs, scale, r);
    }
    const m5 = pathToCandles(path, this.anchor, scale, r, pair.endsWith('JPY') ? 3 : pair === 'XAUUSD' ? 2 : 5);
    const set = { M5: m5, M15: resample(m5, 'M15'), H1: resample(m5, 'H1'), H4: resample(m5, 'H4'), D1: resample(m5, 'D1') };
    this.cache.set(pair, set);
    return set;
  }

  async getCandles(pair: string, tf: Timeframe, count: number): Promise<Candle[]> {
    const s = this.series(pair)[tf];
    return s.slice(-count);
  }

  /** Last close plus a tiny time-based wobble so the world's ticker visibly moves. Demo only. */
  async getPrice(pair: string): Promise<number> {
    const m5 = this.series(pair).M5;
    const base = m5[m5.length - 1].c;
    const sc = (BASE[pair]?.p ?? 1) * 0.00004;
    const t = (Date.now() - this.startedAt) / 1000;
    return base + Math.sin(t / 3 + hash(pair)) * sc;
  }
}
