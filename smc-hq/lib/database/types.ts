import type { MarketAnalysis, NewsIntel, Settings, SetupEvaluation, Signal, DataMode, AgentLogEntry } from '@/types';

export interface TelegramRecord { ts: string; signal_id: string | null; direction: 'outbound' | 'inbound'; ok: boolean; message_id: number | null; text: string; error: string | null }
export interface ActivityRecord extends AgentLogEntry { agent: string }

export interface SignalFilter { mode?: DataMode; limit?: number; since?: string }

/** Everything the app persists. Two implementations: PostgreSQL (Prisma) and a JSON-file fallback. */
export interface Store {
  readonly kind: 'postgres' | 'file';
  nextSignalId(mode: DataMode, year: number): Promise<string>;
  insertSignal(s: Signal): Promise<Signal>;
  updateSignal(signalId: string, patch: Partial<Signal>): Promise<Signal | null>;
  getSignal(signalId: string): Promise<Signal | null>;
  listSignals(f?: SignalFilter): Promise<Signal[]>;
  logAnalysis(a: MarketAnalysis): Promise<void>;
  logNews(n: NewsIntel): Promise<void>;
  logActivity(r: ActivityRecord): Promise<void>;
  logScore(e: SetupEvaluation): Promise<void>;
  logTelegram(r: TelegramRecord): Promise<void>;
  recentActivity(limit: number): Promise<ActivityRecord[]>;
  recentTelegram(limit: number): Promise<TelegramRecord[]>;
  getSettings(): Promise<Settings>;
  saveSettings(s: Settings): Promise<void>;
  counts(): Promise<Record<string, number>>;
}
