'use client';
import { useState } from 'react';
import type { LiveState, Snapshot } from '../world-types';

const STEPS: [keyof LiveState['stage'], string][] = [['analyst', '1 ANALYST'], ['news', '2 NEWS'], ['hunter', '3 HUNTER'], ['command', '4 COMMAND'], ['telegram', '5 TG PREVIEW']];

export function DemoControls({ snap, live, onDone }: { snap: Snapshot | null; live: LiveState; onDone: (r: any) => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const run = async (blackout: boolean) => {
    if (busy) return;
    setBusy(true); setResult(null);
    try {
      const r = await fetch('/api/demo/run-signal', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ blackout }) });
      const j = await r.json();
      if (!r.ok) setResult(j.skipped ?? 'Demo run failed');
      else {
        setResult(j.outcome === 'created' ? `✔ ${j.signal.signal_id} approved · ${Math.round(j.signal.confidence_score)}/100 (DEMO)` : `✖ ${j.outcome.toUpperCase()}: ${j.reason ?? ''}`);
        onDone(j);
      }
    } catch (e) { setResult(`Failed: ${(e as Error).message}`); }
    setBusy(false);
  };
  const stageIdx = STEPS.findIndex(([k]) => !live.stage[k]);
  return (
    <div className="demo-cta">
      {(busy || live.running) && <div className="steps" aria-label="Pipeline progress">{STEPS.map(([k, label], i) => <span key={k} className={`step ${live.stage[k] ? 'done' : i === stageIdx ? 'now' : ''}`}>{label}</span>)}</div>}
      {result && <div className="chip" style={{ background: result.startsWith('✔') ? '#2bff88' : '#ffd426', color: '#0b0b14', fontSize: 13, padding: '3px 10px', lineHeight: 1.3, whiteSpace: 'normal', maxWidth: 420 }}>{result}</div>}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="btn big" onClick={() => run(false)} disabled={busy}>{busy ? 'RUNNING…' : '▶ RUN DEMO SIGNAL'}</button>
        <button className="btn sm blue" onClick={() => run(true)} disabled={busy} title="Same setup, but a simulated HIGH-impact release is minutes away">…WITH NEWS BLACKOUT</button>
      </div>
      <span className="font-pixel" style={{ fontSize: 8, color: '#ffd426', textShadow: '2px 2px 0 #0b0b14' }}>DEMO DATA · NEVER SENT TO TELEGRAM{snap?.mode === 'LIVE' ? ' · RECORDED AS DEMO' : ''}</span>
    </div>
  );
}
