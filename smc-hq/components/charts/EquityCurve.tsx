'use client';

export function EquityCurve({ points }: { points: { t: string; r: number }[] }) {
  if (points.length < 2) return <div className="empty" style={{ padding: 14 }}>EQUITY CURVE NEEDS ≥ 2 CLOSED SIGNALS</div>;
  const W = 600, H = 160, pad = 14;
  const vals = [0, ...points.map((p) => p.r)];
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const xy = (i: number, v: number) => [pad + (i / (vals.length - 1)) * (W - pad * 2), H - pad - ((v - lo) / span) * (H - pad * 2)];
  const d = vals.map((v, i) => `${i ? 'L' : 'M'}${xy(i, v).join(',')}`).join(' ');
  const zero = xy(0, 0)[1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', background: '#fff', border: '3px solid #0b0b14' }} role="img" aria-label="Equity curve in R">
      <line x1={0} x2={W} y1={zero} y2={zero} stroke="#999" strokeDasharray="4 4" />
      <path d={d} fill="none" stroke="#2fa8ff" strokeWidth={3} strokeLinejoin="round" />
      {vals.map((v, i) => { const [x, yy] = xy(i, v); return <circle key={i} cx={x} cy={yy} r={3.5} fill={i && v < vals[i - 1] ? '#ff3b3b' : '#2bff88'} stroke="#0b0b14" strokeWidth={1.5} />; })}
      <text x={W - 6} y={14} textAnchor="end" fontSize={12} fontFamily="monospace">{vals[vals.length - 1] >= 0 ? '+' : ''}{vals[vals.length - 1].toFixed(2)}R</text>
    </svg>
  );
}
