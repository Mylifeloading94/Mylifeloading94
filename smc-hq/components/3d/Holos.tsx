'use client';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { Billboard, Html, Outlines } from '@react-three/drei';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { Candle, MarketAnalysis } from '@/types';
import type { LiveState, Snapshot } from '../world-types';
import { BUILDINGS, Block, INK, PODIUM_H, roofOf, strokedText, TELEGRAM_POS, toonGradient, useCanvasTexture } from './common';

/* ------------------------------------------------------------------ */
/* Analyst: giant holographic chart (REAL candles from the provider)   */
/* ------------------------------------------------------------------ */
function useCandles(pair: string | null) {
  const [data, setData] = useState<{ candles: Candle[]; mode: string } | null>(null);
  useEffect(() => {
    if (!pair) return;
    let dead = false;
    const load = async () => {
      try {
        const r = await fetch(`/api/market/${pair}?tf=M15&count=64`, { cache: 'no-store' });
        if (!r.ok) throw new Error('unavailable');
        const j = await r.json();
        if (!dead) setData({ candles: j.candles, mode: j.data_mode });
      } catch { if (!dead) setData(null); }
    };
    load();
    const t = setInterval(load, 30_000);
    return () => { dead = true; clearInterval(t); };
  }, [pair]);
  return data;
}

export function pickPair(snap: Snapshot | null, live: LiveState): string | null {
  if (live.scanning?.pair) return live.scanning.pair;
  const a = snap ? Object.values(snap.analyses) : [];
  const withModel = a.find((x) => x.candidate);
  return withModel?.pair ?? a[0]?.pair ?? snap?.settings.watchlist[0] ?? null;
}

function drawChart(g: CanvasRenderingContext2D, W: number, H: number, candles: Candle[] | null, a: MarketAnalysis | undefined, pair: string | null, mode: string | null, tick: number) {
  g.clearRect(0, 0, W, H);
  g.fillStyle = 'rgba(0,30,60,0.78)'; g.fillRect(0, 0, W, H);
  g.strokeStyle = '#00f0ff'; g.lineWidth = 6; g.strokeRect(3, 3, W - 6, H - 6);
  g.strokeStyle = 'rgba(0,240,255,0.18)'; g.lineWidth = 1;
  for (let i = 1; i < 6; i++) { g.beginPath(); g.moveTo(0, (H / 6) * i); g.lineTo(W, (H / 6) * i); g.stroke(); }
  if (!candles || candles.length < 2) { strokedText(g, pair ? 'LOADING CHART…' : 'NO PAIR YET', W / 2, H / 2, 54, '#00f0ff', INK, 6); return; }
  const pad = 54;
  let lo = Math.min(...candles.map((c) => c.l)), hi = Math.max(...candles.map((c) => c.h));
  const cand = a?.candidate;
  if (cand) { lo = Math.min(lo, cand.stop_loss); hi = Math.max(hi, cand.take_profits[0]); }
  const span = hi - lo || 1;
  const y = (v: number) => H - pad - ((v - lo) / span) * (H - pad * 1.6);
  const cw = (W - pad) / candles.length;
  if (cand) {
    const long = cand.direction === 'long';
    g.fillStyle = long ? 'rgba(43,255,136,0.25)' : 'rgba(255,59,59,0.25)';
    g.fillRect(0, y(cand.entry_zone.high), W, y(cand.entry_zone.low) - y(cand.entry_zone.high));
    g.setLineDash([10, 8]); g.lineWidth = 3;
    g.strokeStyle = '#ff3b3b'; g.beginPath(); g.moveTo(0, y(cand.stop_loss)); g.lineTo(W, y(cand.stop_loss)); g.stroke();
    g.strokeStyle = '#2bff88'; for (const tp of cand.take_profits) if (tp <= hi && tp >= lo) { g.beginPath(); g.moveTo(0, y(tp)); g.lineTo(W, y(tp)); g.stroke(); }
    g.setLineDash([]);
  }
  candles.forEach((c, i) => {
    const x = 20 + i * cw;
    const up = c.c >= c.o;
    g.strokeStyle = INK; g.lineWidth = 6; g.beginPath(); g.moveTo(x + cw / 2, y(c.h)); g.lineTo(x + cw / 2, y(c.l)); g.stroke();
    g.strokeStyle = up ? '#2bff88' : '#ff3b3b'; g.lineWidth = 2.5; g.beginPath(); g.moveTo(x + cw / 2, y(c.h)); g.lineTo(x + cw / 2, y(c.l)); g.stroke();
    g.fillStyle = up ? '#2bff88' : '#ff3b3b'; g.strokeStyle = INK; g.lineWidth = 2;
    const top = y(Math.max(c.o, c.c)), h = Math.max(2, Math.abs(y(c.o) - y(c.c)));
    g.fillRect(x + 1, top, cw - 2, h); g.strokeRect(x + 1, top, cw - 2, h);
  });
  // sweeping scan line
  const sx = ((tick * 90) % (W + 80)) - 40;
  const grd = g.createLinearGradient(sx - 40, 0, sx, 0); grd.addColorStop(0, 'rgba(0,240,255,0)'); grd.addColorStop(1, 'rgba(0,240,255,0.45)');
  g.fillStyle = grd; g.fillRect(sx - 40, 0, 40, H);
  if (a?.sweep_time) {
    const idx = candles.findIndex((c) => c.t >= a.sweep_time!);
    if (idx >= 0) { strokedText(g, a.liquidity_event === 'sell_side_sweep' ? 'SWEEP ▲' : 'SWEEP ▼', Math.min(W - 90, 20 + idx * cw), a.liquidity_event === 'sell_side_sweep' ? H - 26 : 40, 34, '#ffd426', INK, 6); }
  }
  strokedText(g, `${pair} · M15`, 110, 26, 34, '#ffffff', INK, 6);
  strokedText(g, mode === 'DEMO' ? 'DEMO DATA' : 'LIVE', W - 80, 26, 30, mode === 'DEMO' ? '#ffd426' : '#2bff88', INK, 6);
}

