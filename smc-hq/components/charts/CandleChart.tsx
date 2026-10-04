'use client';
import type { Candle } from '@/types';

export interface Overlay { zone?: { low: number; high: number; color: string }; lines?: { y: number; color: string; label: string }[] }

/** Plain SVG candlestick chart: real candles only, with optional zone / level overlays. */
export function CandleChart({ candles, overlay, height = 260 }: { candles: Candle[]; overlay?: Overlay; height?: number }) {
  if (candles.length < 2) return <div className="empty">NO CANDLES</div>;
  const W = 800, H = height, pad = 8;
  let lo = Math.min(...candles.map((c) => c.l)), hi = Math.max(...candles.map((c) => c.h));
  // Scale to candles + zone + nearby levels only; far-away targets are dropped from the chart instead of squashing the candles.
  if (overlay?.zone) { lo = Math.min(lo, overlay.zone.low); hi = Math.max(hi, overlay.zone.high); }
  const base = hi - lo || 1;
  const lines = (overlay?.lines ?? []).filter((l) => l.y >= lo - base * 0.6 && l.y <= hi + base * 0.6);
  for (const l of lines) { lo = Math.min(lo, l.y); hi = Math.max(hi, l.y); }
  const span = hi - lo || 1;
  const y = (v: number) => H - pad - ((v - lo) / span) * (H - pad * 2);
  const cw = (W - 70) / candles.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', background: '#10122b', border: '3px solid #0b0b14' }} role="img" aria-label="Candlestick chart">
      {overlay?.zone && <rect x={0} y={y(overlay.zone.high)} width={W - 62} height={Math.max(2, y(overlay.zone.low) - y(overlay.zone.high))} fill={overlay.zone.color} opacity={0.28} />}
      {candles.map((c, i) => {
        const x = 6 + i * cw, up = c.c >= c.o, col = up ? '#2bff88' : '#ff3b3b';
        return (
          <g key={c.t}>
            <line x1={x + cw / 2} x2={x + cw / 2} y1={y(c.h)} y2={y(c.l)} stroke={col} strokeWidth={1.4} />
            <rect x={x + 0.5} y={y(Math.max(c.o, c.c))} width={Math.max(1, cw - 1.5)} height={Math.max(1.5, Math.abs(y(c.o) - y(c.c)))} fill={col} stroke="#0b0b14" strokeWidth={0.6} />
          </g>);
      })}
      {lines.map((l) => (
        <g key={l.label}><line x1={0} x2={W - 62} y1={y(l.y)} y2={y(l.y)} stroke={l.color} strokeDasharray="6 4" strokeWidth={1.5} />
          <text x={W - 60} y={y(l.y) + 4} fill={l.color} fontSize={11} fontFamily="monospace">{l.label}</text></g>))}
      <text x={W - 60} y={y(candles[candles.length - 1].c) + 4} fill="#fff" fontSize={11} fontFamily="monospace">{candles[candles.length - 1].c.toFixed(candles[candles.length - 1].c > 500 ? 2 : 5)}</text>
    </svg>
  );
}
