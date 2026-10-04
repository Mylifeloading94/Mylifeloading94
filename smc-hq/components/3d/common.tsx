'use client';
import * as THREE from 'three';
import { Outlines } from '@react-three/drei';
import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { AgentId } from '@/types';

export const INK = '#0b0b14';

/** 'low' drops outlines, rain, sparkles and speech bubbles so weaker GPUs stay smooth. */
export type Quality = 'high' | 'low';
export const QualityContext = createContext<Quality>('high');
export const useQuality = () => useContext(QualityContext);

let grad: THREE.DataTexture | null = null;
/** 4-step cel-shading ramp shared by every toon material. */
export function toonGradient(): THREE.DataTexture {
  if (!grad) {
    grad = new THREE.DataTexture(new Uint8Array([70, 140, 210, 255]), 4, 1, THREE.RedFormat);
    grad.minFilter = grad.magFilter = THREE.NearestFilter;
    grad.needsUpdate = true;
  }
  return grad;
}

export interface BuildingSpec {
  id: AgentId; title: string; tag: string; pos: [number, number, number]; color: string; dark: string; accent: string;
  w: number; d: number; towerH: number;
}
export const PODIUM_H = 5.5;
export const BUILDINGS: Record<AgentId, BuildingSpec> = {
  market_analyst: { id: 'market_analyst', title: 'MARKET ANALYST', tag: 'CHARTS & STRUCTURE', pos: [-26, 0, 4], color: '#2fa8ff', dark: '#14507f', accent: '#00f0ff', w: 9, d: 8, towerH: 14 },
  news_intelligence: { id: 'news_intelligence', title: 'NEWS INTELLIGENCE', tag: 'HEADLINES & EVENTS', pos: [-9, 0, -11], color: '#ff4fd8', dark: '#7a1f68', accent: '#ffd426', w: 11, d: 8, towerH: 11 },
  setup_hunter: { id: 'setup_hunter', title: 'SETUP HUNTER', tag: 'SCAN & SCORE', pos: [9, 0, -11], color: '#ff5a3b', dark: '#7a2112', accent: '#ff2b2b', w: 9, d: 8, towerH: 17 },
  signal_command: { id: 'signal_command', title: 'SIGNAL COMMAND', tag: 'VALIDATE & TRANSMIT', pos: [27, 0, 4], color: '#2bff88', dark: '#0f6b3a', accent: '#ffd426', w: 8, d: 8, towerH: 20 },
};
export const TELEGRAM_POS: [number, number, number] = [38, 26, -6];
export const roofOf = (id: AgentId): [number, number, number] => {
  const b = BUILDINGS[id];
  return [b.pos[0], PODIUM_H + b.towerH + 1.5, b.pos[2]];
};

export function Block({ size, pos = [0, 0, 0], color, emissive, emissiveIntensity = 0.6, opacity = 1, outline = true, rot, map, castShadow }: {
  size: [number, number, number]; pos?: [number, number, number]; color: string; emissive?: string; emissiveIntensity?: number;
  opacity?: number; outline?: boolean; rot?: [number, number, number]; map?: THREE.Texture | null; castShadow?: boolean;
}) {
  const q = useQuality();
  return (
    <mesh position={pos} rotation={rot} castShadow={castShadow}>
      <boxGeometry args={size} />
      <meshToonMaterial color={color} gradientMap={toonGradient()} emissive={emissive ?? '#000000'} emissiveIntensity={emissive ? emissiveIntensity : 0}
        transparent={opacity < 1} opacity={opacity} map={map ?? null} emissiveMap={emissive && map ? map : null} />
      {outline && q === 'high' && opacity >= 1 && <Outlines thickness={0.06} color={INK} />}
    </mesh>
  );
}

/** Canvas → texture, redrawn when `deps` change (and once web fonts are ready). */
export function useCanvasTexture(w: number, h: number, draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void, deps: unknown[]) {
  const [fontsReady, setFontsReady] = useState(false);
  useEffect(() => { (document as any).fonts?.ready?.then(() => setFontsReady(true)); }, []);
  const canvas = useMemo(() => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }, [w, h]);
  const tex = useMemo(() => { const t = new THREE.CanvasTexture(canvas); t.colorSpace = THREE.SRGBColorSpace; return t; }, [canvas]);
  useEffect(() => {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    draw(ctx, w, h);
    tex.needsUpdate = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fontsReady, ...deps]);
  return tex;
}

export const COMIC_FONT = "Bangers, Impact, 'Arial Black', sans-serif";

export function strokedText(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, size: number, fill: string, stroke = INK, lw = 10, maxWidth?: number) {
  ctx.font = `${size}px ${COMIC_FONT}`;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.lineJoin = 'round'; ctx.lineWidth = lw; ctx.strokeStyle = stroke;
  ctx.strokeText(text, x, y, maxWidth); ctx.fillStyle = fill; ctx.fillText(text, x, y, maxWidth);
}
