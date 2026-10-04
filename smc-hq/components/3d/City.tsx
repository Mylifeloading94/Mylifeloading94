'use client';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { Grid, Outlines, Sparkles, Stars } from '@react-three/drei';
import { useLayoutEffect, useMemo, useRef } from 'react';
import { Block, INK, strokedText, toonGradient, useCanvasTexture, useQuality } from './common';

function rng(seed: number) { let a = seed; return () => { a = (a * 1664525 + 1013904223) % 4294967296; return a / 4294967296; }; }

function windowTexture(tint: string, seed: number, w = 128, h = 256) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const g = c.getContext('2d')!;
  const r = rng(seed);
  g.fillStyle = tint; g.fillRect(0, 0, w, h);
  for (let y = 8; y < h - 8; y += 24) for (let x = 8; x < w - 8; x += 20) {
    const lit = r() > 0.45;
    g.fillStyle = lit ? (r() > 0.5 ? '#ffe566' : '#7df3ff') : '#10102a';
    g.fillRect(x, y, 12, 14);
    g.strokeStyle = INK; g.lineWidth = 2; g.strokeRect(x, y, 12, 14);
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function makeWindowTexture(tint: string, seed: number, repeatX: number, repeatY: number) {
  const t = windowTexture(tint, seed); t.repeat.set(repeatX, repeatY); return t;
}

function Skyline() {
  const groups = useMemo(() => {
    const r = rng(7);
    const g: { p: [number, number, number]; s: [number, number, number] }[][] = [[], [], []];
    const cell = (x: number, z: number) => {
      const h = 6 + r() * 26, w = 6 + r() * 5, d = 6 + r() * 5;
      g[Math.floor(r() * 3)].push({ p: [x + (r() - 0.5) * 3, h / 2, z + (r() - 0.5) * 3], s: [w, h, d] });
    };
    for (let x = -88; x <= 88; x += 13) for (const z of [-34, -48, -62, -76]) cell(x, z);
    for (let z = -30; z <= 36; z += 13) { for (const x of [-52, -64, -78]) cell(x, z); for (const x of [52, 64, 78]) cell(x, z); }
    for (let x = -88; x <= 88; x += 14) if (Math.abs(x + 8) > 22 && Math.abs(x - 8) > 22 && Math.abs(x - 40) > 10) cell(x, 34);
    return g;
  }, []);
  const mats = useMemo(() => ['#1c1a45', '#2a1740', '#10253f'].map((t, i) => makeWindowTexture(t, 11 + i, 2, 3)), []);
  const refs = [useRef<THREE.InstancedMesh>(null), useRef<THREE.InstancedMesh>(null), useRef<THREE.InstancedMesh>(null)];
  useLayoutEffect(() => {
    const m = new THREE.Matrix4(), q = new THREE.Quaternion();
    groups.forEach((list, gi) => {
      const mesh = refs[gi].current;
      if (!mesh) return;
      list.forEach((b, i) => { m.compose(new THREE.Vector3(...b.p), q, new THREE.Vector3(...b.s)); mesh.setMatrixAt(i, m); });
      mesh.instanceMatrix.needsUpdate = true;
    });
  }, [groups]); // eslint-disable-line react-hooks/exhaustive-deps
  const tint = ['#5a4a9a', '#7a3a8a', '#3a6a9a'];
  // 3 draw calls for the whole skyline (was ~110 outlined meshes)
  return (
    <group>
      {groups.map((list, gi) => (
        <instancedMesh key={gi} ref={refs[gi]} args={[undefined, undefined, list.length]} frustumCulled={false}>
          <boxGeometry args={[1, 1, 1]} />
          <meshToonMaterial color={tint[gi]} gradientMap={toonGradient()} emissive="#ffffff" emissiveIntensity={0.55} map={mats[gi]} emissiveMap={mats[gi]} />
        </instancedMesh>
      ))}
    </group>
  );
}

function Neon({ text, color, pos, rot = 0, w = 6 }: { text: string; color: string; pos: [number, number, number]; rot?: number; w?: number }) {
  const tex = useCanvasTexture(512, 160, (g, W, H) => {
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#0b0b14'; g.fillRect(0, 0, W, H);
    g.strokeStyle = color; g.lineWidth = 10; g.strokeRect(8, 8, W - 16, H - 16);
    strokedText(g, text, W / 2, H / 2 + 4, 100, color, '#0b0b14', 4);
  }, [text, color]);
  const ref = useRef<THREE.MeshBasicMaterial>(null);
  useFrame(({ clock }) => { if (ref.current) ref.current.opacity = 0.75 + Math.sin(clock.elapsedTime * 3 + pos[0]) * 0.25; });
  return (
    <mesh position={pos} rotation={[0, rot, 0]}>
      <planeGeometry args={[w, w * 0.31]} />
      <meshBasicMaterial ref={ref} map={tex} transparent toneMapped={false} />
    </mesh>
  );
}

function Road({ pos, size }: { pos: [number, number, number]; size: [number, number] }) {
  const horizontal = size[0] > size[1];
  const len = horizontal ? size[0] : size[1];
  const dashes = Math.floor(len / 6);
  return (
    <group position={pos}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}><planeGeometry args={size} /><meshToonMaterial color="#1b1b33" gradientMap={toonGradient()} /></mesh>
      {Array.from({ length: dashes }).map((_, i) => (
        <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={horizontal ? [-len / 2 + 3 + i * 6, 0.04, 0] : [0, 0.04, -len / 2 + 3 + i * 6]}>
          <planeGeometry args={horizontal ? [2.6, 0.3] : [0.3, 2.6]} /><meshBasicMaterial color="#ffd426" />
        </mesh>))}
    </group>
  );
}

