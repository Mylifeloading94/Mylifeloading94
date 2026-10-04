import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { setStoreForTests } from '@/lib/database';
import { resetBus } from '@/lib/events/bus';
import { resetRuntime } from '@/lib/state';

/**
 * Integration test against a real PostgreSQL. Run with:
 *   TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/smc npm test
 * (the schema must already be applied: DATABASE_URL=... npm run db:push). Skipped otherwise.
 */
const url = process.env.TEST_DATABASE_URL;

describe.skipIf(!url)('PostgreSQL store (Prisma)', () => {
  let store: import('@/lib/database/prisma').PrismaStore;
  let db: any;
  beforeAll(async () => {
    process.env.DATABASE_URL = url;
    const { PrismaStore } = await import('@/lib/database/prisma');
    store = await PrismaStore.connect();
    db = (store as any).db;
    for (const t of ['signal', 'marketAnalysisRecord', 'newsEvent', 'agentActivity', 'setupScore', 'telegramMessage', 'setting']) await db[t].deleteMany();
    setStoreForTests(store); resetRuntime(); resetBus();
  });
  afterAll(async () => { await db?.$disconnect(); });

  it('runs the demo pipeline and persists signal, analysis, news, scores and activity', async () => {
    const { runDemoSignal } = await import('@/lib/pipeline');
    const r = await runDemoSignal({ pace: false });
    expect(r.signals[0].outcome).toBe('created');
    await new Promise((res) => setTimeout(res, 300)); // fire-and-forget log writes
    const c = await store.counts();
    expect(c.signals).toBe(1);
    expect(c.analyses).toBeGreaterThanOrEqual(1);
    expect(c.news).toBeGreaterThanOrEqual(1);
    expect(c.scores).toBeGreaterThanOrEqual(1);
    expect(c.activity).toBeGreaterThanOrEqual(4);
    const [s] = await store.listSignals({ mode: 'DEMO' });
    expect(s.signal_id).toMatch(/^DEMO-\d{4}-0001$/);
    expect(s.score_breakdown.market_structure).toBeGreaterThan(0);
    expect(Array.isArray(s.confirmations)).toBe(true);
    expect(typeof s.timestamp).toBe('string');
  });
  it('sequences signal ids, updates status/result, filters by mode', async () => {
    expect(await store.nextSignalId('DEMO', new Date().getUTCFullYear())).toMatch(/0002$/);
    expect(await store.nextSignalId('LIVE', 2026)).toBe('SMC-2026-0001');
    const [s] = await store.listSignals();
    const u = await store.updateSignal(s.signal_id, { status: 'TP2', result: 'TP2 +2R', result_r: 2, closed_at: new Date().toISOString() });
    expect(u).toMatchObject({ status: 'TP2', result_r: 2 });
    expect(await store.getSignal('NOPE')).toBeNull();
    expect(await store.listSignals({ mode: 'LIVE' })).toHaveLength(0);
    expect(await store.updateSignal('NOPE', { status: 'TP1' })).toBeNull();
  });
  it('round-trips settings and telegram log', async () => {
    const { DEFAULT_SETTINGS } = await import('@/types');
    await store.saveSettings({ ...DEFAULT_SETTINGS, risk_per_trade: 2, watchlist: ['EURUSD'] });
    expect(await store.getSettings()).toMatchObject({ risk_per_trade: 2, watchlist: ['EURUSD'] });
    await store.logTelegram({ ts: new Date().toISOString(), signal_id: 'x', direction: 'outbound', ok: true, message_id: 5, text: 'hi', error: null });
    expect((await store.recentTelegram(1))[0]).toMatchObject({ ok: true, message_id: 5 });
  });
});
