import { AGENT_IDS, AGENT_LABELS, type AgentId, type AgentSnapshot, type HunterReport, type MarketAnalysis, type NewsIntel, type Signal } from '@/types';

export interface Runtime {
  paused: boolean;
  agents: Record<AgentId, AgentSnapshot>;
  analyses: Record<string, MarketAnalysis>;
  news: NewsIntel | null;
  newsAt: number | null; // real wall-clock time the news report was produced
  hunter: HunterReport | null;
  lastSignal: Signal | null;
  lastScanAt: string | null;
  scanning: boolean;
  demoRuns: number;
  startedAt: string;
  unavailableReason: string | null;
}

const fresh = (): Runtime => ({
  paused: false,
  agents: Object.fromEntries(AGENT_IDS.map((id) => [id, {
    id, name: AGENT_LABELS[id], status: 'idle', last_run: null, last_duration_ms: null, summary: 'Standing by',
    error: null, runs: 0, failures: 0, logs: [],
  } satisfies AgentSnapshot])) as unknown as Record<AgentId, AgentSnapshot>,
  analyses: {}, news: null, newsAt: null, hunter: null, lastSignal: null, lastScanAt: null, scanning: false, demoRuns: 0,
  startedAt: new Date().toISOString(), unavailableReason: null,
});

const g = globalThis as unknown as { __smcRuntime?: Runtime };
export const runtime = (): Runtime => (g.__smcRuntime ??= fresh());
export const resetRuntime = () => { g.__smcRuntime = fresh(); };