function Car({ axis, fixed, lo, hi, speed, color, offset }: { axis: 'x' | 'z'; fixed: number; lo: number; hi: number; speed: number; color: string; offset: number }) {
  const ref = useRef<THREE.Group>(null);
  const span = hi - lo;
  useFrame(({ clock }) => {
    if (!ref.current) return;
    const raw = (clock.elapsedTime * Math.abs(speed) + offset) % span;
    const v = speed > 0 ? lo + raw : hi - raw;
    if (axis === 'x') { ref.current.position.set(v, 0.55, fixed); ref.current.rotation.y = speed > 0 ? 0 : Math.PI; }
    else { ref.current.position.set(fixed, 0.55, v); ref.current.rotation.y = speed > 0 ? Math.PI / 2 : -Math.PI / 2; }
  });
  return (
    <group ref={ref}>
      <Block size={[2.4, 0.7, 1.2]} color={color} pos={[0, 0, 0]} outline={false} />
      <Block size={[1.2, 0.55, 1.05]} color="#bfe9ff" pos={[-0.1, 0.55, 0]} outline={false} />
      <mesh position={[1.22, 0, 0.4]}><sphereGeometry args={[0.16, 8, 8]} /><meshBasicMaterial color="#fff6a0" /></mesh>
      <mesh position={[1.22, 0, -0.4]}><sphereGeometry args={[0.16, 8, 8]} /><meshBasicMaterial color="#fff6a0" /></mesh>
      <mesh position={[-1.22, 0.05, 0]}><boxGeometry args={[0.05, 0.2, 0.9]} /><meshBasicMaterial color="#ff2b2b" /></mesh>
    </group>
  );
}

const CAR_COLORS = ['#ffd426', '#ff3b3b', '#2fa8ff', '#ff4fd8', '#2bff88', '#ffffff', '#ff8a1f'];
function Traffic() {
  const cars = useMemo(() => {
    const r = rng(99);
    const out: Parameters<typeof Car>[0][] = [];
    const lane = (axis: 'x' | 'z', fixed: number, lo: number, hi: number, n: number) => {
      for (let i = 0; i < n; i++) out.push({ axis, fixed: fixed + (i % 2 ? 1.1 : -1.1), lo, hi, speed: (i % 2 ? 1 : -1) * (4 + r() * 5), color: CAR_COLORS[Math.floor(r() * CAR_COLORS.length)], offset: r() * (hi - lo) });
    };
    lane('x', 16, -80, 80, 5); lane('x', -24, -80, 80, 3); lane('z', 0.5, -24, 16, 3); lane('z', -43, -24, 16, 2); lane('z', 45, -24, 16, 2);
    return out;
  }, []);
  return <>{cars.map((c, i) => <Car key={i} {...c} />)}</>;
}

function Lamps() {
  const pts = useMemo(() => { const a: [number, number][] = []; for (let x = -70; x <= 70; x += 14) a.push([x, 12.8], [x, 19.2]); return a; }, []);
  return (
    <>{pts.map(([x, z], i) => (
      <group key={i} position={[x, 0, z]}>
        <mesh position={[0, 2.2, 0]}><cylinderGeometry args={[0.1, 0.14, 4.4, 6]} /><meshToonMaterial color="#333355" gradientMap={toonGradient()} /></mesh>
        <mesh position={[0, 4.5, 0]}><sphereGeometry args={[0.35, 8, 8]} /><meshBasicMaterial color="#fff2a8" /></mesh>
      </group>))}</>
  );
}

