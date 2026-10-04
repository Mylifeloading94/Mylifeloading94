'use client';
import * as THREE from 'three';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Html, OrbitControls } from '@react-three/drei';
import { Suspense, useEffect, useRef } from 'react';
import type { AgentId } from '@/types';
import type { LiveState, Snapshot } from '../world-types';
import { AgentBuilding } from './Buildings';
import { Atmosphere, City } from './City';
import { BUILDINGS, PODIUM_H } from './common';
import { CommandBeacon, HunterRadar, Packets, TelegramRelay } from './Holos';

const HOME_POS = new THREE.Vector3(3, 38, 88);
const HOME_TARGET = new THREE.Vector3(3, 8, -2);

function CameraRig({ focus, controls, interacting }: { focus: AgentId | null; controls: React.MutableRefObject<any>; interacting: React.MutableRefObject<boolean> }) {
  const { camera } = useThree();
  const anim = useRef({ t: 1, fp: new THREE.Vector3(), ft: new THREE.Vector3(), tp: new THREE.Vector3(), tt: new THREE.Vector3() });
  const first = useRef(true);
  useEffect(() => {
    const c = controls.current;
    const a = anim.current;
    if (first.current) {
      first.current = false;
      camera.position.set(-70, 70, 100); // cinematic intro: swoop in from afar
      if (c) c.target.set(0, 6, -4);
    }
    a.fp.copy(camera.position); a.ft.copy(c ? c.target : HOME_TARGET);
    if (focus) {
      const b = BUILDINGS[focus];
      a.tt.set(b.pos[0] + 9, PODIUM_H + 4, b.pos[2]);
      a.tp.set(b.pos[0] + 9, PODIUM_H + 8, b.pos[2] + 36);
    } else { a.tp.copy(HOME_POS); a.tt.copy(HOME_TARGET); }
    a.t = 0;
  }, [focus, camera, controls]);
  useFrame((_, dt) => {
    const a = anim.current;
    if (a.t >= 1) return;
    a.t = Math.min(1, a.t + dt / (a.fp.length() > 120 ? 3.4 : 1.7));
    const k = 1 - Math.pow(1 - a.t, 3);
    camera.position.lerpVectors(a.fp, a.tp, k);
    if (controls.current) { controls.current.target.lerpVectors(a.ft, a.tt, k); controls.current.update(); }
    interacting.current = false;
  });
  return null;
}

function Scene({ snap, live, selected, onSelect, idle }: { snap: Snapshot | null; live: LiveState; selected: AgentId | null; onSelect: (id: AgentId | null) => void; idle: boolean }) {
  const controls = useRef<any>(null);
  const interacting = useRef(false);
  return (
    <>
      <color attach="background" args={['#0d0a24']} />
      <fog attach="fog" args={['#120e32', 70, 210]} />
      <ambientLight intensity={0.9} color="#7a6cff" />
      <hemisphereLight args={['#8fa8ff', '#2a1a4a', 0.7]} />
      <directionalLight position={[-30, 50, 30]} intensity={1.6} color="#b9c8ff" />
      <directionalLight position={[40, 20, 50]} intensity={0.6} color="#ff8ad8" />
      <Suspense fallback={<Html center><div className="loading-pop">LOADING CITY…</div></Html>}>
        <City />
        <Atmosphere />
        {(Object.keys(BUILDINGS) as AgentId[]).map((id) => (
          <AgentBuilding key={id} id={id} snap={snap} live={live} selected={selected === id} onSelect={onSelect} />
        ))}
        <HunterRadar snap={snap} live={live} />
        <CommandBeacon live={live} />
        <TelegramRelay snap={snap} live={live} />
        <Packets live={live} />
      </Suspense>
      <mesh visible={false} position={[0, -1, 0]} rotation={[-Math.PI / 2, 0, 0]} onClick={() => onSelect(null)}><planeGeometry args={[400, 400]} /></mesh>
      <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.08} maxPolarAngle={Math.PI / 2.15} minDistance={8} maxDistance={150}
        autoRotate={idle && !selected} autoRotateSpeed={0.35} onStart={() => { interacting.current = true; }} />
      <CameraRig focus={selected} controls={controls} interacting={interacting} />
    </>
  );
}

export default function World(props: { snap: Snapshot | null; live: LiveState; selected: AgentId | null; onSelect: (id: AgentId | null) => void; idle: boolean }) {
  return (
    <Canvas shadows={false} dpr={[1, 1.75]} camera={{ fov: 46, near: 0.5, far: 520, position: [-70, 70, 100] }} gl={{ antialias: true, powerPreference: 'high-performance' }}
      onCreated={({ gl }) => { gl.toneMapping = THREE.NoToneMapping; gl.outputColorSpace = THREE.SRGBColorSpace; }}>
      <Scene {...props} />
    </Canvas>
  );
}
