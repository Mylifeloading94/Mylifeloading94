import { DEFAULT_SETTINGS, type DataMode, type MarketAnalysis, type NewsIntel, type Settings, type SetupEvaluation, type Signal } from '@/types';
import type { ActivityRecord, SignalFilter, Store, TelegramRecord } from './types';

/* eslint-disable @typescript-eslint/no-explicit-any */
const toSignal = (r: any): Signal => ({
  id: r.id, signal_id: r.signalId, data_mode: r.dataMode, pair: r.pair, direction: r.direction, entry: r.entry,
  entry_low: r.entryLow, entry_high: r.entryHigh, stop_loss: r.stopLoss, take_profit_1: r.takeProfit1,
  take_profit_2: r.takeProfit2, take_profit_3: r.takeProfit3, confidence_score: r.confidenceScore, grade: r.grade,
  risk_reward: r.riskReward, setup_type: r.setupType, session: r.session, news_risk: r.newsRisk,
  confirmations: r.confirmations, score_breakdown: r.scoreBreakdown, technical_reasoning: r.technicalReasoning,
  news_reasoning: r.newsReasoning, fingerprint: r.fingerprint, timestamp: r.timestamp.toISOString(), status: r.status,
  result: r.result, result_r: r.resultR, closed_at: r.closedAt ? r.closedAt.toISOString() : null,
  telegram_state: r.telegramState, telegram_message_id: r.telegramMessageId,
});
const fromSignal = (s: Partial<Signal>) => {
  const m: Record<string, any> = {
    id: s.id, signalId: s.signal_id, dataMode: s.data_mode, pair: s.pair, direction: s.direction, entry: s.entry,
    entryLow: s.entry_low, entryHigh: s.entry_high, stopLoss: s.stop_loss, takeProfit1: s.take_profit_1,
    takeProfit2: s.take_profit_2, takeProfit3: s.take_profit_3, confidenceScore: s.confidence_score, grade: s.grade,
    riskReward: s.risk_reward, setupType: s.setup_type, session: s.session, newsRisk: s.news_risk,
    confirmations: s.confirmations, scoreBreakdown: s.score_breakdown, technicalReasoning: s.technical_reasoning,
    newsReasoning: s.news_reasoning, fingerprint: s.fingerprint, timestamp: s.timestamp ? new Date(s.timestamp) : undefined,
    status: s.status, result: s.result, resultR: s.result_r, closedAt: s.closed_at ? new Date(s.closed_at) : s.closed_at === null ? null : undefined,
    telegramState: s.telegram_state, telegramMessageId: s.telegram_message_id,
  };
  for (const k of Object.keys(m)) if (m[k] === undefined) delete m[k];
  return m;
};

/** PostgreSQL implementation (Prisma). Requires `npm run db:generate` and `npm run db:push`. */
export class PrismaStore implements Store {
  readonly kind = 'postgres' as const;
  constructor(private db: any) {}

  static async connect(): Promise<PrismaStore> {
    const mod: any = await import('@prisma/client');
    const db = new mod.PrismaClient();
    await db.$connect();
    return new PrismaStore(db);
  }

  async nextSignalId(mode: DataMode, year: number) {
    const prefix = `${mode === 'DEMO' ? 'DEMO' : 'SMC'}-${year}-`;
    const last = await this.db.signal.findFirst({ where: { signalId: { startsWith: prefix } }, orderBy: { signalId: 'desc' } });
    const n = last ? Number(String(last.signalId).slice(prefix.length)) || 0 : 0;
    return `${prefix}${String(n + 1).padStart(4, '0')}`;
  }
  async insertSignal(s: Signal) { return toSignal(await this.db.signal.create({ data: { ...fromSignal(s), id: undefined } })); }
  async updateSignal(signalId: string, patch: Partial<Signal>) {
    try { return toSignal(await this.db.signal.update({ where: { signalId }, data: { ...fromSignal(patch), id: undefined, signalId: undefined } })); }
    catch { return null; }
  }
  async getSignal(signalId: string) { const r = await this.db.signal.findUnique({ where: { signalId } }); return r ? toSignal(r) : null; }
  async listSignals(f: SignalFilter = {}) {
    const rows = await this.db.signal.findMany({
      where: { ...(f.mode ? { dataMode: f.mode } : {}), ...(f.since ? { timestamp: { gte: new Date(f.since) } } : {}) },
      orderBy: { timestamp: 'desc' }, take: f.limit,
    });
    return rows.map(toSignal);
  }
  async logAnalysis(a: MarketAnalysis) { await this.db.marketAnalysisRecord.create({ data: { pair: a.pair, dataMode: a.data_mode, bias: a.htf_bias, payload: a as any } }); }
  async logNews(n: NewsIntel) {
    await this.db.newsEvent.createMany({ data: n.items.slice(0, 20).map((i) => ({ dataMode: n.data_mode, headline: i.headline, impact: i.impact, currency: i.currencies.join(','), payload: i as any })) });
  }
  async logActivity(r: ActivityRecord) { await this.db.agentActivity.create({ data: { agent: r.agent, level: r.level, message: r.message, createdAt: new Date(r.ts) } }); }
  async logScore(e: SetupEvaluation) { await this.db.setupScore.create({ data: { pair: e.pair, dataMode: e.data_mode, score: e.confidence_score, grade: e.grade, approved: e.approved, payload: e as any } }); }
  async logTelegram(r: TelegramRecord) { await this.db.telegramMessage.create({ data: { signalId: r.signal_id, direction: r.direction, ok: r.ok, messageId: r.message_id, text: r.text, error: r.error, createdAt: new Date(r.ts) } }); }
  async recentActivity(limit: number): Promise<ActivityRecord[]> {
    const rows = await this.db.agentActivity.findMany({ orderBy: { createdAt: 'desc' }, take: limit });
    return rows.map((r: any) => ({ agent: r.agent, level: r.level, message: r.message, ts: r.createdAt.toISOString() }));
  }
  async recentTelegram(limit: number): Promise<TelegramRecord[]> {
    const rows = await this.db.telegramMessage.findMany({ orderBy: { createdAt: 'desc' }, take: limit });
    return rows.map((r: any) => ({ ts: r.createdAt.toISOString(), signal_id: r.signalId, direction: r.direction, ok: r.ok, message_id: r.messageId, text: r.text, error: r.error }));
  }
  async getSettings(): Promise<Settings> {
    const r = await this.db.setting.findUnique({ where: { key: 'settings' } });
    return { ...DEFAULT_SETTINGS, ...(r?.value ?? {}) };
  }
  async saveSettings(s: Settings) { await this.db.setting.upsert({ where: { key: 'settings' }, update: { value: s as any }, create: { key: 'settings', value: s as any } }); }
  async counts() {
    const [signals, analyses, news, activity, scores, telegram] = await Promise.all([
      this.db.signal.count(), this.db.marketAnalysisRecord.count(), this.db.newsEvent.count(),
      this.db.agentActivity.count(), this.db.setupScore.count(), this.db.telegramMessage.count(),
    ]);
    return { signals, analyses, news, activity, scores, telegram };
  }
}
