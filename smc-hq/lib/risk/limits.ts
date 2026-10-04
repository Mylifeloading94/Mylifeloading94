import type { Settings, Signal } from '@/types';

const OPEN = new Set(['PENDING', 'ACTIVE']);
const sameUtcDay = (a: number, b: number) => Math.floor(a / 86_400_000) === Math.floor(b / 86_400_000);

/**
 * Daily / simultaneous limits apply to LIVE signals only. Demo signals are excluded so
 * demonstrating the system never consumes (or is blocked by) real risk budget.
 */
export function checkSignalLimits(settings: Settings, signals: Signal[], now: number): { allowed: boolean; reason: string } {
  const live = signals.filter((s) => s.data_mode === 'LIVE');
  const today = live.filter((s) => sameUtcDay(Date.parse(s.timestamp), now));
  if (today.length >= settings.max_daily_signals) return { allowed: false, reason: `Daily signal limit reached (${today.length}/${settings.max_daily_signals})` };
  const open = live.filter((s) => OPEN.has(s.status));
  if (open.length >= settings.max_simultaneous_signals) return { allowed: false, reason: `Simultaneous signal limit reached (${open.length}/${settings.max_simultaneous_signals})` };
  return { allowed: true, reason: 'Within limits' };
}

/** Same sweep already signalled, or an open signal on this pair & direction. */
export function findDuplicate(signals: Signal[], fingerprint: string, pair: string, direction: string, mode: string): Signal | undefined {
  return signals.find((s) =>
    s.data_mode === mode && (s.fingerprint === fingerprint || (mode === 'LIVE' && s.pair === pair && s.direction === direction && OPEN.has(s.status))));
}
