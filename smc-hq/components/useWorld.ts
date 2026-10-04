'use client';
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import type { BusEvent } from '@/types';
import { emptyLive, type Fx, type FxKind, type LiveState, type Snapshot } from './world-types';

let fxSeq = 0;
const mkFx = (text: string, kind: FxKind): Fx => ({ id: `fx${++fxSeq}`, text, kind, at: Date.now() });

function reduce(s: LiveState, e: BusEvent): LiveState {
  const now = Date.now();
  const p = e.payload as any;
  switch (e.type) {
    case 'pipeline.start':
      return { ...s, running: true, stage: { analyst: false, news: false, hunter: false, command: false, telegram: false }, preview: null };
    case 'pipeline.end':
      return { ...s, running: false, scanning: null };
    case 'agent.status':
      return { ...s, speech: { ...s.speech, [p.id]: p.summary } };
    case 'hunter.progress':
      return p.phase === 'analysing'
        ? { ...s, scanning: { pair: p.pair, index: 0, total: 0, phase: 'analysing' } }
        : { ...s, scanning: { pair: p.pair, index: p.index, total: p.total, phase: 'scoring' } };
    case 'market.analysis':
      return { ...s, stage: { ...s.stage, analyst: true } };
    case 'news.intel': {
      const hot = (p.items ?? []).some((i: any) => i.impact === 'HIGH' || i.impact === 'EXTREME') || Object.values(p.pair_risk ?? {}).some((r: any) => r.blackout);
      return { ...s, stage: { ...s.stage, news: true }, breakingAt: hot ? now : s.breakingAt, fx: hot ? [...s.fx, mkFx('BREAKING!', 'zap')].slice(-6) : s.fx };
    }
    case 'setup.evaluated':
      return {
        ...s, stage: { ...s.stage, hunter: true },
        recentEvals: [...s.recentEvals.filter((x) => x.pair !== p.pair), { pair: p.pair, score: p.score, approved: p.approved, ts: now }].slice(-14),
        fx: p.approved ? s.fx : p.score > 0 ? [...s.fx, mkFx('REJECTED', 'bzzt')].slice(-6) : s.fx,
      };
    case 'setup.approved':
      return {
        ...s, packets: [...s.packets, { id: e.id, from: 'hunter' as const, to: 'command' as const, at: now, label: p.pair }].slice(-6),
        fx: [...s.fx, mkFx('APPROVED!', 'pow')].slice(-6),
      };
    case 'signal.created':
      return { ...s, stage: { ...s.stage, command: true }, commandFlashAt: now, fx: [...s.fx, mkFx('KA-CHING!', 'kaching')].slice(-6) };
    case 'telegram.preview':
      return {
        ...s, stage: { ...s.stage, telegram: true }, preview: { signal_id: p.signal_id, text: p.text },
        packets: [...s.packets, { id: `${e.id}-tg`, from: 'command' as const, to: 'telegram' as const, at: now, label: 'DEMO PREVIEW' }].slice(-6),
      };
    case 'telegram.sent':
      return {
        ...s, stage: { ...s.stage, telegram: true }, lastSent: { signal_id: p.signal_id, ok: true, at: now },
        packets: [...s.packets, { id: `${e.id}-tg`, from: 'command' as const, to: 'telegram' as const, at: now, label: 'SENT' }].slice(-6),
        fx: [...s.fx, mkFx('SENT!', 'ping')].slice(-6),
      };
    case 'telegram.failed':
      return { ...s, lastSent: { signal_id: p.signal_id, ok: false, at: now }, fx: [...s.fx, mkFx('FAILED', 'bzzt')].slice(-6) };
    default:
      return s;
  }
}

type Action = { type: 'event'; e: BusEvent } | { type: 'dismissPreview' } | { type: 'prune' };
function reducer(s: LiveState, a: Action): LiveState {
  if (a.type === 'event') return reduce(s, a.e);
  if (a.type === 'dismissPreview') return { ...s, preview: null };
  const now = Date.now();
  return { ...s, fx: s.fx.filter((f) => now - f.at < 2200), packets: s.packets.filter((p) => now - p.at < 6000) };
}

/** Snapshot polling + SSE. The server is the source of truth; events add the animation layer. */
export function useWorld() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, dispatch] = useReducer(reducer, undefined, emptyLive);
  const seen = useRef(new Set<string>());

  const refresh = useCallback(async () => {
    try {
      const r = await fetch('/api/state', { cache: 'no-store' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSnap(await r.json());
      setError(null);
    } catch (e) { setError((e as Error).message); }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 6000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    const es = new EventSource('/api/events');
    es.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data) as BusEvent;
        if (seen.current.has(e.id)) return;
        seen.current.add(e.id);
        if (Date.now() - Date.parse(e.ts) > 15_000) return; // don't replay stale history as animations
        dispatch({ type: 'event', e });
        if (['signal.created', 'pipeline.end', 'news.intel', 'telegram.sent'].includes(e.type)) refresh();
      } catch { /* ignore malformed */ }
    };
    const t = setInterval(() => dispatch({ type: 'prune' }), 1000);
    return () => { es.close(); clearInterval(t); };
  }, [refresh]);

  return { snap, live, error, refresh, dismissPreview: () => dispatch({ type: 'dismissPreview' }) };
}