export function AnalystHolo({ snap, live, busy, w, d }: { snap: Snapshot | null; live: LiveState; busy: boolean; w: number; d: number }) {
  const pair = pickPair(snap, live);
  const data = useCandles(pair);
  const a = pair ? snap?.analyses[pair] : undefined;
  const [tick, setTick] = useState(0);
  useEffect(() => { const t = setInterval(() => setTick((x) => x + 0.12), 120); return () => clearInterval(t); }, []);
  const tex = useCanvasTexture(1024, 400, (g, W, H) => drawChart(g, W, H, data?.candles ?? null, a, pair, data?.mode ?? null, tick), [data, a, pair, tick]);
  const orbit = useRef<THREE.Group>(null);
  useFrame(({ clock }) => { if (orbit.current) orbit.current.rotation.y = clock.elapsedTime * (busy ? 0.7 : 0.25); });
  const cands = useMemo(() => Array.from({ length: 16 }).map((_, i) => ({ a: (i / 16) * Math.PI * 2, r: 6 + (i % 3) * 1.6, y: 5.5 + (i % 5) * 1.5, up: i % 3 !== 0, h: 0.9 + (i % 4) * 0.5 })), []);
  const arrow = useRef<THREE.Group>(null);
  useFrame(({ clock }) => { if (arrow.current) arrow.current.position.y = 7.3 + Math.sin(clock.elapsedTime * 3) * 0.35; });
  const dir = a?.candidate?.direction;
  return (
    <group>
      <mesh position={[0, 3.2, -d / 2 + 0.55]}><planeGeometry args={[w - 1.2, 3.5]} /><meshBasicMaterial map={tex} transparent toneMapped={false} side={THREE.DoubleSide} /></mesh>
      <group ref={orbit} position={[0, 0, 0]}>
        {cands.map((c, i) => (
          <group key={i} position={[Math.cos(c.a) * c.r, PODIUM_H + c.y, Math.sin(c.a) * c.r]}>
            <mesh><boxGeometry args={[0.1, c.h * 1.6, 0.1]} /><meshBasicMaterial color={INK} /></mesh>
            <mesh><boxGeometry args={[0.55, c.h, 0.55]} /><meshToonMaterial color={c.up ? '#2bff88' : '#ff3b3b'} gradientMap={toonGradient()} emissive={c.up ? '#2bff88' : '#ff3b3b'} emissiveIntensity={0.5} /><Outlines thickness={0.05} color={INK} /></mesh>
          </group>))}
      </group>
      {dir && (
        <group ref={arrow} position={[0, 7.3, d / 2 + 1]}>
          <mesh rotation={[dir === 'long' ? 0 : Math.PI, 0, 0]}><coneGeometry args={[0.9, 1.6, 4]} /><meshToonMaterial color={dir === 'long' ? '#2bff88' : '#ff3b3b'} gradientMap={toonGradient()} emissive={dir === 'long' ? '#2bff88' : '#ff3b3b'} emissiveIntensity={0.8} /><Outlines thickness={0.07} color={INK} /></mesh>
        </group>)}
    </group>
  );
}