export function City() {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]}><planeGeometry args={[400, 400]} /><meshToonMaterial color="#17133a" gradientMap={toonGradient()} /></mesh>
      <Grid position={[0, 0.005, 0]} args={[240, 240]} cellSize={4} sectionSize={20} cellColor="#2a2670" sectionColor="#6a4cff" fadeDistance={150} fadeStrength={1.5} infiniteGrid={false} cellThickness={0.6} sectionThickness={1.1} />
      <Road pos={[0, 0, 16]} size={[200, 6]} />
      <Road pos={[0, 0, -24]} size={[200, 6]} />
      <Road pos={[0.5, 0, -4]} size={[6, 40]} />
      <Road pos={[-43, 0, -4]} size={[6, 40]} />
      <Road pos={[45, 0, -4]} size={[6, 40]} />
      <Skyline />
      <Traffic />
      <Lamps />
      <Neon text="FOREX" color="#ff4fd8" pos={[-46, 12, 22]} w={7} />
      <Neon text="GOLD" color="#ffd426" pos={[50, 14, 22]} w={7} />
      <Neon text="24/5" color="#00f0ff" pos={[-18, 9, 34.2]} w={6} />
      <Neon text="PIPS" color="#2bff88" pos={[16, 11, 34.2]} w={6} />
      <Neon text="LIQUIDITY" color="#ff5a3b" pos={[0, 15, -30]} w={9} />
    </group>
  );
}

function Cloud({ x, y, z, s, speed }: { x: number; y: number; z: number; s: number; speed: number }) {
  const ref = useRef<THREE.Group>(null);
  useFrame(({ clock }) => { if (ref.current) { ref.current.position.x = ((x + clock.elapsedTime * speed + 120) % 240) - 120; } });
  return (
    <group ref={ref} position={[x, y, z]} scale={s}>
      {[[0, 0, 0, 3], [3, -0.4, 0.4, 2.4], [-3, -0.3, 0, 2.5], [1.2, 1.2, 0, 2.2], [-1.4, 0.9, 0.5, 2]].map(([px, py, pz, r], i) => (
        <mesh key={i} position={[px, py, pz]}><sphereGeometry args={[r, 12, 10]} /><meshToonMaterial color="#6a5aa8" gradientMap={toonGradient()} transparent opacity={0.85} /></mesh>
      ))}
    </group>
  );
}

const RAIN_V = `
  uniform float uTime;
  void main() {
    vec3 p = position;
    p.y = mod(p.y - uTime * 30.0, 50.0);
    p.x = mod(p.x - uTime * 3.0 + 70.0, 140.0) - 70.0;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = 90.0 / -mv.z;
    gl_Position = projectionMatrix * mv;
  }`;
const RAIN_F = `void main() { gl_FragColor = vec4(0.56, 0.72, 1.0, 0.5); }`;

/** Rain is animated entirely in the vertex shader: zero per-frame JavaScript. */
function Rain() {
  const N = 500;
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const p = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) { p[i * 3] = (Math.random() - 0.5) * 140; p[i * 3 + 1] = Math.random() * 50; p[i * 3 + 2] = (Math.random() - 0.5) * 100; }
    g.setAttribute('position', new THREE.BufferAttribute(p, 3));
    return g;
  }, []);
  const mat = useRef<THREE.ShaderMaterial>(null);
  useFrame(({ clock }) => { if (mat.current) mat.current.uniforms.uTime.value = clock.elapsedTime; });
  return (
    <points geometry={geo} frustumCulled={false}>
      <shaderMaterial ref={mat} vertexShader={RAIN_V} fragmentShader={RAIN_F} uniforms={{ uTime: { value: 0 } }} transparent depthWrite={false} />
    </points>
  );
}

export function Atmosphere() {
  const low = useQuality() === 'low';
  return (
    <group>
      <Stars radius={180} depth={50} count={low ? 600 : 1200} factor={6} saturation={0.4} fade speed={low ? 0 : 1} />
      <mesh position={[-70, 60, -110]}><sphereGeometry args={[9, 24, 18]} /><meshBasicMaterial color="#fff2a8" /><Outlines thickness={0.4} color={INK} /></mesh>
      <Cloud x={-60} y={44} z={-60} s={1.6} speed={1.1} /><Cloud x={10} y={52} z={-80} s={2} speed={0.8} />
      <Cloud x={50} y={40} z={-50} s={1.4} speed={1.4} /><Cloud x={-20} y={36} z={-30} s={1.2} speed={0.9} />
      <Cloud x={70} y={50} z={-90} s={1.8} speed={0.6} /><Cloud x={-90} y={38} z={-20} s={1.3} speed={1.2} />
      {!low && <Rain />}
      {!low && <Sparkles count={50} scale={[110, 34, 70]} size={4} speed={0.35} color="#ffd426" position={[0, 16, 0]} />}
    </group>
  );
}
