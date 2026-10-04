import fs from 'node:fs';
import path from 'node:path';
import { DEFAULT_SETTINGS, type DataMode, type MarketAnalysis, type NewsIntel, type Settings, type SetupEvaluation, type Signal } from '@/types';
import type { ActivityRecord, SignalFilter, Store, TelegramRecord } from './types';

interface Data {
  signals: Signal[];
  analyses: { ts: string; data: MarketAnalysis }[];
  news: { ts: string; data: NewsIntel }[];
  activity: ActivityRecord[];
  scores: { ts: string; data: SetupEvaluation }[];
  telegram: TelegramRecord[];
  settings: Settings;
}
const CAP = 500;
const empty = (): Data => ({ signals: [], analyses: [], news: [], activity: [], scores: [], telegram: [], settings: { ...DEFAULT_SETTINGS } });

/** Zero-setup fallback so `npm install && npm run dev` works with no database. Single-process only. */
export class FileStore implements Store {
  readonly kind = 'file' as const;
  private data: Data;
  private file: string;
  private writing: Promise<void> = Promise.resolve();

  constructor(dir: string, filename = 'store.json') {
    fs.mkdirSync(dir, { recursive: true });
    this.file = path.join(dir, filename);
    this.data = empty();
    if (fs.existsSync(this.file)) {
      try { this.data = { ...empty(), ...JSON.parse(fs.readFileSync(this.file, 'utf8')) }; }
      catch { fs.copyFileSync(this.file, `${this.file}.corrupt-${Date.now()}`); }
    }
  }

  private persist() {
    const snapshot = JSON.stringify(this.data);
    this.writing = this.writing.then(async () => {
      const tmp = `${this.file}.tmp`;
      await fs.promises.writeFile(tmp, snapshot);
      await fs.promises.rename(tmp, this.file);
    }).catch(() => undefined);
    return this.writing;
  }
  private push<T>(arr: T[], item: T) { arr.push(item); if (arr.length > CAP) arr.splice(0, arr.length - CAP); }

  async nextSignalId(mode: DataMode, year: number) {
    const prefix = `${mode === 'DEMO' ? 'DEMO' : 'SMC'}-${year}-`;
    const max = this.data.signals.filter((s) => s.signal_id.startsWith(prefix)).reduce((m, s) => Math.max(m, Number(s.signal_id.slice(prefix.length)) || 0), 0);
    return `${prefix}${String(max + 1).padStart(4, '0')}`;
  }
  async insertSignal(s: Signal) { this.data.signals.push(s); await this.persist(); return s; }
  async updateSignal(signalId: string, patch: Partial<Signal>) {
    const s = this.data.signals.find((x) => x.signal_id === signalId);
    if (!s) return null;
    Object.assign(s, patch);
    await this.persist();
    return s;
  }
  async getSignal(signalId: string) { return this.data.signals.find((x) => x.signal_id === signalId) ?? null; }
  async listSignals(f: SignalFilter = {}) {
    let out = [...this.data.signals];
    if (f.mode) out = out.filter((s) => s.data_mode === f.mode);
    if (f.since) out = out.filter((s) => s.timestamp >= f.since!);
    out.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    return f.limit ? out.slice(0, f.limit) : out;
  }
  async logAnalysis(a: MarketAnalysis) { this.push(this.data.analyses, { ts: a.timestamp, data: a }); this.persist(); }
  async logNews(n: NewsIntel) { this.push(this.data.news, { ts: n.timestamp, data: n }); this.persist(); }
  async logActivity(r: ActivityRecord) { this.push(this.data.activity, r); this.persist(); }
  async logScore(e: SetupEvaluation) { this.push(this.data.scores, { ts: e.timestamp, data: e }); this.persist(); }
  async logTelegram(r: TelegramRecord) { this.push(this.data.telegram, r); this.persist(); }
  async recentActivity(limit: number) { return this.data.activity.slice(-limit).reverse(); }
  async recentTelegram(limit: number) { return this.data.telegram.slice(-limit).reverse(); }
  async getSettings() { return { ...DEFAULT_SETTINGS, ...this.data.settings }; }
  async saveSettings(s: Settings) { this.data.settings = s; await this.persist(); }
  async counts() {
    return { signals: this.data.signals.length, analyses: this.data.analyses.length, news: this.data.news.length, activity: this.data.activity.length, scores: this.data.scores.length, telegram: this.data.telegram.length };
  }
  /** Await pending writes (tests / shutdown). */
  async flush() { await this.writing; }
}
