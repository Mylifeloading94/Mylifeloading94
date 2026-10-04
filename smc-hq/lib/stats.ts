import type { DataMode, Signal } from '@/types';

export interface Performance {
  data_mode: DataMode;
  total_signals: number;
  signals_today: number;
  signals_this_week: number;
  open: number;
  closed: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  avg_rr: number | null;
  avg_confidence: number | null;
  profit_factor: number | null;
  profit_factor_note: string | null;
  max_drawdown_r: number | null;
  net_r: number;
  best_pair: { pair: string; net_r: number } | null;
  worst_pair: { pair: string; net_r: number } | null;
  equity_curve: { t: string; r: number }[];
  basis: string;
}

/** R multiple realised for a status, from the recorded levels. EXPIRED / CANCELLED are excluded from statistics. */
export function resultFor(s: Pick<Signal, 'entry' | 'stop_loss' | 'take_profit_1' | 'take_profit_2' | 'take_profit_3'>, status: Signal['status']): number | null {
  const risk = Math.abs(s.entry - s.stop_loss);
  if (risk === 0) return null;
  const r = (tp: number) => Number((Math.abs(tp - s.entry) / risk).toFixed(2));
  switch (status) {
    case 'TP1': return r(s.take_profit_1);
    case 'TP2': return r(s.take_profit_2);
    case 'TP3': return r(s.take_profit_3);
    case 'STOPPED': return -1;
    default: return null;
  }
}

const weekStart = (ts: number) => { const d = new Date(Math.floor(ts / 86_400_000) * 86_400_000); return d.getTime() - ((d.getUTCDay() + 6) % 7) * 86_400_000; };

/**
 * Everything here is computed from recorded signals/results of ONE data mode. Nothing is estimated, backfilled
 * or simulated; with no closed signals the ratios are null and the UI says so.
 */
export function computePerformance(all: Signal[], mode: DataMode, now = Date.now()): Performance {
  const sigs = all.filter((s) => s.data_mode === mode);
  const day = Math.floor(now / 86_400_000);
  const wk = weekStart(now);
  const closedSigs = sigs.filter((s) => s.result_r !== null && ['TP1', 'TP2', 'TP3', 'STOPPED'].includes(s.status))
    .sort((a, b) => (a.closed_at ?? a.timestamp).localeCompare(b.closed_at ?? b.timestamp));
  const wins = closedSigs.filter((s) => (s.result_r ?? 0) > 0);
  const losses = closedSigs.filter((s) => (s.result_r ?? 0) < 0);
  const grossWin = wins.reduce((a, s) => a + (s.result_r ?? 0), 0);
  const grossLoss = Math.abs(losses.reduce((a, s) => a + (s.result_r ?? 0), 0));
  const mean = (xs: number[]) => (xs.length ? Number((xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(2)) : null);

  let eq = 0, peak = 0, dd = 0;
  const curve = closedSigs.map((s) => { eq += s.result_r ?? 0; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq); return { t: s.closed_at ?? s.timestamp, r: Number(eq.toFixed(2)) }; });

  const byPair = new Map<string, number>();
  for (const s of closedSigs) byPair.set(s.pair, (byPair.get(s.pair) ?? 0) + (s.result_r ?? 0));
  const ranked = [...byPair.entries()].map(([pair, net_r]) => ({ pair, net_r: Number(net_r.toFixed(2)) })).sort((a, b) => b.net_r - a.net_r);

  let pf: number | null = null, note: string | null = null;
  if (closedSigs.length) {
    if (grossLoss === 0) note = 'No losing signals recorded yet';
    else pf = Number((grossWin / grossLoss).toFixed(2));
  }
  return {
    data_mode: mode,
    total_signals: sigs.length,
    signals_today: sigs.filter((s) => Math.floor(Date.parse(s.timestamp) / 86_400_000) === day).length,
    signals_this_week: sigs.filter((s) => Date.parse(s.timestamp) >= wk).length,
    open: sigs.filter((s) => s.status === 'PENDING' || s.status === 'ACTIVE').length,
    closed: closedSigs.length,
    wins: wins.length,
    losses: losses.length,
    win_rate: closedSigs.length ? Number(((wins.length / closedSigs.length) * 100).toFixed(1)) : null,
    avg_rr: mean(sigs.map((s) => s.risk_reward)),
    avg_confidence: mean(sigs.map((s) => s.confidence_score)),
    profit_factor: pf,
    profit_factor_note: note,
    max_drawdown_r: closedSigs.length ? Number(dd.toFixed(2)) : null,
    net_r: Number(eq.toFixed(2)),
    best_pair: ranked.length ? ranked[0] : null,
    worst_pair: ranked.length > 1 ? ranked[ranked.length - 1] : null,
    equity_curve: curve,
    basis: `Computed from ${closedSigs.length} closed ${mode} signal(s). R = multiple of initial risk; the highest target reached is assumed to be the exit.`,
  };
}
