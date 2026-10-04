'use client';
import { useFrame } from '@react-three/fiber';
import { Outlines } from '@react-three/drei';
import { useRef } from 'react';
import type * as THREE from 'three';
import { INK, toonGradient } from './common';

export interface Look { skin: string; shirt: string; pants: string; hair: string; hairStyle: 'spiky' | 'swoop' | 'bun' | 'flat'; accessory?: 'visor' | 'headset' | 'glasses' | 'none' }

const M = ({ c, e }: { c: string; e?: string }) => <meshToonMaterial color={c} gradientMap={toonGradient()} emissive={e ?? '#000'} emissiveIntensity={e ? 0.5 : 0} />;

/**
 * Original stylised comic-book operator: chunky proportions, thick outlines, big expressive eyes.
 * `busy` speeds up the typing / pointing animation.
 */
export function Operator({ look, busy, scale = 1, phase = 0 }: { look: Look; busy: boolean; scale?: number; phase?: number }) {
  const root = useRef<THREE.Group>(null);
  const armL = useRef<THREE.Group>(null);
  const armR = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime + phase;
    const sp = busy ? 9 : 2.2;
    if (root.current) root.current.position.y = Math.abs(Math.sin(t * (busy ? 4 : 1.5))) * (busy ? 0.08 : 0.04);
    if (armL.current) armL.current.rotation.x = -0.9 + Math.sin(t * sp) * (busy ? 0.5 : 0.12);
    if (armR.current) armR.current.rotation.x = -0.9 + Math.sin(t * sp + 1.7) * (busy ? 0.5 : 0.12);
    if (head.current) { head.current.rotation.y = Math.sin(t * 0.8) * 0.35; head.current.rotation.z = Math.sin(t * 1.3) * 0.05; }
  });
  const hair = () => {
    if (look.hairStyle === 'spiky') return [0, 1, 2, 3, 4].map((i) => (
      <mesh key={i} position={[(i - 2) * 0.17, 0.5 + (i % 2 ? 0.02 : 0.1), -0.02]} rotation={[0, 0, (2 - i) * 0.35]}>
        <coneGeometry args={[0.13, 0.42, 6]} /><M c={look.hair} />
      </mesh>));
    if (look.hairStyle === 'swoop') return (
      <mesh position={[0.08, 0.46, 0.05]} rotation={[0.2, 0, -0.35]} scale={[1.2, 0.55, 1.1]}>
        <sphereGeometry args={[0.42, 12, 10]} /><M c={look.hair} />
      </mesh>);
    if (look.hairStyle === 'bun') return (<>
      <mesh position={[0, 0.4, -0.05]} scale={[1.05, 0.7, 1.05]}><sphereGeometry args={[0.42, 12, 10]} /><M c={look.hair} /></mesh>
      <mesh position={[0, 0.85, -0.1]}><sphereGeometry args={[0.2, 10, 8]} /><M c={look.hair} /></mesh></>);
    return (<mesh position={[0, 0.42, -0.02]} scale={[1.04, 0.6, 1.04]}><sphereGeometry args={[0.42, 12, 10]} /><M c={look.hair} /></mesh>);
  };
  return (
    <group ref={root} scale={scale}>
      {/* legs */}
      {[-0.2, 0.2].map((x) => (
        <mesh key={x} position={[x, 0.45, 0]}><boxGeometry args={[0.28, 0.9, 0.3]} /><M c={look.pants} /></mesh>))}
      {/* torso */}
      <mesh position={[0, 1.3, 0]}><capsuleGeometry args={[0.45, 0.55, 6, 12]} /><M c={look.shirt} /><Outlines thickness={0.05} color={INK} /></mesh>
      {/* arms */}
      {([['L', -0.62, armL], ['R', 0.62, armR]] as const).map(([k, x, ref]) => (
        <group key={k} ref={ref} position={[x, 1.65, 0]}>
          <mesh position={[0, -0.35, 0.25]} rotation={[0.1, 0, 0]}><capsuleGeometry args={[0.13, 0.55, 4, 8]} /><M c={look.shirt} /></mesh>
          <mesh position={[0, -0.7, 0.45]}><sphereGeometry args={[0.15, 8, 8]} /><M c={look.skin} /></mesh>
        </group>))}
      {/* head */}
      <group ref={head} position={[0, 2.2, 0]}>
        <mesh><sphereGeometry args={[0.55, 20, 16]} /><M c={look.skin} /><Outlines thickness={0.05} color={INK} /></mesh>
        {hair()}
        {[-0.2, 0.2].map((x) => (
          <group key={x} position={[x, 0.05, 0.47]}>
            <mesh><sphereGeometry args={[0.14, 10, 8]} /><meshBasicMaterial color="#ffffff" /></mesh>
            <mesh position={[0, 0, 0.1]}><sphereGeometry args={[0.065, 8, 8]} /><meshBasicMaterial color={INK} /></mesh>
          </group>))}
        <mesh position={[0, -0.22, 0.5]} rotation={[0, 0, Math.PI]}><torusGeometry args={[0.1, 0.025, 6, 12, Math.PI]} /><meshBasicMaterial color={INK} /></mesh>
        {look.accessory === 'visor' && <mesh position={[0, 0.07, 0.5]}><boxGeometry args={[0.9, 0.2, 0.1]} /><meshStandardMaterial color="#00f0ff" emissive="#00f0ff" emissiveIntensity={1.2} transparent opacity={0.7} /></mesh>}
        {look.accessory === 'headset' && <mesh position={[0, 0.1, 0]} rotation={[0, 0, Math.PI / 2]}><torusGeometry args={[0.57, 0.04, 6, 16, Math.PI]} /><meshBasicMaterial color={INK} /></mesh>}
        {look.accessory === 'glasses' && [-0.2, 0.2].map((x) => <mesh key={x} position={[x, 0.05, 0.56]}><torusGeometry args={[0.15, 0.025, 6, 14]} /><meshBasicMaterial color={INK} /></mesh>)}
      </group>
    </group>
  );
}

export const LOOKS: Record<string, Look> = {
  analyst: { skin: '#ffd1a1', shirt: '#2fa8ff', pants: '#1b2a6b', hair: '#ffd426', hairStyle: 'spiky', accessory: 'visor' },
  news: { skin: '#c98b5e', shirt: '#ff4fd8', pants: '#3b1b4f', hair: '#2a1a3a', hairStyle: 'bun', accessory: 'headset' },
  hunter: { skin: '#ffe0bd', shirt: '#ff5a3b', pants: '#2d2d3a', hair: '#e8343a', hairStyle: 'swoop', accessory: 'glasses' },
  command: { skin: '#8d5a3c', shirt: '#2bff88', pants: '#14301f', hair: '#0b0b14', hairStyle: 'flat', accessory: 'headset' },
};
