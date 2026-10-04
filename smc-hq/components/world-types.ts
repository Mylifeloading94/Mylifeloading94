import type { AgentId, AgentSnapshot, BusEvent, HunterReport, MarketAnalysis, NewsIntel, Settings, Signal } from '@/types';

export interface Snapshot {
  mode: 'LIVE' | 'DEMO';
  paused: boolean;
  scanning: boolean;
  now: string;
  system: {
    market: { state: 'ONLINE' | 'DEMO' | 'STANDBY' | 'UNAVAILABLE'; detail: string };
    news: { state: 'ONLINE' | 'DEMO' | 'STANDBY' | 'UNAVAILABLE'; detail: string };
    agents: { online: number; total: number };
    telegram: { state: 'CONNECTED' | 'NOT_CONFIGURED' | 'ERROR'; detail: string };
    database: string;
  };
  agents: Record<AgentId, AgentSnapshot>;
  analyses: Record<string, MarketAnalysis>;
  news: NewsIntel | null;
  news_at: number | null;
  hunter: HunterReport | null;
  lastSignal: Signal | null;
  signals: Signal[];
  settings: Settings;
  last_scan_at: string | null;
  events: BusEvent[];
}

export type FxKind = 'pow' | 'bzzt' | 'kaching' | 'zap' | 'ping';
export interface Fx { id: string; text: string; kind: FxKind; at: number }
export interface Packet { id: string; from: 'hunter' | 'command'; to: 'command' | 'telegram'; at: number; label: string }

/** Ephemeral, event-driven state that only exists in the browser. */
export interface LiveState {
  speech: Partial<Record<AgentId, string>>;
  scanning: { pair: string; index: number; total: number; phase: string } | null;
  recentEvals: { pair: string; score: number; approved: boolean; ts: number }[];
  packets: Packet[];
  fx: Fx[];
  breakingAt: number;
  commandFlashAt: number;
  preview: { signal_id: string; text: string } | null;
  lastSent: { signal_id: string; ok: boolean; at: number } | null;
  stage: { analyst: boolean; news: boolean; hunter: boolean; command: boolean; telegram: boolean };
  running: boolean;
}

export const emptyLive = (): LiveState => ({
  speech: {}, scanning: null, recentEvals: [], packets: [], fx: [], breakingAt: 0, commandFlashAt: 0, preview: null, lastSent: null,
  stage: { analyst: false, news: false, hunter: false, command: false, telegram: false }, running: false,
});
