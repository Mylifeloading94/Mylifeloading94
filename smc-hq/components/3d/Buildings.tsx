'use client';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { Html, Outlines } from '@react-three/drei';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { AgentId } from '@/types';
import type { LiveState, Snapshot } from '../world-types';
import { Operator, LOOKS } from './Characters';
import { makeWindowTexture } from './City';
import { AnalystHolo, ConfidenceMeter, NewsHolo, pickPair } from './Holos';
import { BUILDINGS, Block, INK, PODIUM_H, strokedText, useCanvasTexture } from './common';

const STATUS_COLOR: Record<string, string> = { idle: '#2bff88', working: '#ffd426', error: '#ff2b2b', paused: '#ff8a1f', offline: '#666' };

function Sign({ id }: { id: AgentId }) {
  const b = BUILDINGS[id];
  const tex = useCanvasTexture(1024, 256, (g, W, H) => {
    g.fillStyle = b.color; g.fillRect(0, 0, W, H);
    // halftone dots
    g.fillStyle = 'rgba(0,0,0,0.18)';
    for (let y = 6; y < H; y += 14) for (let x = (y / 14) % 2 ? 6 : 13; x < W; x += 14) { g.beginPath(); g.arc(x, y, 3.2, 0, 7); g.fill(); }
    g.strokeStyle = INK; g.lineWidth = 16; g.strokeRect(8, 8, W - 16, H - 16);
    g.strokeStyle = '#fff'; g.lineWidth = 4; g.strokeRect(26, 26, W - 52, H - 52);
    strokedText(g, b.title, W / 2, H / 2 - 12, 150, '#ffffff', INK, 16, W - 90);
    strokedText(g, b.tag, W / 2, H - 52, 38, '#ffd426', INK, 8);
  }, [id]);
  const w = Math.min(13, b.w + 4);
  const y = PODIUM_H + b.towerH + 2.4;
  return (
    <group position={[0, y, 0.2]}>
      <mesh position={[0, 0, 0.1]}><planeGeometry args={[w, w / 4]} /><meshBasicMaterial map={tex} toneMapped={false} /></mesh>
      <mesh position={[0, 0, -0.1]}><boxGeometry args={[w + 0.5, w / 4 + 0.5, 0.3]} /><meshBasicMaterial color={INK} /></mesh>
      {[-1, 1].map((s) => <mesh key={s} position={[s * (w / 2 - 1), -w / 8 - 0.9, -0.1]}><cylinderGeometry args={[0.12, 0.12, 1.8, 6]} /><meshBasicMaterial color={INK} /></mesh>)}
      <pointLight position={[0, 0, 3]} color={b.accent} intensity={2.5} distance={22} />
    </group>
  );
}

function Bubble({ text, color }: { text: string; color: string }) {
  return (
    <Html position={[0, 3.9, 0.6]} center distanceFactor={20} style={{ pointerEvents: 'none' }} zIndexRange={[20, 10]}>
      <div className="speech" style={{ ['--c' as any]: color }}>{text.length > 70 ? `${text.slice(0, 68)}…` : text}</div>
    </Html>
  );
}

const Row = ({ k, v, tone }: { k: string; v: string; tone?: 'good' | 'bad' | 'warn' }) => (
  <div className="prow"><span>{k}</span><b className={tone}>{v}</b></div>
);

function useNow(ms = 1000) { const [n, setN] = useState(Date.now()); useEffect(() => { const t = setInterval(() => setN(Date.now()), ms); return () => clearInterval(t); }, [ms]); return n; }
const fmtCountdown = (s: number) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60); return `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`; };

