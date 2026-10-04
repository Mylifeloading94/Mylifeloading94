'use client';
import type { ReactNode } from 'react';

export const Chip = ({ children, tone }: { children: ReactNode; tone?: 'good' | 'bad' | 'warn' | 'info' | 'demo' }) => <span className={`chip ${tone ?? ''}`}>{children}</span>;

export const Stat = ({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: string; tone?: 'good' | 'bad' }) => (
  <div className="stat"><span>{label}</span><b style={{ color: tone === 'good' ? '#0a8a3a' : tone === 'bad' ? '#d11' : undefined }}>{value}</b>{sub && <small style={{ fontSize: 11, opacity: 0.7 }}>{sub}</small>}</div>
);

export const Empty = ({ title, hint }: { title: string; hint?: string }) => <div className="empty">{title}{hint && <small>{hint}</small>}</div>;

export const Json = ({ data }: { data: unknown }) => <pre className="json">{JSON.stringify(data, null, 2)}</pre>;

export function Loading({ what = 'LOADING' }: { what?: string }) { return <div className="empty">{what}…<small>hang tight</small></div>; }

export const trendTone = (t: string) => (t === 'bullish' || t === 'long' ? 'good' : t === 'bearish' || t === 'short' ? 'bad' : 'warn') as 'good' | 'bad' | 'warn';

export function ViewShell({ title, color, onClose, children, right, narrow }: { title: string; color: string; onClose: () => void; children: ReactNode; right?: ReactNode; narrow?: boolean }) {
  return (
    <section className="view cpanel" data-narrow={narrow ? '1' : undefined} style={{ ['--c' as any]: color }} aria-label={title}>
      <div className="cpanel-h"><span>{title}</span><span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{right}<button className="btn sm red" onClick={onClose} aria-label="Close panel">✕</button></span></div>
      <div className="body">{children}</div>
    </section>
  );
}

export const fmtTime = (iso: string | null | undefined) => (iso ? new Date(iso).toISOString().replace('T', ' ').slice(0, 16) + 'Z' : '—');
export const num = (n: number | null | undefined, d = 2) => (n == null ? '—' : n.toFixed(d));
