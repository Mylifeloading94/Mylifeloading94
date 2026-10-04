'use client';
import { useEffect, useState } from 'react';
import { formatSignalMessage } from '@/lib/telegram/format';
import { SIGNAL_STATUSES, type DataMode, type Signal } from '@/types';
import { Chip, Empty, fmtTime, Loading, trendTone, ViewShell } from '../ui/Comic';
import { TelegramPreview } from '../telegram/TelegramPreview';
import type { Snapshot } from '../world-types';

const sTone = (s: string) => (s.startsWith('TP') ? 'good' : s === 'STOPPED' ? 'bad' : s === 'PENDING' || s === 'ACTIVE' ? 'info' : 'warn') as 'good' | 'bad' | 'info' | 'warn';

export function SignalsView({ snap, onClose, refresh }: { snap: Snapshot | null; onClose: () => void; refresh: () => void }) {
  const [mode, setMode] = useState<DataMode>(snap?.mode ?? 'DEMO');
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [preview, setPreview] = useState<Signal | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = async () => {
    const r = await fetch(`/api/signals?mode=${mode}&limit=100`, { cache: 'no-store' });
    setSignals((await r.json()).signals);
  };
  useEffect(() => { setSignals(null); load(); }, [mode, snap?.lastSignal?.signal_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const setStatus = async (id: string, status: string) => {
    const r = await fetch(`/api/signals/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ status }) });
    setMsg(r.ok ? `${id} → ${status}` : 'Update failed');
    await load(); refresh();
  };
  const track = async () => {
    const r = await fetch('/api/signals/track', { method: 'POST' });
    const j = await r.json();
    setMsg(j.errors?.length ? j.errors[0] : `Checked ${j.checked}, updated ${j.updated.length}`);
    await load(); refresh();
  };

  return (
    <ViewShell title="SIGNAL COMMAND" color="#2bff88" onClose={onClose} right={
      <span style={{ display: 'flex', gap: 6 }}>
        {(['LIVE', 'DEMO'] as const).map((m) => <button key={m} className={`btn sm ${mode === m ? '' : 'blue'}`} onClick={() => setMode(m)}>{m}</button>)}
      </span>}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
        <Chip tone={mode === 'DEMO' ? 'demo' : 'good'}>{mode === 'DEMO' ? 'DEMO SIGNALS — never sent to Telegram' : 'LIVE SIGNALS'}</Chip>
        {mode === 'LIVE' && <button className="btn sm" onClick={track}>TRACK OPEN SIGNALS</button>}
        {msg && <span style={{ fontSize: 12 }}>{msg}</span>}
      </div>
      {!signals ? <Loading what="LOADING SIGNALS" /> : !signals.length ? (
        <Empty title={mode === 'DEMO' ? 'NO DEMO SIGNALS YET' : 'NO LIVE SIGNALS YET'} hint={mode === 'DEMO' ? 'Hit RUN DEMO SIGNAL (bottom-left) to push a simulated setup through all four agents.' : 'Live signals appear here only after Signal Command approves a setup from real market data.'} />
      ) : (
        <table className="tbl">
          <thead><tr><th>ID</th><th>PAIR</th><th>ENTRY</th><th>SL</th><th>TP1/2/3</th><th>R:R</th><th>SCORE</th><th>STATUS</th><th>TG</th><th></th></tr></thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.signal_id}>
                <td style={{ whiteSpace: 'nowrap' }}><b>{s.signal_id}</b><div style={{ fontSize: 11, opacity: 0.7 }}>{fmtTime(s.timestamp)}</div></td>
                <td><Chip tone={trendTone(s.direction)}>{s.pair} {s.direction.toUpperCase()}</Chip><div style={{ fontSize: 11 }}>{s.setup_type}</div></td>
                <td>{s.entry_low}–{s.entry_high}</td><td>{s.stop_loss}</td><td style={{ fontSize: 12 }}>{s.take_profit_1}<br />{s.take_profit_2}<br />{s.take_profit_3}</td>
                <td>1:{s.risk_reward.toFixed(1)}</td><td>{Math.round(s.confidence_score)}</td>
                <td><Chip tone={sTone(s.status)}>{s.status}</Chip>{s.result && <div style={{ fontSize: 11 }}>{s.result}</div>}</td>
                <td style={{ fontSize: 11 }}>{s.telegram_state.replace('_', ' ')}</td>
                <td style={{ display: 'grid', gap: 4, minWidth: 96 }}>
                  <button className="btn sm blue" onClick={() => setPreview(s)}>MSG</button>
                  <select className="input" style={{ width: 96, padding: 1, fontSize: 11 }} value="" aria-label={`Record outcome for ${s.signal_id}`} onChange={(e) => e.target.value && setStatus(s.signal_id, e.target.value)}>
                    <option value="">outcome…</option>{SIGNAL_STATUSES.map((x) => <option key={x} value={x}>{x}</option>)}
                  </select>
                </td>
              </tr>))}
          </tbody>
        </table>)}
      {preview && <TelegramPreview text={formatSignalMessage(preview)} signalId={preview.signal_id} demo={preview.data_mode === 'DEMO'} onClose={() => setPreview(null)} />}
    </ViewShell>
  );
}