function Panel({ id, snap, live }: { id: AgentId; snap: Snapshot | null; live: LiveState }) {
  const b = BUILDINGS[id];
  const now = useNow();
  const agent = snap?.agents[id];
  const demo = snap?.mode === 'DEMO';
  let rows: JSX.Element[] = [];
  if (id === 'market_analyst') {
    const pair = pickPair(snap, live);
    const a = pair ? snap?.analyses[pair] : undefined;
    rows = [
      <Row key="p" k="CURRENT PAIR" v={pair ?? '—'} />,
      <Row key="t" k="TIMEFRAME" v={a ? 'D1 H4 H1 M15 M5' : '—'} />,
      <Row key="b" k="BIAS" v={a ? a.htf_bias.toUpperCase() : '—'} tone={a?.htf_bias === 'bullish' ? 'good' : a?.htf_bias === 'bearish' ? 'bad' : undefined} />,
      <Row key="s" k="STRUCTURE" v={a ? `H4 ${a.structure.H4.slice(0, 4).toUpperCase()} · M15 ${a.m15_event === 'NONE' ? '—' : a.m15_event.replace('_', ' ')}` : '—'} />,
      <Row key="l" k="LIQUIDITY" v={a ? a.liquidity_event.replace(/_/g, ' ').toUpperCase() : '—'} />,
      <Row key="f" k="FVG" v={a ? (a.fvg ? 'PRESENT' : 'NONE') : '—'} tone={a?.fvg ? 'good' : undefined} />,
    ];
  } else if (id === 'news_intelligence') {
    const n = snap?.news;
    const top = n?.items.find((i) => i.impact === 'HIGH' || i.impact === 'EXTREME') ?? n?.items[0];
    const cd = n?.countdown_seconds != null && snap?.news_at ? Math.max(0, n.countdown_seconds - (now - snap.news_at) / 1000) : null;
    rows = [
      <Row key="n" k="LATEST NEWS" v={top ? (top.headline.length > 38 ? `${top.headline.slice(0, 36)}…` : top.headline) : n && !n.available ? 'FEED UNAVAILABLE' : '—'} />,
      <Row key="i" k="NEWS IMPACT" v={top?.impact ?? '—'} tone={top?.impact === 'HIGH' || top?.impact === 'EXTREME' ? 'bad' : undefined} />,
      <Row key="c" k="CURRENCY" v={top?.currencies.join('/') || '—'} />,
      <Row key="e" k="NEXT EVENT" v={n?.next_event ? `${n.next_event.currency} ${n.next_event.title.replace(' (simulated)', '')}` : '—'} />,
      <Row key="d" k="COUNTDOWN" v={cd != null ? fmtCountdown(cd) : '—'} />,
      <Row key="s" k="SENTIMENT" v={n ? n.sentiment.label.replace('_', '-').toUpperCase() : '—'} />,
    ];
  } else if (id === 'setup_hunter') {
    const h = snap?.hunter;
    const cur = live.scanning;
    rows = [
      <Row key="p" k="PAIR SCANNING" v={cur ? cur.pair : h ? 'IDLE' : '—'} />,
      <Row key="f" k="SETUPS FOUND" v={h ? String(h.approved.length) : '—'} tone={h?.approved.length ? 'good' : undefined} />,
      <Row key="r" k="REJECTED" v={h ? String(h.rejected_count) : '—'} tone={h?.rejected_count ? 'bad' : undefined} />,
      <Row key="c" k="CURRENT SCORE" v={live.recentEvals.length ? `${live.recentEvals[live.recentEvals.length - 1].score}/100` : '—'} />,
      <Row key="b" k="BEST SETUP" v={h?.best ? `${h.best.pair} ${h.best.score}/100` : '—'} />,
    ];
  } else {
    const today = snap?.signals.filter((s) => s.data_mode === snap.mode && s.timestamp.slice(0, 10) === (demo ? snap.signals[0]?.timestamp.slice(0, 10) : new Date().toISOString().slice(0, 10))).length;
    const last = snap?.lastSignal;
    const tg = snap?.system.telegram;
    rows = [
      <Row key="t" k="SIGNALS TODAY" v={snap ? String(today ?? 0) : '—'} />,
      <Row key="l" k="LAST SIGNAL" v={last ? `${last.signal_id} ${last.pair}` : 'NONE YET'} />,
      <Row key="g" k="TELEGRAM" v={demo ? 'DEMO — PREVIEW ONLY' : (tg?.state ?? '—').replace('_', ' ')} tone={tg?.state === 'CONNECTED' && !demo ? 'good' : tg?.state === 'ERROR' ? 'bad' : 'warn'} />,
      <Row key="s" k="SYSTEM" v={snap ? (snap.paused ? 'PAUSED' : agent?.status === 'error' ? 'ERROR' : 'RUNNING') : '—'} tone={snap?.paused ? 'warn' : undefined} />,
    ];
  }
  return (
    <Html position={[0, PODIUM_H + 8.2, BUILDINGS[id].d / 2 + 3]} center distanceFactor={26} style={{ pointerEvents: 'none' }} zIndexRange={[15, 5]}>
      <div className="fpanel" style={{ ['--c' as any]: b.color, ['--a' as any]: b.accent }}>
        <div className="fpanel-h"><span>{b.title}</span><i className={agent?.status ?? 'idle'} /></div>
        {demo && <div className="demo-tag">DEMO DATA</div>}
        {rows}
      </div>
    </Html>
  );
}

