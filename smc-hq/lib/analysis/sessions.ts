import type { Candle } from '@/types';

export type SessionName = 'ASIAN' | 'LONDON' | 'LONDON/NEW YORK' | 'NEW YORK' | 'OFF-HOURS' | 'MARKET CLOSED';

/** Approximate FX sessions in UTC. Documented simplification — not exchange-exact. */
export function sessionAt(ts: number): SessionName {
  const d = new Date(ts);
  const day = d.getUTCDay();
  const h = d.getUTCHours();
  if (day === 6) return 'MARKET CLOSED';
  if (day === 0 && h < 21) return 'MARKET CLOSED';
  if (day === 5 && h >= 21) return 'MARKET CLOSED';
  if (h < 7) return 'ASIAN';
  if (h < 12) return 'LONDON';
  if (h < 16) return 'LONDON/NEW YORK';
  if (h < 21) return 'NEW YORK';
  return 'OFF-HOURS';
}

export const isMarketOpen = (ts: number) => sessionAt(ts) !== 'MARKET CLOSED';

const dayStart = (ts: number) => Math.floor(ts / 86_400_000) * 86_400_000;

export interface SessionRange { name: 'ASIAN' | 'LONDON' | 'NEW YORK'; high: number; low: number; complete: boolean }

/** High/low of today's Asian, London and New York windows (UTC) from intraday candles. */
export function sessionRanges(c: Candle[], now: number): SessionRange[] {
  const base = dayStart(now);
  const windows: [SessionRange['name'], number, number][] = [
    ['ASIAN', 0, 7], ['LONDON', 7, 16], ['NEW YORK', 12, 21],
  ];
  const out: SessionRange[] = [];
  for (const [name, from, to] of windows) {
    const a = base + from * 3_600_000;
    const b = base + to * 3_600_000;
    const inWin = c.filter((x) => x.t >= a && x.t < b && x.t <= now);
    if (!inWin.length) continue;
    out.push({
      name,
      high: Math.max(...inWin.map((x) => x.h)),
      low: Math.min(...inWin.map((x) => x.l)),
      complete: now >= b,
    });
  }
  return out;
}

/** Previous completed D1 candle and previous completed ISO week from D1 candles. */
export function previousLevels(d1: Candle[], now: number) {
  if (d1.length < 2) return { pdh: null, pdl: null, pwh: null, pwl: null };
  const today = dayStart(now);
  const completed = d1.filter((x) => x.t < today);
  const pd = completed[completed.length - 1];
  const weekStart = (ts: number) => {
    const d = new Date(dayStart(ts));
    const dow = (d.getUTCDay() + 6) % 7; // Monday=0
    return d.getTime() - dow * 86_400_000;
  };
  const thisWeek = weekStart(now);
  const prevWeek = thisWeek - 7 * 86_400_000;
  const pw = d1.filter((x) => x.t >= prevWeek && x.t < thisWeek);
  return {
    pdh: pd ? pd.h : null,
    pdl: pd ? pd.l : null,
    pwh: pw.length ? Math.max(...pw.map((x) => x.h)) : null,
    pwl: pw.length ? Math.min(...pw.map((x) => x.l)) : null,
  };
}