/* ------------------------------------------------------------------ */
/* News: floating screens, scrolling headlines, currency glyphs        */
/* ------------------------------------------------------------------ */
const IMPACT_COLOR: Record<string, string> = { LOW: '#6a8cff', MEDIUM: '#ffd426', HIGH: '#ff8a1f', EXTREME: '#ff2b2b' };

function NewsScreen({ items, offset, pos, rot, size = [3.4, 2.1] }: { items: Snapshot['news'] extends infer N ? (N extends { items: infer I } ? I : never) : never; offset: number; pos: [number, number, number]; rot: number; size?: [number, number] }) {
  const [t, setT] = useState(0);
  useEffect(() => { const i = setInterval(() => setT((x) => x + 1), 200); return () => clearInterval(i); }, []);
  const tex = useCanvasTexture(512, 320, (g, W, H) => {
    g.fillStyle = '#12082a'; g.fillRect(0, 0, W, H);
    const list = (items as any[]) ?? [];
    const it = list.length ? list[(offset + Math.floor(t / 28)) % list.length] : null;
    g.fillStyle = it ? IMPACT_COLOR[it.impact] : '#444'; g.fillRect(0, 0, W, 54);
    strokedText(g, it ? `${it.impact} IMPACT` : 'NO FEED', W / 2, 28, 44, '#fff', INK, 7);
    g.fillStyle = '#fff'; g.font = "bold 30px 'Comic Neue', 'Comic Sans MS', sans-serif"; g.textAlign = 'left'; g.textBaseline = 'top';
    const text = it ? it.headline : 'News feed unavailable or waiting for the first scan';
    const words = text.split(' '); let line = '', yy = 70, n = 0;
    for (const w of words) { const test = `${line}${w} `; if (g.measureText(test).width > W - 36 && line) { g.fillText(line, 18, yy); line = `${w} `; yy += 36; if (++n >= 5) break; } else line = test; }
    if (n < 5) g.fillText(line, 18, yy);
    g.fillStyle = '#ffd426'; g.fillRect(0, H - 40, W, 40);
    g.fillStyle = INK; g.font = "bold 24px 'Comic Neue', sans-serif";
    const tick = list.map((x: any) => `${x.currencies.join('/') || '—'}: ${x.headline}`).join('   ◆   ') || 'WAITING FOR NEWS';
    g.fillText(tick, 12 - ((t * 9) % Math.max(400, g.measureText(tick).width)), H - 32);
  }, [items, offset, t]);
  return (
    <group position={pos} rotation={[0, rot, 0]}>
      <mesh><planeGeometry args={size} /><meshBasicMaterial map={tex} toneMapped={false} side={THREE.DoubleSide} /></mesh>
      <mesh position={[0, 0, -0.04]}><boxGeometry args={[size[0] + 0.2, size[1] + 0.2, 0.06]} /><meshBasicMaterial color={INK} /></mesh>
    </group>
  );
}

function Glyph({ ch, color, base, phase }: { ch: string; color: string; base: [number, number, number]; phase: number }) {
  const tex = useCanvasTexture(128, 128, (g, W, H) => { g.clearRect(0, 0, W, H); strokedText(g, ch, W / 2, H / 2 + 4, 110, color, INK, 12); }, [ch, color]);
  const ref = useRef<THREE.Group>(null);
  const mat = useRef<THREE.MeshBasicMaterial>(null);
  useFrame(({ clock }) => {
    const t = (clock.elapsedTime * 0.35 + phase) % 1;
    if (ref.current) ref.current.position.set(base[0] + Math.sin(phase * 9 + clock.elapsedTime) * 0.6, base[1] + t * 3.2, base[2]);
    if (mat.current) mat.current.opacity = Math.sin(t * Math.PI);
  });
  return <group ref={ref}><Billboard><mesh><planeGeometry args={[1.5, 1.5]} /><meshBasicMaterial ref={mat} map={tex} transparent toneMapped={false} depthWrite={false} /></mesh></Billboard></group>;
}

