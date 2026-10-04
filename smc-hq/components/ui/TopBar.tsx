'use client';
import type { Snapshot } from '../world-types';

export type View = 'world' | 'market' | 'news' | 'setups' | 'signals' | 'performance' | 'settings';
const VIEWS: View[] = ['world', 'market', 'news', 'setups', 'signals', 'performance', 'settings'];

const Dot = ({ cls }: { cls: 'ok' | 'demo' | 'bad' | 'off' }) => <i className={`dot ${cls}`} />;

export function TopBar({ snap, view, onView, flat, onFlat, error }: { snap: Snapshot | null; view: View; onView: (v: View) => void; flat: boolean; onFlat: () => void; error: string | null }) {
  const s = snap?.system;
  const mk = s?.market.state, nw = s?.news.state, tg = s?.telegram.state;
  return (
    <header className="hud-top">
      <div>
        <div className="logo">SMC TRADING HQ<small>3D AGENT WORLD</small></div>
        <nav className="nav" style={{ marginTop: 10 }} aria-label="Primary">
          {VIEWS.map((v) => <button key={v} className={view === v ? 'on' : ''} onClick={() => onView(v)}>{v.toUpperCase()}</button>)}
          <button onClick={onFlat} title="Toggle 2D / 3D">{flat ? '3D MODE' : '2D MODE'}</button>
        </nav>
      </div>
      <div className="statusbar" role="status" aria-live="polite">
        {error && !snap ? <span><Dot cls="bad" />SERVER UNREACHABLE</span> : <>
          <span><Dot cls={mk === 'ONLINE' ? 'ok' : mk === 'DEMO' || mk === 'STANDBY' ? 'demo' : mk ? 'bad' : 'off'} />MARKET DATA: {mk === 'UNAVAILABLE' ? 'UNAVAILABLE' : mk ?? '…'}</span>
          <span><Dot cls={nw === 'ONLINE' ? 'ok' : nw === 'DEMO' || nw === 'STANDBY' ? 'demo' : nw ? 'bad' : 'off'} />NEWS: {nw ?? '…'}</span>
          <span><Dot cls={s && s.agents.online === s.agents.total ? 'ok' : 'bad'} />AGENTS: {s ? `${s.agents.online}/${s.agents.total}` : '…'} ONLINE</span>
          <span><Dot cls={tg === 'CONNECTED' ? 'ok' : tg === 'ERROR' ? 'bad' : 'off'} />TELEGRAM: {tg ? tg.replace('_', ' ') : '…'}</span>
          {snap?.mode === 'DEMO' && <span style={{ color: '#ffd426' }}>◆ DEMO MODE — SIMULATED DATA</span>}
          {snap?.paused && <span style={{ color: '#ff8a1f' }}>⏸ PAUSED</span>}
        </>}
      </div>
    </header>
  );
}
