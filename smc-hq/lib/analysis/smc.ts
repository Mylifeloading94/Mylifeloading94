import type { Candle } from '@/types';
import type { Dir, Swing } from './structure';

export interface Zone { dir: Dir; i: number; low: number; high: number; t: number }
export interface Fvg extends Zone { mitigated: boolean }
export interface OrderBlock extends Zone { mitigated: boolean }
export interface Breaker extends Zone { origin: 'order_block' }

/** Three-candle imbalance. `i` is the completion candle. Mitigated once price closes through the whole gap. */
export function findFvgs(c: Candle[], atrArr: number[], minAtr = 0.1): Fvg[] {
  const out: Fvg[] = [];
  for (let m = 1; m < c.length - 1; m++) {
    const a = c[m - 1], b = c[m + 1];
    let z: Fvg | null = null;
    if (b.l > a.h && b.l - a.h >= minAtr * atrArr[m]) z = { dir: 'bullish', i: m + 1, low: a.h, high: b.l, t: c[m + 1].t, mitigated: false };
    else if (b.h < a.l && a.l - b.h >= minAtr * atrArr[m]) z = { dir: 'bearish', i: m + 1, low: b.h, high: a.l, t: c[m + 1].t, mitigated: false };
    if (!z) continue;
    for (let j = z.i + 1; j < c.length; j++) {
      if (z.dir === 'bullish' && c[j].c < z.low) { z.mitigated = true; break; }
      if (z.dir === 'bearish' && c[j].c > z.high) { z.mitigated = true; break; }
    }
    out.push(z);
  }
  return out;
}

/** Order block = last opposite-colour candle before a displacement that left an FVG. */
export function findOrderBlocks(c: Candle[], fvgs: Fvg[]): { obs: OrderBlock[]; breakers: Breaker[] } {
  const obs: OrderBlock[] = [];
  const seen = new Set<string>();
  for (const f of fvgs) {
    const mid = f.i - 1;
    for (let j = mid - 1; j >= Math.max(0, mid - 6); j--) {
      const opp = f.dir === 'bullish' ? c[j].c < c[j].o : c[j].c > c[j].o;
      if (!opp) continue;
      const key = `${f.dir}:${j}`;
      if (!seen.has(key)) {
        seen.add(key);
        const ob: OrderBlock = { dir: f.dir, i: j, low: c[j].l, high: c[j].h, t: c[j].t, mitigated: false };
        for (let q = mid + 1; q < c.length; q++) {
          if (ob.dir === 'bullish' && c[q].c < ob.low) { ob.mitigated = true; break; }
          if (ob.dir === 'bearish' && c[q].c > ob.high) { ob.mitigated = true; break; }
        }
        obs.push(ob);
      }
      break;
    }
  }
  // Breaker: an OB that was closed through flips polarity; it stays valid until closed through the other way.
  const breakers: Breaker[] = [];
  for (const ob of obs) {
    if (!ob.mitigated) continue;
    let q = -1;
    for (let j = ob.i + 1; j < c.length; j++) {
      if ((ob.dir === 'bullish' && c[j].c < ob.low) || (ob.dir === 'bearish' && c[j].c > ob.high)) { q = j; break; }
    }
    if (q < 0) continue;
    const flipped: Dir = ob.dir === 'bullish' ? 'bearish' : 'bullish';
    let alive = true;
    for (let j = q + 1; j < c.length; j++) {
      if ((flipped === 'bearish' && c[j].c > ob.high) || (flipped === 'bullish' && c[j].c < ob.low)) { alive = false; break; }
    }
    if (alive) breakers.push({ dir: flipped, i: q, low: ob.low, high: ob.high, t: c[q].t, origin: 'order_block' });
  }
  return { obs, breakers };
}

export type PoolKind = 'equal' | 'swing' | 'previous_day' | 'previous_week' | 'session' | 'htf_swing';
export interface Pool { side: 'buy' | 'sell'; price: number; kind: PoolKind; label: string; i: number }
export interface Sweep { side: 'buy' | 'sell'; price: number; i: number; t: number; extreme: number; pool: Pool }

