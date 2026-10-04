'use client';
import { Fragment, useState } from 'react';
import { MAX_POINTS } from '@/lib/scoring/score';
import { Chip, Empty, trendTone, ViewShell } from '../ui/Comic';
import type { Snapshot } from '../world-types';

const GRADE: Record<string, 'good' | 'info' | 'warn' | 'bad'> = { PREMIUM: 'good', VERY_HIGH: 'good', HIGH: 'info', STANDARD: 'warn', REJECTED: 'bad' };
const LABEL: Record<string, string> = { market_structure: 'Market structure', liquidity: 'Liquidity', fvg_ob: 'FVG / Order block', htf_alignment: 'HTF alignment', entry_confirmation: 'Entry confirmation', risk_reward: 'Risk / reward', session: 'Session', news: 'News environment', volatility: 'Volatility' };

export function SetupsView({ snap, onClose, onScan, scanning }: { snap: Snapshot | null; onClose: () => void; onScan: () => void; scanning: boolean }) {
  const h = snap?.hunter;
  const [open, setOpen] = useState<string | null>(null);
  const evals = [...(h?.evaluations ?? [])].sort((a, b) => b.confidence_score - a.confidence_score);
  return (
    <ViewShell title="SETUP HUNTER" color="#ff5a3b" onClose={onClose} right={<button className="btn sm" onClick={onScan} disabled={scanning}>{scanning ? 'SCANNING…' : 'SCAN NOW'}</button>}>
      {!h ? <Empty title="NO SCAN YET" hint="The Hunter scores every pair on a transparent 100-point rubric and rejects anything below your minimum confidence." /> : (
        <div style={{ display: 'grid', gap: 12 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <Chip tone={h.data_mode === 'DEMO' ? 'demo' : 'good'}>{h.data_mode === 'DEMO' ? 'DEMO DATA' : 'LIVE'}</Chip>
            <Chip>{h.scanned} scanned</Chip><Chip tone="good">{h.approved.length} approved</Chip><Chip tone="bad">{h.rejected_count} rejected</Chip>
            <Chip tone="info">min confidence {snap?.settings.min_confidence} · min R:R 1:{snap?.settings.min_rr}</Chip>
            {h.unavailable.length > 0 && <Chip tone="bad">MARKET DATA UNAVAILABLE: {h.unavailable.join(', ')}</Chip>}
          </div>
          <p style={{ margin: 0, fontSize: 12, opacity: 0.8 }}>The confidence score measures how many rule-based conditions are satisfied right now. It is <b>not</b> a probability of winning and does not guarantee any outcome.</p>
          <table className="tbl">
            <thead><tr><th>PAIR</th><th>SCORE</th><th>GRADE</th><th>DIR</th><th>RESULT</th><th>WHY</th></tr></thead>
            <tbody>
              {evals.map((e) => (
                <Fragment key={e.pair}>
                  <tr onClick={() => setOpen(open === e.pair ? null : e.pair)} style={{ cursor: 'pointer' }}>
                    <td><b>{e.pair}</b></td>
                    <td style={{ minWidth: 120 }}><div className="bar"><i style={{ width: `${e.confidence_score}%`, background: e.confidence_score >= 90 ? '#2bff88' : e.confidence_score >= 80 ? '#ffd426' : '#ff3b3b' }} /></div>{e.confidence_score}/100</td>
                    <td><Chip tone={GRADE[e.grade]}>{e.grade.replace('_', ' ')}</Chip></td>
                    <td>{e.direction ? <Chip tone={trendTone(e.direction)}>{e.direction.toUpperCase()}</Chip> : '—'}</td>
                    <td><Chip tone={e.approved ? 'good' : 'bad'}>{e.approved ? 'APPROVED' : 'REJECTED'}</Chip></td>
                    <td style={{ fontSize: 12 }}>{e.approved ? (e.warnings[0] ?? 'All checks passed') : (e.rejection_reasons[0] ?? '—')}</td>
                  </tr>
                  {open === e.pair && (
                    <tr><td colSpan={6} style={{ background: 'rgba(0,0,0,.05)' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 16 }}>
                        <div><b>Score breakdown</b>
                          {Object.entries(e.score_breakdown).map(([k, v]) => <div key={k} style={{ fontSize: 12 }}>{LABEL[k]}: <b>{v}</b> / {(MAX_POINTS as any)[k]}<div className="bar" style={{ height: 8 }}><i style={{ width: `${(v / (MAX_POINTS as any)[k]) * 100}%` }} /></div></div>)}</div>
                        <div><b>Validation</b>{e.checks.map((c) => <div key={c.id} style={{ fontSize: 12 }}>{c.passed ? '✅' : '❌'} <b>{c.label}</b> — {c.detail}</div>)}
                          {e.warnings.map((w) => <div key={w} style={{ fontSize: 12, color: '#a56300' }}>⚠ {w}</div>)}</div>
                      </div></td></tr>)}
                </Fragment>))}
            </tbody>
          </table>
        </div>)}
    </ViewShell>
  );
}
