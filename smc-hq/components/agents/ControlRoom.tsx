'use client';
import { useState } from 'react';
import { AGENT_LABELS, type AgentId } from '@/types';
import { BUILDINGS } from '../3d/common';
import { Chip, Empty, fmtTime, Json, ViewShell } from '../ui/Comic';
import type { LiveState, Snapshot } from '../world-types';

const STATUS_TONE = { idle: 'good', working: 'warn', error: 'bad', paused: 'warn', offline: 'bad' } as const;

export function ControlRoom({ id, snap, live, onClose, onScan, scanning, onOpenTelegram }: { id: AgentId; snap: Snapshot | null; live: LiveState; onClose: () => void; onScan: () => void; scanning: boolean; onOpenTelegram: () => void }) {
  const b = BUILDINGS[id];
  const a = snap?.agents[id];
  const [tg, setTg] = useState<string | null>(null);
  const testTelegram = async () => { const r = await fetch('/api/telegram/test', { method: 'POST' }); const j = await r.json(); setTg(r.ok ? 'Test message sent ✓' : j.error ?? 'failed'); };
  let output: unknown = null;
  let body: React.ReactNode = null;
  if (id === 'market_analyst') {
    const list = snap ? Object.values(snap.analyses) : [];
    output = list.find((x) => x.candidate) ?? list[0] ?? null;
    body = list.length ? <>
      <b>Latest conclusions</b>
      {list.slice(0, 8).map((x) => <div key={x.pair} style={{ fontSize: 13 }}><b>{x.pair}</b> — {x.summary}</div>)}
      <div style={{ fontSize: 12, opacity: 0.75 }}>Analyses: D1 · H4 · H1 · M15 · M5. BOS/CHoCH/MSS, sweeps, EQH/EQL, FVG, OB, breaker, premium/discount, fib, ATR, RSI, MAs, PDH/PDL, PWH/PWL, Asian/London/NY ranges.</div>
    </> : <Empty title="NO ANALYSIS YET" hint="Run a scan." />;
  } else if (id === 'news_intelligence') {
    output = snap?.news ? { ...snap.news, items: snap.news.items.slice(0, 5) } : null;
    const n = snap?.news;
    body = n ? <><b>{n.summary}</b>
      {n.items.slice(0, 5).map((i) => <div key={i.id} style={{ fontSize: 13 }}><Chip tone={i.impact === 'HIGH' || i.impact === 'EXTREME' ? 'bad' : 'info'}>{i.impact}</Chip> {i.headline}</div>)}</> : <Empty title="NO NEWS REPORT YET" hint="Run a scan." />;
  } else if (id === 'setup_hunter') {
    output = snap?.hunter ? { ...snap.hunter, evaluations: snap.hunter.evaluations.slice(0, 3) } : null;
    const h = snap?.hunter;
    body = h ? <><b>{a?.summary}</b>
      {[...h.evaluations].sort((x, y) => y.confidence_score - x.confidence_score).slice(0, 6).map((e) => <div key={e.pair} style={{ fontSize: 13 }}><Chip tone={e.approved ? 'good' : 'bad'}>{e.approved ? 'OK' : 'NO'}</Chip> <b>{e.pair}</b> {e.confidence_score}/100 — {e.approved ? 'approved' : e.rejection_reasons[0]}</div>)}</> : <Empty title="NO SCAN YET" hint="Run a scan." />;
  } else {
    const last = snap?.lastSignal;
    output = last ?? null;
    body = <>
      {last ? <div style={{ fontSize: 13 }}><b>{last.signal_id}</b> {last.pair} {last.direction.toUpperCase()} · {last.confidence_score}/100 · {last.status} · Telegram: {last.telegram_state.replace('_', ' ')}</div> : <Empty title="NO SIGNALS YET" hint="Signal Command only acts on setups approved by Setup Hunter." />}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {live.preview && <button className="btn sm blue" onClick={onOpenTelegram}>OPEN LAST TELEGRAM PREVIEW</button>}
        <button className="btn sm" onClick={testTelegram}>TELEGRAM TEST MESSAGE</button>
      </div>
      {tg && <Chip tone={tg.includes('✓') ? 'good' : 'bad'}>{tg}</Chip>}
    </>;
  }
  return (
    <ViewShell narrow title={`CONTROL ROOM · ${AGENT_LABELS[id]}`} color={b.color} onClose={onClose} right={id !== 'signal_command' ? <button className="btn sm" onClick={onScan} disabled={scanning}>{scanning ? 'SCANNING…' : 'SCAN NOW'}</button> : null}>
      <div style={{ display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <Chip tone={a ? STATUS_TONE[a.status] : 'warn'}>{a?.status.toUpperCase() ?? '…'}</Chip>
          <Chip>runs {a?.runs ?? 0}</Chip><Chip tone={a?.failures ? 'bad' : undefined}>failures {a?.failures ?? 0}</Chip>
          <Chip>last run {fmtTime(a?.last_run)}</Chip>{a?.last_duration_ms != null && <Chip>{a.last_duration_ms} ms</Chip>}
          {snap?.mode === 'DEMO' && <Chip tone="demo">DEMO DATA</Chip>}
        </div>
        <div className="stat"><span>Decision summary (factors only)</span><div style={{ fontSize: 14, marginTop: 4 }}>{a?.summary ?? '—'}</div>{a?.error && <div style={{ color: '#d11', fontSize: 13 }}>Error: {a.error}</div>}</div>
        <div style={{ display: 'grid', gap: 6 }}>{body}</div>
        <div><b>Activity log</b>
          <div style={{ maxHeight: 160, overflow: 'auto', background: '#fff', border: '2px solid #0b0b14', padding: 6 }}>
            {a?.logs.length ? [...a.logs].reverse().map((l, i) => <div key={i} className={`logline ${l.level}`}>{l.ts.slice(11, 19)} [{l.level}] {l.message}</div>) : <div className="logline">No log entries yet.</div>}
          </div></div>
        <details><summary style={{ cursor: 'pointer' }}>Structured output (JSON handed to the next agent)</summary>{output ? <Json data={output} /> : <div className="logline">none yet</div>}</details>
      </div>
    </ViewShell>
  );
}
