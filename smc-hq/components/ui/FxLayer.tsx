'use client';
import type { Fx } from '../world-types';

const hash = (s: string) => { let h = 0; for (const c of s) h = (h * 33 + c.charCodeAt(0)) >>> 0; return h; };

export function FxLayer({ fx }: { fx: Fx[] }) {
  return (
    <div className="fx-layer" aria-hidden>
      {fx.map((f) => {
        const h = hash(f.id);
        return <div key={f.id} className={`fx ${f.kind}`} style={{ left: `${14 + (h % 52)}%`, top: `${18 + ((h >> 5) % 32)}%` }}>{f.text}</div>;
      })}
    </div>
  );
}