export function NewsHolo({ snap, live, w, d }: { snap: Snapshot | null; live: LiveState; w: number; d: number }) {
  const items = snap?.news?.items ?? [];
  const [flash, setFlash] = useState(false);
  useEffect(() => { const i = setInterval(() => setFlash(Date.now() - live.breakingAt < 7000), 250); return () => clearInterval(i); }, [live.breakingAt]);
  const light = useRef<THREE.PointLight>(null);
  useFrame(({ clock }) => { if (light.current) light.current.intensity = flash ? (Math.sin(clock.elapsedTime * 14) > 0 ? 8 : 0.5) : 0; });
  const banner = useCanvasTexture(512, 128, (g, W, H) => { g.fillStyle = '#ff2b2b'; g.fillRect(0, 0, W, H); strokedText(g, '⚡ BREAKING NEWS ⚡', W / 2, H / 2 + 4, 74, '#fff', INK, 9); }, []);
  return (
    <group>
      <NewsScreen items={items as any} offset={0} pos={[-w / 2 + 2, 3.3, -d / 2 + 0.9]} rot={0.35} />
      <NewsScreen items={items as any} offset={1} pos={[0, 3.6, -d / 2 + 0.6]} rot={0} size={[4, 2.5]} />
      <NewsScreen items={items as any} offset={2} pos={[w / 2 - 2, 3.3, -d / 2 + 0.9]} rot={-0.35} />
      {[['$', '#2bff88'], ['€', '#2fa8ff'], ['£', '#ff4fd8'], ['¥', '#ffd426'], ['₣', '#ff8a1f'], ['$', '#2bff88']].map(([ch, c], i) => (
        <Glyph key={i} ch={ch} color={c} base={[-w / 2 + 1 + i * (w / 6), PODIUM_H + 0.5, d / 2 + 0.5]} phase={i * 0.17} />
      ))}
      {flash && (
        <group position={[0, PODIUM_H + 11 + 2.2, d / 2 + 0.5]}>
          <mesh><planeGeometry args={[7.5, 1.9]} /><meshBasicMaterial map={banner} toneMapped={false} /></mesh>
          <pointLight ref={light} color="#ff2b2b" distance={30} position={[0, 0, 2]} />
        </group>)}
    </group>
  );
}

/* ------------------------------------------------------------------ */
/* Hunter: radar + confidence meter                                    */
/* ------------------------------------------------------------------ */
const hashAngle = (s: string) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; };

export function HunterRadar({ snap, live }: { snap: Snapshot | null; live: LiveState }) {
  const sweep = useRef<THREE.Mesh>(null);
  useFrame((_, dt) => { if (sweep.current) sweep.current.rotation.z -= dt * (live.scanning ? 3.2 : 1.2); });
  const list = snap?.settings.watchlist ?? [];
  const evals = new Map((snap?.hunter?.evaluations ?? []).map((e) => [e.pair, e]));
  const [pulse, setPulse] = useState(0);
  useEffect(() => { const i = setInterval(() => setPulse((p) => p + 1), 250); return () => clearInterval(i); }, []);
  const rt = roofOf('setup_hunter');
  return (
    <group position={[rt[0], rt[1] + 3.2, rt[2] + 1]} rotation={[-0.9, 0, 0]}>
      <mesh><circleGeometry args={[4.4, 40]} /><meshBasicMaterial color="#04200f" transparent opacity={0.9} /></mesh>
      {[1.1, 2.2, 3.3, 4.3].map((r) => <mesh key={r} position={[0, 0, 0.01]}><ringGeometry args={[r - 0.04, r, 48]} /><meshBasicMaterial color="#2bff88" /></mesh>)}
      <mesh position={[0, 0, 0.01]}><planeGeometry args={[8.8, 0.04]} /><meshBasicMaterial color="#2bff88" /></mesh>
      <mesh position={[0, 0, 0.01]}><planeGeometry args={[0.04, 8.8]} /><meshBasicMaterial color="#2bff88" /></mesh>
      <mesh ref={sweep} position={[0, 0, 0.03]}><circleGeometry args={[4.3, 32, 0, Math.PI / 4]} /><meshBasicMaterial color="#2bff88" transparent opacity={0.45} blending={THREE.AdditiveBlending} depthWrite={false} /></mesh>
      <mesh position={[0, 0, 0.02]}><ringGeometry args={[4.4, 4.7, 40]} /><meshToonMaterial color="#ff5a3b" gradientMap={toonGradient()} /><Outlines thickness={0.05} color={INK} /></mesh>
      {list.map((p, i) => {
        const e = evals.get(p);
        const ang = (i / list.length) * Math.PI * 2 + (hashAngle(p) % 100) / 400;
        const rad = 1.1 + ((hashAngle(p) >> 3) % 100) / 100 * 2.7;
        const scanning = live.scanning?.pair === p;
        const color = scanning ? '#ffd426' : e ? (e.approved ? '#2bff88' : e.confidence_score > 0 ? '#ff3b3b' : '#6a5a8a') : '#2fa8ff';
        const size = scanning ? 0.34 + (pulse % 2) * 0.12 : e?.approved ? 0.4 : 0.2;
        return (
          <mesh key={p} position={[Math.cos(ang) * rad, Math.sin(ang) * rad, 0.1]}>
            <sphereGeometry args={[size, 10, 8]} /><meshBasicMaterial color={color} />
            {(scanning || e?.approved) && <Html center distanceFactor={26} style={{ pointerEvents: 'none' }}><div className="blip-label">{p}</div></Html>}
          </mesh>);
      })}
    </group>
  );
}

