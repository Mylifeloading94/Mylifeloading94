'use client';
import { useEffect, useState } from 'react';
import type { CalendarEvent, Settings } from '@/types';
import { Chip, ViewShell } from '../ui/Comic';
import type { Snapshot } from '../world-types';

export function SettingsView({ snap, onClose, refresh }: { snap: Snapshot | null; onClose: () => void; refresh: () => void }) {
  const [s, setS] = useState<Settings | null>(snap?.settings ?? null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pairInput, setPairInput] = useState('');
  const [ev, setEv] = useState({ title: '', currency: 'USD', impact: 'HIGH', time: '' });
  const [health, setHealth] = useState<any>(null);
  useEffect(() => { if (snap && !s) setS(snap.settings); }, [snap, s]);
  useEffect(() => { fetch('/api/health').then((r) => r.json()).then(setHealth).catch(() => undefined); }, []);
  if (!s) return <ViewShell title="SETTINGS" color="#7a4dff" onClose={onClose}><div className="empty">LOADING…</div></ViewShell>;

  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setS({ ...s, [k]: v });
  const save = async () => {
    const r = await fetch('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(s) });
    const j = await r.json();
    setMsg(r.ok ? { ok: true, text: 'Saved.' } : { ok: false, text: j.error ?? 'Failed' });
    if (r.ok) { setS(j); refresh(); }
  };
  const addPair = () => {
    const p = pairInput.trim().toUpperCase();
    if (!/^[A-Z]{6}$/.test(p)) return setMsg({ ok: false, text: 'Pairs are 6 letters, e.g. EURGBP or XAUUSD' });
    if (!s.watchlist.includes(p)) set('watchlist', [...s.watchlist, p]);
    setPairInput('');
  };
  const addEvent = () => {
    if (!ev.title || !ev.time) return setMsg({ ok: false, text: 'Event needs a title and a time' });
    const e: CalendarEvent = { id: `manual-${Date.now()}`, title: ev.title, currency: ev.currency, impact: ev.impact as CalendarEvent['impact'], time: new Date(ev.time).toISOString(), affected_assets: [], manual: true };
    set('manual_events', [...s.manual_events, e]); setEv({ ...ev, title: '' });
  };
  const testTg = async () => {
    const r = await fetch('/api/telegram/test', { method: 'POST' });
    const j = await r.json();
    setMsg({ ok: r.ok, text: r.ok ? 'Test message sent to Telegram.' : j.error ?? 'Telegram test failed' });
  };
  const Field = ({ label, children }: { label: string; children: React.ReactNode }) => <label style={{ display: 'grid', gap: 3, fontSize: 12, fontWeight: 800 }}>{label}{children}</label>;

  return (
    <ViewShell title="SETTINGS" color="#7a4dff" onClose={onClose} right={<button className="btn sm green" onClick={save}>SAVE</button>}>
      <div style={{ display: 'grid', gap: 16 }}>
        {msg && <Chip tone={msg.ok ? 'good' : 'bad'}>{msg.text}</Chip>}
        <div className="stat" style={{ fontSize: 13 }}>
          <b className="font-comic" style={{ fontSize: 20 }}>⚠ NO AUTOMATIC EXECUTION</b>
          This system only produces analysis and Telegram signals. It never places trades. Educational analysis — not financial advice.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))', gap: 12 }}>
          <Field label="Risk per trade (%)"><select className="input" value={s.risk_per_trade} onChange={(e) => set('risk_per_trade', Number(e.target.value) as Settings['risk_per_trade'])}>{[0.25, 0.5, 1, 2].map((x) => <option key={x} value={x}>{x}%</option>)}</select></Field>
          <Field label="Max daily signals"><input className="input" type="number" min={1} max={20} value={s.max_daily_signals} onChange={(e) => set('max_daily_signals', Number(e.target.value))} /></Field>
          <Field label="Max simultaneous signals"><input className="input" type="number" min={1} max={20} value={s.max_simultaneous_signals} onChange={(e) => set('max_simultaneous_signals', Number(e.target.value))} /></Field>
          <Field label="Minimum R:R"><input className="input" type="number" step={0.1} min={1} max={10} value={s.min_rr} onChange={(e) => set('min_rr', Number(e.target.value))} /></Field>
          <Field label="Minimum confidence (70–100)"><input className="input" type="number" min={70} max={100} value={s.min_confidence} onChange={(e) => set('min_confidence', Number(e.target.value))} /></Field>
          <Field label="News blackout window"><select className="input" value={s.news_blackout_minutes} onChange={(e) => set('news_blackout_minutes', Number(e.target.value) as Settings['news_blackout_minutes'])}>{[15, 30, 60].map((x) => <option key={x} value={x}>{x} minutes</option>)}</select></Field>
        </div>
        <div>
          <b className="font-comic" style={{ fontSize: 20 }}>WATCHLIST</b>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '6px 0' }}>
            {s.watchlist.map((p) => <span key={p} className="chip info">{p} <button aria-label={`Remove ${p}`} onClick={() => s.watchlist.length > 1 && set('watchlist', s.watchlist.filter((x) => x !== p))} style={{ background: 'none', border: 0, color: '#fff', cursor: 'pointer', fontWeight: 900 }}>×</button></span>)}
          </div>
          <div style={{ display: 'flex', gap: 6 }}><input className="input" style={{ maxWidth: 160 }} placeholder="EURGBP" value={pairInput} onChange={(e) => setPairInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addPair()} /><button className="btn sm" onClick={addPair}>ADD</button>
            <button className="btn sm blue" onClick={() => set('watchlist', ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD', 'EURJPY', 'GBPJPY', 'CADJPY', 'AUDJPY', 'XAUUSD'])}>RESET DEFAULT</button></div>
        </div>
        <div>
          <b className="font-comic" style={{ fontSize: 20 }}>MANUAL NEWS EVENTS (blackout scheduling)</b>
          <p style={{ fontSize: 12, margin: '2px 0 6px' }}>Add scheduled releases (CPI, NFP, FOMC…) when your news provider has no economic calendar. Times use your local timezone and are stored as UTC.</p>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 80px 110px 1.4fr auto', gap: 6, alignItems: 'end' }}>
            <input className="input" placeholder="US CPI" value={ev.title} onChange={(e) => setEv({ ...ev, title: e.target.value })} aria-label="Event title" />
            <select className="input" value={ev.currency} onChange={(e) => setEv({ ...ev, currency: e.target.value })} aria-label="Currency">{['USD', 'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'NZD', 'CAD', 'XAU'].map((c) => <option key={c}>{c}</option>)}</select>
            <select className="input" value={ev.impact} onChange={(e) => setEv({ ...ev, impact: e.target.value })} aria-label="Impact">{['LOW', 'MEDIUM', 'HIGH', 'EXTREME'].map((c) => <option key={c}>{c}</option>)}</select>
            <input className="input" type="datetime-local" value={ev.time} onChange={(e) => setEv({ ...ev, time: e.target.value })} aria-label="Event time" />
            <button className="btn sm" onClick={addEvent}>ADD</button>
          </div>
          {s.manual_events.map((e) => <div key={e.id} style={{ fontSize: 12, marginTop: 4 }}><Chip tone={e.impact === 'HIGH' || e.impact === 'EXTREME' ? 'bad' : 'warn'}>{e.impact}</Chip> {e.currency} {e.title} — {e.time.slice(0, 16).replace('T', ' ')}Z <button className="btn sm red" onClick={() => set('manual_events', s.manual_events.filter((x) => x.id !== e.id))}>✕</button></div>)}
        </div>
        <div className="stat" style={{ fontSize: 13, display: 'grid', gap: 4 }}>
          <b className="font-comic" style={{ fontSize: 20 }}>INTEGRATIONS (secrets live in .env, server-side only)</b>
          <div>Mode: <Chip tone={snap?.mode === 'DEMO' ? 'demo' : 'good'}>{snap?.mode}</Chip> {snap?.mode === 'DEMO' && 'Set MARKET_DATA_API_KEY in .env for live data.'}</div>
          <div>Database: <Chip>{snap?.system.database}</Chip></div>
          <div>Telegram: <Chip tone={snap?.system.telegram.state === 'CONNECTED' ? 'good' : 'warn'}>{snap?.system.telegram.state.replace('_', ' ')}</Chip> {snap?.system.telegram.detail} <button className="btn sm blue" onClick={testTg}>SEND TEST MESSAGE</button></div>
          <div>News API: <Chip>{health ? (health.news_configured ? 'configured' : 'not configured') : '…'}</Chip> X API: <Chip>{health ? (health.x_configured ? 'configured' : 'not configured') : '…'}</Chip></div>
        </div>
      </div>
    </ViewShell>
  );
}
