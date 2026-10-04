import type { Candle, DataMode, MarketAnalysis, Timeframe } from '@/types';
import { atr as atrFn, ema, rsi as rsiFn, last } from './indicators';
import { analyzeStructure, type Dir, type StructureResult, type Trend } from './structure';
import {
  dealingRange, equalLevels, findFvgs, findOrderBlocks, findSweeps, fibPosition, srLevels,
  type Breaker, type Fvg, type OrderBlock, type Pool, type Sweep,
} from './smc';
import { previousLevels, sessionAt, sessionRanges } from './sessions';

export type CandleSet = Record<Timeframe, Candle[]>;

export interface TfAnalysis {
  tf: Timeframe;
  candles: Candle[];
  atr: number[];
  struct: StructureResult;
  fvgs: Fvg[];
  obs: OrderBlock[];
  breakers: Breaker[];
}

const DIGITS = (pair: string) => (pair.endsWith('JPY') ? 3 : pair === 'XAUUSD' ? 2 : 5);
export const roundPrice = (pair: string, v: number) => Number(v.toFixed(DIGITS(pair)));

export function analyzeTf(tf: Timeframe, candles: Candle[]): TfAnalysis {
  const atrArr = atrFn(candles, 14);
  const struct = analyzeStructure(candles, atrArr, 2);
  const fvgs = findFvgs(candles, atrArr);
  const { obs, breakers } = findOrderBlocks(candles, fvgs);
  return { tf, candles, atr: atrArr, struct, fvgs, obs, breakers };
}

const vote = (t: Trend) => (t === 'bullish' ? 1 : t === 'bearish' ? -1 : 0);

/** HTF bias: H4 carries double weight; needs agreement from D1 or H1. A lone H4 trend stays neutral. */
export function htfBias(d1: Trend, h4: Trend, h1: Trend): 'bullish' | 'bearish' | 'neutral' {
  const s = vote(d1) + 2 * vote(h4) + vote(h1);
  return s >= 3 ? 'bullish' : s <= -3 ? 'bearish' : 'neutral';
}

const regimeOf = (cur: number, series: number[]) => {
  const tail = series.slice(-60);
  const avg = tail.reduce((a, b) => a + b, 0) / Math.max(1, tail.length);
  const r = avg > 0 ? cur / avg : 1;
  return r < 0.6 ? 'low' : r > 2.4 ? 'extreme' : r > 1.6 ? 'high' : 'normal';
};

function buildPools(pair: string, a: Record<Timeframe, TfAnalysis>, now: number, prev: ReturnType<typeof previousLevels>, sess: ReturnType<typeof sessionRanges>): Pool[] {
  const m15 = a.M15;
  const atrM15 = last(m15.atr);
  const pools: Pool[] = [];
  const recent = <T extends { i: number }>(s: T[], n: number, len: number) => s.filter((x) => x.i >= len - n);
  const sw15 = recent(m15.struct.swings, 120, m15.candles.length);
  for (const s of sw15) pools.push({ side: s.type === 'H' ? 'buy' : 'sell', price: s.price, kind: 'swing', label: `M15 swing ${s.type === 'H' ? 'high' : 'low'}`, i: s.i });
  pools.push(...equalLevels(sw15, 0.15 * atrM15).map((p) => ({ ...p, label: `M15 ${p.label}` })));
  // HTF swing points mapped onto M15 index space by time
  for (const tf of ['H1', 'H4'] as const) {
    for (const s of recent(a[tf].struct.swings, 40, a[tf].candles.length)) {
      const idx = m15.candles.findIndex((x) => x.t >= s.t);
      if (idx < 0) continue;
      pools.push({ side: s.type === 'H' ? 'buy' : 'sell', price: s.price, kind: 'htf_swing', label: `${tf} swing ${s.type === 'H' ? 'high' : 'low'}`, i: idx });
    }
  }
  const dayStartIdx = Math.max(0, m15.candles.findIndex((x) => x.t >= Math.floor(now / 86_400_000) * 86_400_000));
  if (prev.pdh != null) pools.push({ side: 'buy', price: prev.pdh, kind: 'previous_day', label: 'previous day high', i: dayStartIdx });
  if (prev.pdl != null) pools.push({ side: 'sell', price: prev.pdl, kind: 'previous_day', label: 'previous day low', i: dayStartIdx });
  if (prev.pwh != null) pools.push({ side: 'buy', price: prev.pwh, kind: 'previous_week', label: 'previous week high', i: 0 });
  if (prev.pwl != null) pools.push({ side: 'sell', price: prev.pwl, kind: 'previous_week', label: 'previous week low', i: 0 });
  for (const s of sess.filter((x) => x.complete)) {
    const idx = m15.candles.findIndex((x) => x.t >= Math.floor(now / 86_400_000) * 86_400_000 + (s.name === 'ASIAN' ? 7 : 16) * 3_600_000);
    pools.push({ side: 'buy', price: s.high, kind: 'session', label: `${s.name.toLowerCase()} session high`, i: Math.max(0, idx) });
    pools.push({ side: 'sell', price: s.low, kind: 'session', label: `${s.name.toLowerCase()} session low`, i: Math.max(0, idx) });
  }
  return pools;
}