export function ConfidenceMeter({ snap, live }: { snap: Snapshot | null; live: LiveState }) {
  const b = BUILDINGS.setup_hunter;
  const best = snap?.hunter?.best?.score ?? (live.recentEvals.length ? Math.max(...live.recentEvals.map((e) => e.score)) : 0);
  const fill = useRef<THREE.Mesh>(null);
  const cur = useRef(0);
  useFrame((_, dt) => {
    cur.current += (best - cur.current) * Math.min(1, dt * 3);
    if (fill.current) { const h = Math.max(0.05, (cur.current / 100) * 9); fill.current.scale.y = h; fill.current.position.y = h / 2; }
  });
  const color = best >= 90 ? '#2bff88' : best >= 80 ? '#ffd426' : '#ff3b3b';
  return (
    <group position={[b.w / 2 + 3.2, 0, b.d / 2 + 1.5]}>
      <Block size={[1.6, 9.6, 1]} pos={[0, 4.8, 0]} color="#1b1b33" />
      <mesh ref={fill} position={[0, 0.5, 0.55]}><boxGeometry args={[1.1, 1, 0.3]} /><meshToonMaterial color={color} gradientMap={toonGradient()} emissive={color} emissiveIntensity={0.7} /></mesh>
      {[80, 85, 90].map((t) => <mesh key={t} position={[0, (t / 100) * 9, 0.75]}><boxGeometry args={[1.9, 0.07, 0.1]} /><meshBasicMaterial color="#fff" /></mesh>)}
      <Html position={[0, 10.8, 0]} center distanceFactor={24} style={{ pointerEvents: 'none' }}>
        <div className="meter-label"><span>BEST SCORE</span><b style={{ color }}>{Math.round(best)}</b></div>
      </Html>
    </group>
  );
}

/* ------------------------------------------------------------------ */
/* Command: beacons, burst effect and the Telegram relay               */
/* ------------------------------------------------------------------ */
export function CommandBeacon({ live }: { live: LiveState }) {
  const rt = roofOf('signal_command');
  const spin = useRef<THREE.Group>(null);
  const burst = useRef<THREE.Mesh>(null);
  const red = useRef<THREE.PointLight>(null);
  const green = useRef<THREE.PointLight>(null);
  useFrame(({ clock }, dt) => {
    const since = (Date.now() - live.commandFlashAt) / 1000;
    const hot = since < 4;
    if (spin.current) spin.current.rotation.y += dt * (hot ? 9 : 2);
    if (red.current) red.current.intensity = hot ? 6 : 1.2;
    if (green.current) green.current.intensity = hot ? 6 : 1.2;
    if (burst.current) {
      const k = Math.min(1, since / 1.4);
      burst.current.visible = since < 1.4;
      burst.current.scale.setScalar(1 + k * 9);
      (burst.current.material as THREE.MeshBasicMaterial).opacity = 1 - k;
    }
    void clock;
  });
  return (
    <group position={[rt[0], rt[1] + 1.2, rt[2]]}>
      <mesh position={[0, 1.5, 0]}><cylinderGeometry args={[0.08, 0.14, 3, 6]} /><meshToonMaterial color="#333355" gradientMap={toonGradient()} /></mesh>
      <group ref={spin} position={[0, 3.2, 0]}>
        <mesh position={[0.8, 0, 0]}><sphereGeometry args={[0.45, 12, 10]} /><meshBasicMaterial color="#ff2b2b" /><pointLight ref={red} color="#ff2b2b" distance={25} /></mesh>
        <mesh position={[-0.8, 0, 0]}><sphereGeometry args={[0.45, 12, 10]} /><meshBasicMaterial color="#2bff88" /><pointLight ref={green} color="#2bff88" distance={25} /></mesh>
      </group>
      <mesh ref={burst} position={[0, 1, 0]} rotation={[-Math.PI / 2, 0, 0]} visible={false}><ringGeometry args={[0.8, 1, 32]} /><meshBasicMaterial color="#ffd426" transparent depthWrite={false} /></mesh>
    </group>
  );
}

