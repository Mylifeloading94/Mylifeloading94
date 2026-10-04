'use client';
import { useEffect, useState } from 'react';
import type { DataMode } from '@/types';
import type { Performance } from '@/lib/stats';
import { EquityCurve } from '../charts/EquityCurve';
import { Chip, Empty, Loading, num, Stat, ViewShell } from '../ui/Comic';
import type { Snapshot } from '../world-types';

export function PerformanceView({ snap, onClose }: { snap: Snapshot | null; onClose: () => void }) {
  const [mode, setMode] = useState<DataMode>('LIVE');
  const [p, setP] = useState<Performance | null>(null);
  useEffect(() => { setP(null); fetch(`/api/performance?mode=${mode}`, { cache: 'no-store' }).then((r) => r.json()).then(setP); }, [mode, snap?.lastSignal?.signal_id, snap?.signals?.length]);
  const pf = p?.profit_factor;
  return (
    <ViewShell title="PERFORMANCE" color="#ffd426" onClose={onClose} right={
      <span style={{ display: 'flex', gap: 6 }}>{(['LIVE', 'DEMO'] as const).map((m) => <button key={m} className={`btn sm ${mode === m ? '' : 'blue'}`} onClick={() => setMode(m)}>{m}</button>)}</span>}>
      {!p ? <Loading what="CRUNCHING RECORDED RESULTS" /> : (
        <div style={{ display: 'grid', gap: 12 }}>
          <Chip tone={mode === 'DEMO' ? 'demo' : 'good'}>{mode === 'DEMO' ? 'DEMO DATA — simulated, NOT real performance' : 'LIVE RECORDED SIGNALS'}</Chip>
          {p.total_signals === 0 && <Empty title={`NO ${mode} SIGNALS RECORDED`} hint="Statistics are computed only from signals and outcomes actually recorded in the database. Nothing is estimated or back-filled." />}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10 }}>
            <Stat label="Signals today" value={p.signals_today} />
            <Stat label="Signals this week" value={p.signals_this_week} />
            <Stat label="Winning signals" value={p.wins} tone={p.wins ? 'good' : undefined} />
            <Stat label="Losing signals" value={p.losses} tone={p.losses ? 'bad' : undefined} />
            <Stat label="Win rate" value={p.win_rate == null ? '—' : `${p.win_rate}%`} sub={p.closed ? `${p.closed} closed` : 'no closed signals'} />
            <Stat label="Average R:R" value={p.avg_rr == null ? '—' : `1:${p.avg_rr}`} />
            <Stat label="Average confidence" value={p.avg_confidence ?? '—'} />
            <Stat label="Profit factor" value={pf == null ? '—' : pf} sub={p.profit_factor_note ?? undefined} />
            <Stat label="Max drawdown" value={p.max_drawdown_r == null ? '—' : `${p.max_drawdown_r}R`} />
            <Stat label="Net result" value={p.closed ? `${p.net_r > 0 ? '+' : ''}${p.net_r}R` : '—'} tone={p.net_r > 0 ? 'good' : p.net_r < 0 ? 'bad' : undefined} />
            <Stat label="Best pair" value={p.best_pair?.pair ?? '—'} sub={p.best_pair ? `${num(p.best_pair.net_r)}R` : undefined} />
            <Stat label="Worst pair" value={p.worst_pair?.pair ?? '—'} sub={p.worst_pair ? `${num(p.worst_pair.net_r)}R` : undefined} />
          </div>
          <EquityCurve points={p.equity_curve} />
          <p style={{ fontSize: 12, opacity: 0.8, margin: 0 }}>{p.basis} Open signals: {p.open}. Past results do not predict future results. Educational analysis — not financial advice. Record outcomes in the Signals tab (or let the tracker update LIVE signals).</p>
        </div>)}
    </ViewShell>
  );
}
