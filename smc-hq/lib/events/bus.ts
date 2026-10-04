import type { AgentId, BusEvent, BusEventType } from '@/types';

type Listener = (e: BusEvent) => void;
interface BusState { listeners: Set<Listener>; buffer: BusEvent[]; seq: number }
const g = globalThis as unknown as { __smcBus?: BusState };
const state = (): BusState => (g.__smcBus ??= { listeners: new Set(), buffer: [], seq: 0 });

/** In-process pub/sub. Agents talk by publishing typed, schema-validated payloads — never by touching each other's state. */
export function emit<T>(type: BusEventType, from: BusEvent['from'], to: BusEvent['to'], payload: T): BusEvent<T> {
  const s = state();
  const e: BusEvent<T> = { id: `${Date.now().toString(36)}-${(++s.seq).toString(36)}`, ts: new Date().toISOString(), type, from, to, payload };
  s.buffer.push(e);
  if (s.buffer.length > 300) s.buffer.splice(0, s.buffer.length - 300);
  for (const l of s.listeners) { try { l(e); } catch { /* a bad subscriber must not break the pipeline */ } }
  return e;
}
export function subscribe(l: Listener): () => void { const s = state(); s.listeners.add(l); return () => s.listeners.delete(l); }
export const recentEvents = (n = 100): BusEvent[] => state().buffer.slice(-n);
export const resetBus = () => { g.__smcBus = undefined; };
export type { AgentId };