/** Equal highs / lows: swing points within `tol` of each other. */
export function equalLevels(swings: Swing[], tol: number): Pool[] {
  const pools: Pool[] = [];
  for (const type of ['H', 'L'] as const) {
    const s = swings.filter((x) => x.type === type);
    for (let a = 0; a < s.length; a++) {
      for (let b = a + 1; b < s.length; b++) {
        if (Math.abs(s[a].price - s[b].price) <= tol) {
          const price = type === 'H' ? Math.max(s[a].price, s[b].price) : Math.min(s[a].price, s[b].price);
          pools.push({ side: type === 'H' ? 'buy' : 'sell', price, kind: 'equal', label: type === 'H' ? 'equal highs' : 'equal lows', i: s[b].i });
        }
      }
    }
  }
  return pools;
}

/**
 * Finds a sweep: a wick through the pool followed (within 4 candles) by a close back on the original side,
 * with the pool still intact (never closed through) before that candle. Returns the most recent sweep per side.
 */
export function findSweeps(c: Candle[], pools: Pool[], lookback: number): Sweep[] {
  const out: Sweep[] = [];
  const start = Math.max(1, c.length - lookback);
  for (const p of pools) {
    for (let i = Math.max(start, p.i + 1); i < c.length; i++) {
      const pierced = p.side === 'buy' ? c[i].h > p.price : c[i].l < p.price;
      const brokenByClose = p.side === 'buy' ? c[i].c > p.price : c[i].c < p.price;
      if (!pierced) continue;
      let ret = -1;
      for (let j = i; j <= Math.min(c.length - 1, i + 4); j++) {
        const back = p.side === 'buy' ? c[j].c < p.price : c[j].c > p.price;
        if (back) { ret = j; break; }
      }
      if (ret < 0) { if (brokenByClose) break; else continue; }
      let extreme = p.side === 'buy' ? -Infinity : Infinity;
      for (let j = i; j <= ret; j++) extreme = p.side === 'buy' ? Math.max(extreme, c[j].h) : Math.min(extreme, c[j].l);
      out.push({ side: p.side, price: p.price, i, t: c[i].t, extreme, pool: p });
      break;
    }
  }
  return out;
}

export interface DealingRange { high: number; low: number; eq: number; position: 'premium' | 'discount' | 'equilibrium' }

export function dealingRange(swings: Swing[], price: number): DealingRange | null {
  const h = [...swings].reverse().find((s) => s.type === 'H');
  const l = [...swings].reverse().find((s) => s.type === 'L');
  if (!h || !l || h.price <= l.price) return null;
  const eq = (h.price + l.price) / 2;
  const band = (h.price - l.price) * 0.05;
  const position = price > eq + band ? 'premium' : price < eq - band ? 'discount' : 'equilibrium';
  return { high: h.price, low: l.price, eq, position };
}

/** Fibonacci retracement of the most recent impulse leg and where price sits in it. */
export function fibPosition(swings: Swing[], price: number): { text: string; ote: boolean } {
  const n = swings.length;
  if (n < 2) return { text: 'n/a', ote: false };
  const a = swings[n - 2], b = swings[n - 1];
  const range = Math.abs(b.price - a.price);
  if (range === 0) return { text: 'n/a', ote: false };
  // retracement of the leg a→b measured back from b
  const r = b.type === 'H' ? (b.price - price) / range : (price - b.price) / range;
  const pct = Math.round(r * 1000) / 10;
  if (r < 0) return { text: `beyond leg extreme (${pct}%)`, ote: false };
  if (r > 1) return { text: `leg fully retraced (${pct}%)`, ote: false };
  const ote = r >= 0.62 && r <= 0.79;
  return { text: `${pct}% retrace of last leg${ote ? ' (OTE 62–79%)' : ''}`, ote };
}

/** Horizontal support/resistance from clustered swing points (≥2 touches). */
export function srLevels(swings: Swing[], price: number, tol: number) {
  const prices = swings.map((s) => s.price).sort((a, b) => a - b);
  const clusters: { p: number; n: number }[] = [];
  for (const p of prices) {
    const cl = clusters[clusters.length - 1];
    if (cl && Math.abs(p - cl.p / cl.n) <= tol) { cl.p += p; cl.n += 1; } else clusters.push({ p, n: 1 });
  }
  const lv = clusters.filter((x) => x.n >= 2).map((x) => x.p / x.n);
  return {
    support: lv.filter((x) => x < price).sort((a, b) => b - a).slice(0, 3),
    resistance: lv.filter((x) => x > price).sort((a, b) => a - b).slice(0, 3),
  };
}