export function TelegramRelay({ snap, live }: { snap: Snapshot | null; live: LiveState }) {
  const g = useRef<THREE.Group>(null);
  const plane = useRef<THREE.Group>(null);
  const shape = useMemo(() => {
    const s = new THREE.Shape();
    s.moveTo(-1.1, 0); s.lineTo(1.2, 0.8); s.lineTo(0.6, -0.9); s.lineTo(0.1, -0.2); s.lineTo(-0.35, -0.55); s.lineTo(-0.2, 0.0); s.closePath();
    return s;
  }, []);
  useFrame(({ clock }) => {
    if (g.current) g.current.position.y = TELEGRAM_POS[1] + Math.sin(clock.elapsedTime * 1.2) * 0.8;
    if (plane.current) { const hot = Date.now() - (live.lastSent?.at ?? 0) < 3000 || live.stage.telegram && live.running; plane.current.rotation.z = Math.sin(clock.elapsedTime * (hot ? 8 : 1.5)) * 0.25; }
  });
  const state = snap?.system.telegram.state;
  const label = snap?.mode === 'DEMO' ? 'DEMO PREVIEW ONLY' : state === 'CONNECTED' ? 'CONNECTED' : state === 'ERROR' ? 'ERROR' : 'NOT CONFIGURED';
  return (
    <group ref={g} position={TELEGRAM_POS}>
      <mesh><sphereGeometry args={[2.6, 24, 18]} /><meshToonMaterial color="#2aabee" gradientMap={toonGradient()} emissive="#2aabee" emissiveIntensity={0.55} /><Outlines thickness={0.12} color={INK} /></mesh>
      <group ref={plane} position={[0, 0, 2.7]}>
        <mesh><extrudeGeometry args={[shape, { depth: 0.2, bevelEnabled: false }]} /><meshToonMaterial color="#ffffff" gradientMap={toonGradient()} emissive="#ffffff" emissiveIntensity={0.3} /><Outlines thickness={0.05} color={INK} /></mesh>
      </group>
      <mesh rotation={[Math.PI / 2.4, 0, 0]}><torusGeometry args={[3.6, 0.1, 8, 40]} /><meshBasicMaterial color="#ffd426" /></mesh>
      <Html position={[0, -4.2, 0]} center distanceFactor={30} style={{ pointerEvents: 'none' }}><div className="tg-label">TELEGRAM<br /><small>{label}</small></div></Html>
    </group>
  );
}

export function Packets({ live }: { live: LiveState }) {
  const refs = useRef<Record<string, THREE.Group | null>>({});
  const curve = (p: LiveState['packets'][number]) => {
    const a = p.from === 'hunter' ? roofOf('setup_hunter') : roofOf('signal_command');
    const b = p.to === 'command' ? roofOf('signal_command') : TELEGRAM_POS;
    const start = new THREE.Vector3(...a), end = new THREE.Vector3(...b);
    const mid = start.clone().lerp(end, 0.5); mid.y += 10;
    return new THREE.QuadraticBezierCurve3(start, mid, end);
  };
  const curves = useMemo(() => new Map(live.packets.map((p) => [p.id, curve(p)])), [live.packets]);
  useFrame(() => {
    for (const p of live.packets) {
      const grp = refs.current[p.id]; const c = curves.get(p.id);
      if (!grp || !c) continue;
      const t = Math.min(1, (Date.now() - p.at) / 2400);
      grp.visible = t < 1;
      grp.children.forEach((child, i) => { const tt = Math.max(0, t - i * 0.025); child.position.copy(c.getPoint(tt)).sub(grp.position); child.scale.setScalar(1 - i * 0.14); });
    }
  });
  return (
    <>{live.packets.map((p) => (
      <group key={p.id} ref={(el) => { refs.current[p.id] = el; }}>
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <mesh key={i}>
            {i === 0 ? <boxGeometry args={[1.5, 1, 0.3]} /> : <sphereGeometry args={[0.35, 8, 6]} />}
            <meshBasicMaterial color={i === 0 ? '#ffffff' : p.to === 'telegram' ? '#2aabee' : '#ffd426'} />
          </mesh>))}
      </group>))}</>
  );
}
