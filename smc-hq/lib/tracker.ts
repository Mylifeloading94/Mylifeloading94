import type { Candle, Signal } from '@/types';
import { getStore } from '@/lib/database';
import { getMarketProvider, type MarketDataProvider } from '@/lib/market';
import { resultFor } from '@/lib/stats';

const HOURS = 3_600_000;

/**
 * Pure state machine: walks candles after the signal and returns the patch to apply (or null).
 * Conservative: if SL and a target print in the same candle, the stop is assumed to hit first.
 */
export function evaluateSignal(s: Signal, candles: Candle[], now: number): Partial<Signal> | null {
  if (!['PENDING', 'ACTIVE', 'TP1', 'TP2'].includes(s.status)) return null;
  const long = s.direction === 'long';
  const after = candles.filter((c) => c.t >= Date.parse(s.timestamp));
  let status: Signal['status'] = s.status;
  let closedAt: string | null = s.closed_at;

  for (const c of after) {
    if (status === 'PENDING') {
      const touched = long ? c.l <= s.entry_high : c.h >= s.entry_low;
      const hitSl = long ? c.l <= s.stop_loss : c.h >= s.stop_loss;
      const missed = long ? c.h >= s.take_profit_1 : c.l <= s.take_profit_1;
      if (touched && hitSl) { status = 'STOPPED'; closedAt = new Date(c.t).toISOString(); break; } // entered and stopped in one bar
      if (touched) { status = 'ACTIVE'; continue; }
      if (missed) { status = 'CANCELLED'; closedAt = new Date(c.t).toISOString(); break; } // TP1 reached without ever filling the zone
      continue;
    }
    const hitSl = long ? c.l <= s.stop_loss : c.h >= s.stop_loss;
    const hit = (tp: number) => (long ? c.h >= tp : c.l <= tp);
    if (status === 'ACTIVE') {
      if (hitSl) { status = 'STOPPED'; closedAt = new Date(c.t).toISOString(); break; }
      if (hit(s.take_profit_3)) status = 'TP3';
      else if (hit(s.take_profit_2)) status = 'TP2';
      else if (hit(s.take_profit_1)) status = 'TP1';
    } else if (status === 'TP1' || status === 'TP2') {
      // after the first target the stop is treated as moved to break-even: a return to entry closes the signal at the reached target
      const backToEntry = long ? c.l <= s.entry : c.h >= s.entry;
      if (hit(s.take_profit_3)) status = 'TP3';
      else if (status === 'TP1' && hit(s.take_profit_2)) status = 'TP2';
      else if (backToEntry) { closedAt = new Date(c.t).toISOString(); break; }
    }
    if (status === 'TP3') { closedAt = new Date(c.t).toISOString(); break; }
  }

  if (status === 'PENDING' && now - Date.parse(s.timestamp) > 24 * HOURS) { status = 'EXPIRED'; closedAt = new Date(now).toISOString(); }
  if (status === 'ACTIVE' && now - Date.parse(s.timestamp) > 72 * HOURS) { status = 'EXPIRED'; closedAt = new Date(now).toISOString(); }
  if ((status === 'TP1' || status === 'TP2') && !closedAt && now - Date.parse(s.timestamp) > 72 * HOURS) closedAt = new Date(now).toISOString();
  if (status === s.status && closedAt === s.closed_at) return null;

  const r = resultFor(s, status);
  return {
    status, closed_at: closedAt, result_r: r,
    result: r === null ? status : `${status} ${r > 0 ? '+' : ''}${r}R`,
  };
}

/** Updates every open LIVE signal from provider candles. Demo signals are resolved manually. */
export async function trackOpenSignals(provider: MarketDataProvider = getMarketProvider()): Promise<{ checked: number; updated: string[]; errors: string[] }> {
  const store = await getStore();
  const open = (await store.listSignals({ mode: 'LIVE' })).filter((s) => ['PENDING', 'ACTIVE', 'TP1', 'TP2'].includes(s.status));
  const updated: string[] = [], errors: string[] = [];
  if (provider.mode !== 'LIVE') return { checked: 0, updated, errors: ['Tracking requires a LIVE market data provider'] };
  for (const s of open) {
    try {
      const candles = await provider.getCandles(s.pair, 'M5', 300);
      const patch = evaluateSignal(s, candles, provider.now());
      if (patch) { await store.updateSignal(s.signal_id, patch); updated.push(`${s.signal_id} → ${patch.status}`); }
    } catch (e) { errors.push(`${s.signal_id}: ${(e as Error).message}`); }
  }
  return { checked: open.length, updated, errors };
}