const dirOf = (bias: string): Dir | null => (bias === 'bullish' ? 'bullish' : bias === 'bearish' ? 'bearish' : null);

/** Build the full structured report for one pair from five timeframes of candles. */
export function buildMarketAnalysis(pair: string, candles: CandleSet, mode: DataMode, now: number): MarketAnalysis {
  const a = {
    D1: analyzeTf('D1', candles.D1), H4: analyzeTf('H4', candles.H4), H1: analyzeTf('H1', candles.H1),
    M15: analyzeTf('M15', candles.M15), M5: analyzeTf('M5', candles.M5),
  } as Record<Timeframe, TfAnalysis>;
  const price = last(candles.M5).c;
  const atrM15 = last(a.M15.atr), atrH1 = last(a.H1.atr);
  const bias = htfBias(a.D1.struct.trend, a.H4.struct.trend, a.H1.struct.trend);
  const prev = previousLevels(candles.D1, now);
  const sess = sessionRanges(candles.M15, now);
  const pools = buildPools(pair, a, now, prev, sess);
  const sweepsAll = findSweeps(a.M15.candles, pools, 90);
  const dir = dirOf(bias);

  // Opposing liquidity for the bias direction: bullish bias wants a sell-side sweep (below lows).
  const wantSide = dir === 'bullish' ? 'sell' : dir === 'bearish' ? 'buy' : null;
  const rank = (s: Sweep) => (s.pool.kind === 'equal' ? 3 : s.pool.kind === 'swing' ? 1 : 2);
  const candidates = sweepsAll.filter((s) => s.side === wantSide).sort((x, y) => y.i - x.i || rank(y) - rank(x));
  const sweep: Sweep | undefined = candidates[0] ?? sweepsAll.sort((x, y) => y.i - x.i)[0];

  const m15Events = a.M15.struct.events;
  const lastM15 = last(m15Events);
  const m5Last = last(a.M5.struct.events);
  const evName = (e?: { type: string; dir: Dir }) => (e ? `${e.type === 'CHOCH' ? 'MSS' : 'BOS'}_${e.dir.toUpperCase()}` : 'NONE');
  const dr = dealingRange(a.H1.struct.swings, price);
  let fib = fibPosition(a.M15.struct.swings, price);
  const sr = srLevels(a.H1.struct.swings, price, 0.3 * atrH1);
  const rsiH1 = last(rsiFn(candles.H1.map((x) => x.c))), rsiM15 = last(rsiFn(candles.M15.map((x) => x.c)));
  const cH1 = candles.H1.map((x) => x.c);
  const e20 = last(ema(cH1, 20)), e50 = last(ema(cH1, 50)), e200 = last(ema(cH1, 200));
  const emaTrend = price > e20 && e20 > e50 && e50 > e200 ? 'above' : price < e20 && e20 < e50 && e50 < e200 ? 'below' : 'mixed';
  const regime = regimeOf(atrM15, a.M15.atr);

  /* ---------------- entry model ---------------- */
  let candidate: MarketAnalysis['candidate'] = null;
  let liquidityEvent: MarketAnalysis['liquidity_event'] = 'none';
  let liquidityDetail = 'No recent liquidity sweep detected';
  let liquidityQuality: MarketAnalysis['liquidity_quality'] = 'none';
  let fvgFlag = false, obFlag = false, breakerFlag = false;
  const confirmations: string[] = [];
  let m5Confirm = false;
  let pdOverride: 'premium' | 'discount' | 'equilibrium' | null = null;
  let sweepExtreme: number | null = sweep ? sweep.extreme : null;

  if (sweep) {
    liquidityEvent = sweep.side === 'sell' ? 'sell_side_sweep' : 'buy_side_sweep';
    liquidityDetail = `${sweep.side === 'sell' ? 'Sell' : 'Buy'}-side liquidity swept (${sweep.pool.label} @ ${roundPrice(pair, sweep.price)})`;
    liquidityQuality = sweep.pool.kind === 'equal' ? 'equal_levels' : sweep.pool.kind === 'swing' ? 'swing' : 'htf_level';
  }

  if (dir && sweep && wantSide === sweep.side) {
    const ev = m15Events.filter((e) => e.dir === dir && e.i > sweep.i).sort((x, y) => (y.type === 'CHOCH' ? 1 : 0) - (x.type === 'CHOCH' ? 1 : 0) || y.i - x.i)[0];
    const fvgs = a.M15.fvgs.filter((f) => f.dir === dir && f.i >= sweep.i && !f.mitigated);
    const obs = a.M15.obs.filter((o) => o.dir === dir && o.i >= sweep.i - 3 && !o.mitigated);
    const brk = a.M15.breakers.filter((b) => b.dir === dir && b.i >= sweep.i - 3);
    fvgFlag = fvgs.length > 0; obFlag = obs.length > 0; breakerFlag = brk.length > 0;
    const fvg = fvgs.sort((x, y) => y.i - x.i)[0];
    const ob = obs.sort((x, y) => y.i - x.i)[0];
    const zoneSrc = fvg ? { low: fvg.low, high: fvg.high } : ob ? { low: ob.low, high: ob.high } : null;
    if (ev && zoneSrc) {
      const overlapsOb = !!(fvg && ob && ob.low <= fvg.high && ob.high >= fvg.low);
      const buf = 0.25 * atrM15;
      const long = dir === 'bullish';
      // The manipulation extreme is the most extreme wick between the sweep and the structure shift.
      let extreme = sweep.extreme;
      for (let j = sweep.i; j <= ev.i; j++) extreme = long ? Math.min(extreme, a.M15.candles[j].l) : Math.max(extreme, a.M15.candles[j].h);
      sweepExtreme = extreme;
      const stop = long ? Math.min(extreme, zoneSrc.low) - buf : Math.max(extreme, zoneSrc.high) + buf;
      const mid = (zoneSrc.low + zoneSrc.high) / 2;
      const risk = Math.abs(mid - stop);

      // Targets: real liquidity beyond the zone, nearest first.
      const levels: number[] = [];
      const beyondLong = Math.max(zoneSrc.high, price) + 0.3 * atrM15;
      const beyondShort = Math.min(zoneSrc.low, price) - 0.3 * atrM15;
      for (const p of pools) if (long ? p.side === 'buy' && p.price > beyondLong : p.side === 'sell' && p.price < beyondShort) levels.push(p.price);
      const dist = (p: number) => Math.abs(p - mid);
      const uniq = [...new Set(levels.map((x) => roundPrice(pair, x)))].sort((x, y) => dist(x) - dist(y));
      const spaced: number[] = [];
      for (const p of uniq) if (!spaced.length || Math.abs(p - spaced[spaced.length - 1]) >= 0.5 * atrH1) spaced.push(p);
      const tps: number[] = [];
      const projected = [false, false, false];
      const t1 = spaced.find((p) => dist(p) >= 0.5 * risk);
      if (t1 !== undefined) tps[0] = t1; else { tps[0] = mid + (long ? 1 : -1) * risk; projected[0] = true; }
      const t2 = spaced.find((p) => dist(p) >= 2 * risk && dist(p) > dist(tps[0]) + 0.3 * atrH1);
      if (t2 !== undefined) tps[1] = t2; else { tps[1] = mid + (long ? 1 : -1) * Math.max(2 * risk, dist(tps[0]) + risk); projected[1] = true; }
      const t3 = spaced.find((p) => dist(p) > dist(tps[1]) + 0.5 * atrH1);
      if (t3 !== undefined) tps[2] = t3; else { tps[2] = mid + (long ? 1 : -1) * dist(tps[1]) * 1.5; projected[2] = true; }

      // Entry state relative to the zone.
      let state: 'in_zone' | 'approaching' | 'extended' | 'invalidated';
      const beyondStop = long ? price <= stop : price >= stop;
      const pastTp1 = long ? price >= tps[0] : price <= tps[0];
      const pad = 0.1 * atrM15;
      if (beyondStop) state = 'invalidated';
      else if (long ? price <= zoneSrc.high + pad : price >= zoneSrc.low - pad) state = 'in_zone';
      else if (pastTp1) state = 'extended';
      else state = Math.abs(price - (long ? zoneSrc.high : zoneSrc.low)) <= 1.5 * atrM15 ? 'approaching' : 'extended';

      // M5 trigger: a same-direction structure shift after the sweep, or a rejection candle inside the zone.
      const m5After = a.M5.struct.events.filter((e) => e.t >= sweep.t);
      const m5Ev = m5After.length > 0 && m5After[m5After.length - 1].dir === dir;
      const lc = last(candles.M5);
      const rng = lc.h - lc.l || 1e-9;
      const wick = long ? Math.min(lc.o, lc.c) - lc.l : lc.h - Math.max(lc.o, lc.c);
      const rejection = state === 'in_zone' && wick / rng >= 0.5 && (long ? lc.c >= lc.o : lc.c <= lc.o);
      m5Confirm = (m5Ev && state !== 'extended') || rejection;

      // Fibonacci retracement of the post-sweep impulse leg (manipulation extreme → impulse extreme).
      const post = a.M15.candles.slice(sweep.i);
      const impulse = long ? Math.max(...post.map((x) => x.h)) : Math.min(...post.map((x) => x.l));
      const leg = Math.abs(impulse - extreme);
      if (leg > 0) {
        const r = long ? (impulse - price) / leg : (price - impulse) / leg;
        // Premium/discount of the setup's own dealing range (manipulation extreme → impulse extreme).
        pdOverride = r > 0.55 ? (long ? 'discount' : 'premium') : r < 0.45 ? (long ? 'premium' : 'discount') : 'equilibrium';
        const ote = r >= 0.62 && r <= 0.79;
        fib = { text: `${(r * 100).toFixed(1)}% retrace of the post-sweep impulse${ote ? ' (OTE 62–79%)' : r >= 0.5 && r < 0.62 ? ' (equilibrium)' : ''}`, ote };
      }
      candidate = {
        direction: long ? 'long' : 'short',
        entry_zone: { low: roundPrice(pair, zoneSrc.low), high: roundPrice(pair, zoneSrc.high) },
        stop_loss: roundPrice(pair, stop),
        invalidation: roundPrice(pair, extreme),
        take_profits: tps.map((x) => roundPrice(pair, x)) as [number, number, number],
        tp_projected: projected,
        entry_state: state,
        m5_confirmation: m5Confirm,
        zone_source: fvg && overlapsOb ? 'FVG+OB' : fvg ? 'FVG' : 'OB',
      };
    }
  }

  const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
  for (const tf of ['D1', 'H4', 'H1'] as const) if (dir && a[tf].struct.trend === dir) confirmations.push(`${tf} ${dir} structure`);
  if (candidate && sweep) {
    confirmations.push(`${cap(sweep.side)}-side liquidity swept`);
    const ev = m15Events.filter((e) => e.dir === dir && e.i > sweep.i).sort((x, y) => (y.type === 'CHOCH' ? 1 : 0) - (x.type === 'CHOCH' ? 1 : 0))[0];
    if (ev) confirmations.push(`M15 ${ev.type === 'CHOCH' ? 'MSS' : 'BOS'}`);
    if (fvgFlag) confirmations.push(`${cap(dir ?? '')} FVG`);
    if (obFlag) confirmations.push(`${cap(dir ?? '')} order block`);
    if (candidate.m5_confirmation) confirmations.push('M5 entry confirmation');
  }
  if (dir) confirmations.push('HTF alignment');

  const sessionNow = sessionAt(now);
  const summary = dir
    ? `${bias.toUpperCase()} bias · ${candidate ? `${candidate.direction.toUpperCase()} model on ${candidate.zone_source} (${candidate.entry_state.replace('_', ' ')})` : 'no complete entry model'}`
    : 'No HTF bias — D1/H4/H1 not aligned';

  return {
    pair,
    timestamp: new Date(now).toISOString(),
    data_mode: mode,
    price: roundPrice(pair, price),
    session: sessionNow,
    htf_bias: bias,
    structure: { D1: a.D1.struct.trend, H4: a.H4.struct.trend, H1: a.H1.struct.trend, M15: a.M15.struct.trend, M5: a.M5.struct.trend },
    m15_event: evName(lastM15),
    m5_event: evName(m5Last),
    liquidity_event: liquidityEvent,
    liquidity_detail: liquidityDetail,
    liquidity_quality: liquidityQuality,
    sweep_time: sweep ? sweep.t : null,
    sweep_extreme: sweepExtreme != null ? roundPrice(pair, sweepExtreme) : null,
    fvg: fvgFlag,
    order_block: obFlag,
    breaker_block: breakerFlag,
    premium_discount: pdOverride ?? (dr ? dr.position : 'equilibrium'),
    fib_zone: fib.text,
    volatility: { atr_m15: Number(atrM15.toPrecision(5)), atr_h1: Number(atrH1.toPrecision(5)), regime },
    indicators: { rsi_h1: Number(rsiH1.toFixed(1)), rsi_m15: Number(rsiM15.toFixed(1)), ema_trend_h1: emaTrend },
    levels: {
      pdh: prev.pdh, pdl: prev.pdl, pwh: prev.pwh, pwl: prev.pwl,
      session_high: sess.length ? Math.max(...sess.map((s) => s.high)) : null,
      session_low: sess.length ? Math.min(...sess.map((s) => s.low)) : null,
      support: sr.support.map((x) => roundPrice(pair, x)),
      resistance: sr.resistance.map((x) => roundPrice(pair, x)),
    },
    candidate,
    confirmations,
    summary,
  };
}