export function AgentBuilding({ id, snap, live, onSelect, selected }: { id: AgentId; snap: Snapshot | null; live: LiveState; onSelect: (id: AgentId) => void; selected: boolean }) {
  const b = BUILDINGS[id];
  const [hover, setHover] = useState(false);
  const agent = snap?.agents[id];
  const status = agent?.status ?? 'idle';
  const busy = status === 'working' || (id === 'setup_hunter' && !!live.scanning) || (id === 'signal_command' && Date.now() - live.commandFlashAt < 4000);
  const lamp = useRef<THREE.MeshBasicMaterial>(null);
  useFrame(({ clock }) => { if (lamp.current) lamp.current.opacity = busy ? 0.55 + Math.sin(clock.elapsedTime * 10) * 0.45 : 1; });
  useEffect(() => { document.body.style.cursor = hover ? 'pointer' : ''; return () => { document.body.style.cursor = ''; }; }, [hover]);
  const tex = useMemo(() => makeWindowTexture(b.dark, id.length * 13, Math.ceil(b.w / 3), Math.ceil(b.towerH / 4)), [b, id]);
  const look = LOOKS[id === 'market_analyst' ? 'analyst' : id === 'news_intelligence' ? 'news' : id === 'setup_hunter' ? 'hunter' : 'command'];
  const speech = agent?.summary ?? 'Standing by';
  return (
    <group position={b.pos}
      onClick={(e) => { e.stopPropagation(); onSelect(id); }}
      onPointerOver={(e) => { e.stopPropagation(); setHover(true); }}
      onPointerOut={() => setHover(false)}>
      {/* plaza */}
      <Block size={[b.w + 5, 0.25, b.d + 6]} pos={[0, 0.12, 1]} color="#2c2a5a" />
      {/* podium = hollow glass-fronted control room so the operator and holograms are visible */}
      <Block size={[b.w, 0.3, b.d]} pos={[0, 0.4, 0]} color="#1b1b33" />
      <Block size={[b.w, PODIUM_H - 0.3, 0.5]} pos={[0, PODIUM_H / 2 + 0.4, -b.d / 2 + 0.25]} color={b.dark} emissive={b.color} emissiveIntensity={hover || selected ? 0.45 : 0.18} />
      {[-1, 1].map((sx) => <Block key={sx} size={[0.5, PODIUM_H - 0.3, b.d]} pos={[sx * (b.w / 2 - 0.25), PODIUM_H / 2 + 0.4, 0]} color={b.dark} emissive={hover || selected ? b.color : undefined} emissiveIntensity={0.3} />)}
      <Block size={[b.w, 0.5, b.d]} pos={[0, PODIUM_H + 0.25, 0]} color={b.dark} />
      <mesh position={[0, 2.9, b.d / 2 - 0.1]}><boxGeometry args={[b.w - 1, PODIUM_H - 1, 0.1]} /><meshPhysicalMaterial color="#9ff3ff" transparent opacity={0.16} roughness={0.1} depthWrite={false} /></mesh>
      <Block size={[b.w, 0.35, 0.35]} pos={[0, PODIUM_H - 0.05, b.d / 2 - 0.1]} color={INK} outline={false} />
      <Block size={[b.w, 0.35, 0.35]} pos={[0, 0.55, b.d / 2 - 0.1]} color={INK} outline={false} />
      <pointLight position={[0, 3.8, 1.2]} color={b.accent} intensity={4} distance={14} />
      {/* tower */}
      <Block size={[b.w - 1.2, b.towerH, b.d - 1.2]} pos={[0, PODIUM_H + b.towerH / 2 + 0.25, 0]} color={b.color} emissive="#ffffff" emissiveIntensity={0.5} map={tex} />
      <Block size={[b.w - 0.6, 0.6, b.d - 0.6]} pos={[0, PODIUM_H + b.towerH + 0.55, 0]} color={b.accent} emissive={b.accent} emissiveIntensity={0.6} />
      <Sign id={id} />
      {/* status lamp */}
      <mesh position={[b.w / 2 - 0.4, PODIUM_H + 0.8, b.d / 2 + 0.3]}>
        <sphereGeometry args={[0.38, 12, 10]} /><meshBasicMaterial ref={lamp} color={STATUS_COLOR[status]} transparent /><Outlines thickness={0.05} color={INK} />
      </mesh>
      {/* operator */}
      <group position={[0, 0.3, 0.6]}><Operator look={look} busy={busy} phase={id.length} /><Bubble text={speech} color={b.color} /></group>
      {/* per-agent holograms */}
      {id === 'market_analyst' && <AnalystHolo snap={snap} live={live} busy={busy} w={b.w} d={b.d} />}
      {id === 'news_intelligence' && <NewsHolo snap={snap} live={live} w={b.w} d={b.d} />}
      {id === 'setup_hunter' && <ConfidenceMeter snap={snap} live={live} />}
      <Panel id={id} snap={snap} live={live} />
      {selected && <mesh position={[0, 0.3, 1]} rotation={[-Math.PI / 2, 0, 0]}><ringGeometry args={[b.w * 0.85, b.w * 0.85 + 0.35, 48]} /><meshBasicMaterial color={b.accent} /></mesh>}
    </group>
  );
}

