import { describe, expect, it } from 'vitest';
import type { Candle } from '@/types';
import { atr, ema, rsi } from '@/lib/analysis/indicators';
import { resample } from '@/lib/analysis/resample';
import { analyzeStructure, findSwings } from '@/lib/analysis/structure';
import { equalLevels, findFvgs, findOrderBlocks, findSweeps } from '@/lib/analysis/smc';
import { htfBias } from '@/lib/analysis/analyze';
import { previousLevels, sessionAt } from '@/lib/analysis/sessions';

const mk = (rows: [number, number, number, number][], t0 = 0, step = 60_000): Candle[] => rows.map(([o, h, l, c], i) => ({ t: t0 + i * step, o, h, l, c, v: 1 }));
const line = (pts: number[]) => mk(pts.map((p, i) => [i ? pts[i - 1] : p, Math.max(p, i ? pts[i - 1] : p) + 0.2, Math.min(p, i ? pts[i - 1] : p) - 0.2, p]));

describe('indicators', () => {
  it('RSI is 100 for a pure uptrend and low for a downtrend', () => {
    const up = Array.from({ length: 40 }, (_, i) => 100 + i), down = up.map((x) => 200 - x);
    expect(rsi(up).at(-1)).toBe(100);
    expect(rsi(down).at(-1)!).toBeLessThan(5);
  });
  it('EMA tracks a constant series and ATR is positive', () => {
    expect(ema(new Array(30).fill(5), 10).at(-1)).toBeCloseTo(5);
    expect(atr(line(Array.from({ length: 40 }, (_, i) => 100 + (i % 2)))).at(-1)!).toBeGreaterThan(0);
  });
  it('resamples M5 into H1 buckets with correct OHLC', () => {
    const m5 = mk(Array.from({ length: 24 }, (_, i) => [i, i + 2, i - 1, i + 1] as [number, number, number, number]), 0, 5 * 60_000);
    const h1 = resample(m5, 'H1');
    expect(h1).toHaveLength(2);
    expect(h1[0]).toMatchObject({ o: 0, c: 12, l: -1, h: 13 });
  });
});

describe('structure', () => {
  // zig-zag with rising highs and lows, then a close below the last higher low = bearish CHoCH
  const zig = [100, 104, 101, 108, 103, 112, 107, 116, 110, 118, 100, 98];
  const c = line(zig.flatMap((p, i) => (i === 0 ? [p] : [(zig[i - 1] + p) / 2, p])));
  it('detects alternating swings and a bullish trend', () => {
    const a = atr(c);
    const s = analyzeStructure(c.slice(0, 18), a.slice(0, 18), 1);
    expect(s.swings.every((x, i) => i === 0 || x.type !== s.swings[i - 1].type)).toBe(true);
    expect(s.trend).toBe('bullish');
    expect(s.events.some((e) => e.dir === 'bullish')).toBe(true);
  });
  it('labels a break against the trend as CHoCH (MSS), not BOS', () => {
    const a = atr(c);
    const s = analyzeStructure(c, a, 1);
    const last = s.events.at(-1)!;
    expect(last.dir).toBe('bearish');
    expect(last.type).toBe('CHOCH');
  });
  it('a wick through a swing does not change structure (sweeps are not breaks)', () => {
    const base = [100, 106, 102, 108, 104, 110, 105];
    const cs = line(base.flatMap((p, i) => (i === 0 ? [p] : [(base[i - 1] + p) / 2, p])));
    const wick = [...cs, { t: cs.length * 60_000, o: 106, h: 107, l: 99, c: 106, v: 1 }, { t: (cs.length + 1) * 60_000, o: 106, h: 108, l: 105, c: 107, v: 1 }];
    const r = analyzeStructure(wick, atr(wick), 1);
    expect(r.events.filter((e) => e.dir === 'bearish')).toHaveLength(0);
  });
});

describe('liquidity, FVG and order blocks', () => {
  it('finds a bullish FVG and the order block behind it, and marks fill as mitigated', () => {
    const c = mk([[10, 10.5, 9.5, 9.8], [9.8, 10, 9.4, 9.6], [9.6, 12, 9.6, 11.8], [11.8, 12.4, 11.2, 12.2], [12.2, 12.6, 11.9, 12.4]]);
    const f = findFvgs(c, atr(c), 0.05);
    expect(f.some((x) => x.dir === 'bullish' && x.low === 10 && x.high === 11.2)).toBe(true);
    const { obs } = findOrderBlocks(c, f);
    expect(obs.some((o) => o.dir === 'bullish')).toBe(true);
    const filled = [...c, { t: 9e6, o: 12, h: 12, l: 9, c: 9.2, v: 1 }];
    expect(findFvgs(filled, atr(filled), 0.05).find((x) => x.low === 10)!.mitigated).toBe(true);
  });
  it('detects equal lows and a sell-side sweep that closes back above', () => {
    const rows: [number, number, number, number][] = [[12, 12.5, 11.5, 12], [12, 12.2, 10.0, 10.4], [10.4, 12, 10.3, 11.8], [11.8, 12.4, 10.9, 12], [12, 12.2, 10.02, 10.3], [10.3, 12.3, 10.2, 12.1], [12.1, 12.6, 11.8, 12.4], [12.4, 12.5, 9.5, 11.9], [11.9, 12.5, 11.7, 12.2], [12.2, 12.6, 12, 12.4]];
    const c = mk(rows);
    const sw = findSwings(c, 1);
    const pools = equalLevels(sw, 0.1);
    expect(pools.some((p) => p.side === 'sell' && Math.abs(p.price - 10) < 0.05)).toBe(true);
    const sweeps = findSweeps(c, pools, 20);
    expect(sweeps.some((s) => s.side === 'sell' && s.extreme === 9.5)).toBe(true);
  });
});

describe('bias & sessions', () => {
  it('requires more than a lone H4 trend for a directional bias', () => {
    expect(htfBias('ranging', 'bullish', 'ranging')).toBe('neutral');
    expect(htfBias('bullish', 'bullish', 'ranging')).toBe('bullish');
    expect(htfBias('bearish', 'bearish', 'bearish')).toBe('bearish');
    expect(htfBias('bullish', 'bearish', 'bullish')).toBe('neutral');
  });
  it('classifies sessions and the weekend closure (UTC)', () => {
    expect(sessionAt(Date.UTC(2026, 9, 1, 3))).toBe('ASIAN');
    expect(sessionAt(Date.UTC(2026, 9, 1, 9))).toBe('LONDON');
    expect(sessionAt(Date.UTC(2026, 9, 1, 13))).toBe('LONDON/NEW YORK');
    expect(sessionAt(Date.UTC(2026, 9, 1, 18))).toBe('NEW YORK');
    expect(sessionAt(Date.UTC(2026, 9, 3, 12))).toBe('MARKET CLOSED'); // Saturday
  });
  it('derives previous-day and previous-week extremes', () => {
    const day = 86_400_000, mon = Date.UTC(2026, 8, 21); // Monday
    const d1: Candle[] = Array.from({ length: 10 }, (_, i) => ({ t: mon + i * day, o: 1, h: 10 + i, l: 1 - i * 0.1, c: 2, v: 1 }));
    const lv = previousLevels(d1, mon + 9 * day + 3_600_000); // Wed of week 2
    expect(lv.pdh).toBe(10 + 8);
    expect(lv.pwh).toBe(10 + 6); // Mon-Sun week 1 → up to index 6
  });
});
