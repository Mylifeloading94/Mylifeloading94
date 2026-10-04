'use client';
import dynamic from 'next/dynamic';
import { Component, useCallback, useEffect, useState } from 'react';
import { AGENT_IDS, AGENT_LABELS, type AgentId } from '@/types';
import { ControlRoom } from './agents/ControlRoom';
import { MarketView } from './dashboard/MarketView';
import { NewsView } from './dashboard/NewsView';
import { PerformanceView } from './dashboard/PerformanceView';
import { SettingsView } from './dashboard/SettingsView';
import { SetupsView } from './dashboard/SetupsView';
import { SignalsView } from './dashboard/SignalsView';
import { TelegramPreview } from './telegram/TelegramPreview';
import { Chip } from './ui/Comic';
import { DemoControls } from './ui/DemoControls';
import { FxLayer } from './ui/FxLayer';
import { TopBar, type View } from './ui/TopBar';
import { BUILDINGS } from './3d/common';
import { useWorld } from './useWorld';

const World = dynamic(() => import('./3d/World'), { ssr: false });

function webglOk() {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch { return false; }
}

class Boundary extends Component<{ onError: () => void; children: React.ReactNode }, { bad: boolean }> {
  state = { bad: false };
  static getDerivedStateFromError() { return { bad: true }; }
  componentDidCatch(e: Error) { console.error('3D world crashed — falling back to 2D', e); this.props.onError(); }
  render() { return this.state.bad ? null : this.props.children; }
}

export default function App() {
  const { snap, live, error, refresh, dismissPreview } = useWorld();
  const [view, setView] = useState<View>('world');
  const [selected, setSelected] = useState<AgentId | null>(null);
  const [flat, setFlat] = useState(false);
  const [booted, setBooted] = useState(false);
  const [idle, setIdle] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => {
    setFlat(!webglOk() || window.innerWidth < 640 || new URLSearchParams(location.search).has('flat'));
    setBooted(true);
    const t = setTimeout(() => setIdle(true), 6500); // cinematic camera starts drifting after the title card
    return () => clearTimeout(t);
  }, []);
  useEffect(() => { if (live.preview) setPreviewOpen(true); }, [live.preview]);

  const pickView = (v: View) => { setView(v); setSelected(null); };
  const selectAgent = useCallback((id: AgentId | null) => { setSelected(id); if (id) setView('world'); }, []);
  const scan = async () => {
    setScanning(true);
    try { await fetch('/api/pipeline/scan', { method: 'POST' }); } finally { setScanning(false); refresh(); }
  };
  const closeAll = () => { setView('world'); setSelected(null); };
  const panelOpen = view !== 'world' || !!selected;

  return (
    <>
      {booted && !flat && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1 }}>
          <Boundary onError={() => setFlat(true)}>
            <World snap={snap} live={live} selected={selected} onSelect={selectAgent} idle={idle && !panelOpen} />
          </Boundary>
        </div>)}
      {flat && (
        <div className="flat-grid" role="main">
          {AGENT_IDS.map((id) => {
            const b = BUILDINGS[id]; const a = snap?.agents[id];
            return (
              <article key={id} className="cpanel" style={{ ['--c' as any]: b.color, alignSelf: 'start' }}>
                <div className="cpanel-h"><span>{AGENT_LABELS[id]}</span><Chip tone={a?.status === 'error' ? 'bad' : a?.status === 'working' ? 'warn' : 'good'}>{(a?.status ?? '…').toUpperCase()}</Chip></div>
                <div style={{ padding: 12, color: '#0b0b14', display: 'grid', gap: 8 }}>
                  <div style={{ fontSize: 14 }}>{a?.summary ?? 'Loading…'}</div>
                  <div style={{ fontSize: 12, opacity: 0.7 }}>{b.tag}</div>
                  <button className="btn sm" onClick={() => selectAgent(id)}>OPEN CONTROL ROOM</button>
                </div>
              </article>);
          })}
        </div>)}

      <div className="halftone" /><div className="vignette" /><div className="frame" />
      <div className={`speedlines ${live.running ? 'on' : ''}`} />
      <TopBar snap={snap} view={view} onView={pickView} flat={flat} onFlat={() => setFlat(!flat)} error={error} />

      {booted && !flat && <div className="intro" aria-hidden><h1>SMC TRADING HQ</h1><p>FOUR AI AGENTS. ONE MARKET INTELLIGENCE SYSTEM.</p><span className="tap">CLICK A BUILDING TO ENTER ITS CONTROL ROOM</span></div>}

      {selected && <ControlRoom id={selected} snap={snap} live={live} onClose={closeAll} onScan={scan} scanning={scanning} onOpenTelegram={() => setPreviewOpen(true)} />}
      {view === 'market' && <MarketView snap={snap} onClose={closeAll} onScan={scan} scanning={scanning} />}
      {view === 'news' && <NewsView snap={snap} onClose={closeAll} onScan={scan} scanning={scanning} />}
      {view === 'setups' && <SetupsView snap={snap} onClose={closeAll} onScan={scan} scanning={scanning} />}
      {view === 'signals' && <SignalsView snap={snap} onClose={closeAll} refresh={refresh} />}
      {view === 'performance' && <PerformanceView snap={snap} onClose={closeAll} />}
      {view === 'settings' && <SettingsView snap={snap} onClose={closeAll} refresh={refresh} />}

      <DemoControls snap={snap} live={live} onDone={() => refresh()} />
      <FxLayer fx={live.fx} />
      {previewOpen && live.preview && <TelegramPreview text={live.preview.text} signalId={live.preview.signal_id} demo onClose={() => { setPreviewOpen(false); dismissPreview(); }} />}
      <footer className="font-pixel" style={{ position: 'fixed', right: 22, bottom: 20, zIndex: 20, fontSize: 8, color: '#fff', textShadow: '2px 2px 0 #0b0b14', textAlign: 'right', maxWidth: 340, lineHeight: 1.6 }}>
        EDUCATIONAL ANALYSIS — NOT FINANCIAL ADVICE. CONFIDENCE SCORE ≠ WIN PROBABILITY. NO AUTO-EXECUTION.
      </footer>
    </>
  );
}
