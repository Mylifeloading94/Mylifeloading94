'use client';
import { useEffect, useState } from 'react';
import { Chip, Empty, fmtTime, ViewShell } from '../ui/Comic';
import type { Snapshot } from '../world-types';

const tone = (i: string) => (i === 'EXTREME' || i === 'HIGH' ? 'bad' : i === 'MEDIUM' ? 'warn' : 'info') as 'bad' | 'warn' | 'info';

export function NewsView({ snap, onClose, onScan, scanning }: { snap: Snapshot | null; onClose: () => void; onScan: () => void; scanning: boolean }) {
  const n = snap?.news;
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const cd = n?.countdown_seconds != null && snap?.news_at ? Math.max(0, n.countdown_seconds - (now - snap.news_at) / 1000) : null;
  const risky = n ? Object.entries(n.pair_risk).filter(([, r]) => r.level !== 'low') : [];
  return (
    <ViewShell title="NEWS INTELLIGENCE" color="#ff4fd8" onClose={onClose} right={<button className="btn sm" onClick={onScan} disabled={scanning}>{scanning ? 'SCANNING…' : 'REFRESH'}</button>}>
      {!n ? <Empty title="NO NEWS REPORT YET" hint={snap?.mode === 'LIVE' && snap.system.news.state === 'UNAVAILABLE' ? 'News feed unavailable — set NEWS_API_KEY (and X_API_KEY for social). Without it, news risk is reported as UNKNOWN.' : 'Run a scan to pull headlines, scheduled events and per-pair news risk.'} /> : (
        <div style={{ display: 'grid', gap: 14 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Chip tone={n.data_mode === 'DEMO' ? 'demo' : 'good'}>{n.data_mode === 'DEMO' ? 'DEMO DATA' : 'LIVE FEED'}</Chip>
            {!n.available && <Chip tone="bad">FEED UNAVAILABLE</Chip>}
            {!n.calendar_available && <Chip tone="warn">NO ECONOMIC CALENDAR — add events in Settings</Chip>}
            <Chip tone="info">SENTIMENT (headline tone): {n.sentiment.label.replace('_', '-').toUpperCase()}</Chip>
            <span style={{ fontSize: 13 }}>{n.summary}</span>
          </div>
          <div className="stat">
            <span>NEXT KEY EVENT</span>
            <b>{n.next_event ? `${n.next_event.currency} · ${n.next_event.title}` : 'None scheduled'}</b>
            {n.next_event && <small>{fmtTime(n.next_event.time)} · {n.next_event.impact} · countdown {cd != null ? `${Math.floor(cd / 3600)}h ${Math.floor((cd % 3600) / 60)}m ${Math.floor(cd % 60)}s` : '—'} · affects {n.next_event.affected_assets.join(', ') || '—'}</small>}
          </div>
          {risky.length > 0 && <div><b className="font-comic" style={{ fontSize: 20 }}>PAIRS WITH NEWS RISK</b>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>{risky.map(([p, r]) => <Chip key={p} tone={r.blackout ? 'bad' : r.level === 'unknown' ? 'warn' : tone(r.level.toUpperCase())}>{p}: {r.blackout ? 'BLACKOUT' : r.level.toUpperCase()}</Chip>)}</div></div>}
          <div>
            <b className="font-comic" style={{ fontSize: 20 }}>UPCOMING EVENTS</b>
            {n.upcoming_events.length ? <table className="tbl"><thead><tr><th>TIME</th><th>EVENT</th><th>CCY</th><th>IMPACT</th><th>AFFECTS</th></tr></thead><tbody>
              {n.upcoming_events.map((e) => <tr key={e.id}><td>{fmtTime(e.time)}</td><td>{e.title}{e.manual && <Chip>manual</Chip>}</td><td>{e.currency}</td><td><Chip tone={tone(e.impact)}>{e.impact}</Chip></td><td style={{ fontSize: 12 }}>{e.affected_assets.join(' ')}</td></tr>)}</tbody></table> : <Empty title="NO SCHEDULED EVENTS" />}
          </div>
          <div>
            <b className="font-comic" style={{ fontSize: 20 }}>HEADLINES & SOCIAL</b>
            {n.items.length ? <table className="tbl"><thead><tr><th>TIME</th><th>HEADLINE</th><th>IMPACT</th><th>CCY</th></tr></thead><tbody>
              {n.items.slice(0, 25).map((i) => <tr key={i.id}><td style={{ whiteSpace: 'nowrap' }}>{fmtTime(i.published_at).slice(11)}</td>
                <td>{i.channel === 'social' && <Chip tone="info">X</Chip>} {i.headline}<div style={{ fontSize: 11, opacity: 0.7 }}>{i.source} · {i.potential_effect}</div></td>
                <td><Chip tone={tone(i.impact)}>{i.impact}</Chip></td><td>{i.currencies.join('/') || '—'}</td></tr>)}</tbody></table> : <Empty title="NO HEADLINES" />}
          </div>
        </div>)}
    </ViewShell>
  );
}
