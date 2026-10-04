import fs from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { freshEnv } from './helpers';
import { DemoMarketProvider, demoAnchor } from '@/lib/market';
import { MarketAnalystAgent } from '@/lib/agents/marketAnalyst';
import { SetupHunterAgent } from '@/lib/agents/setupHunter';
import { SignalCommandAgent } from '@/lib/agents/signalCommand';
import { gradeOf, riskReward, scoreSetup, validateSetup, MAX_POINTS } from '@/lib/scoring/score';
import { checkSignalLimits, findDuplicate } from '@/lib/risk/limits';
import { loadSettings, updateSettings } from '@/lib/risk/settings';
import { formatSignalMessage, sendTelegramSignal, BotApiTelegramProvider } from '@/lib/telegram';
import { handleCommand } from '@/lib/telegram/commands';
import { computePerformance, resultFor } from '@/lib/stats';
import { evaluateSignal } from '@/lib/tracker';
import { runtime } from '@/lib/state';
import { classifyImpact, detectCurrencies, pairRisk } from '@/lib/news/classify';
import { ApprovedSetupSchema, DEFAULT_SETTINGS, MarketAnalysisSchema, type MarketAnalysis, type Signal } from '@/types';

async function analysis(pair = 'XAUUSD'): Promise<MarketAnalysis> {
  const p = new DemoMarketProvider({ anchor: demoAnchor() });
  const r = await new MarketAnalystAgent(p, { retryDelayMs: 0 }).run({ pair });
  return r.output!;
}
const calm = { level: 'low' as const, blackout: false, reason: 'none' };

describe('confidence scoring', () => {
  beforeEach(() => { freshEnv(); });
  it('weights sum to exactly 100', () => {
    expect(Object.values(MAX_POINTS).reduce((a, b) => a + b, 0)).toBe(100);
  });
  it('scores the demo setup within bounds and never exceeds component maxima', async () => {
    const a = await analysis();
    const s = scoreSetup(a, calm);
    for (const [k, v] of Object.entries(s.breakdown)) expect(v).toBeLessThanOrEqual((MAX_POINTS as any)[k]);
    expect(s.total).toBeGreaterThanOrEqual(80);
    expect(s.total).toBeLessThanOrEqual(100);
  });
  it('grades by threshold: 90 premium, 85 very high, 80 high, below minimum rejected', () => {
    expect([gradeOf(91, 80), gradeOf(86, 80), gradeOf(81, 80), gradeOf(79, 80), gradeOf(75, 70)]).toEqual(['PREMIUM', 'VERY_HIGH', 'HIGH', 'REJECTED', 'STANDARD']);
  });
  it('scores 0 and explains when there is no entry model (indicator agreement alone is not enough)', async () => {
    const a = await analysis();
    const none = { ...a, candidate: null };
    const s = scoreSetup(none, calm);
    expect(s.total).toBe(0);
    expect(validateSetup(none, calm, DEFAULT_SETTINGS, 0)[0].passed).toBe(false);
  });
  it('downgrades with news risk and rejects inside a blackout', async () => {
    const a = await analysis();
    const base = scoreSetup(a, calm).total;
    const unknown = scoreSetup(a, { level: 'unknown', blackout: false, reason: 'x' }).total;
    expect(unknown).toBeLessThan(base);
    const checks = validateSetup(a, { level: 'high', blackout: true, reason: 'CPI in 10m' }, DEFAULT_SETTINGS, riskReward(a));
    expect(checks.find((c) => c.id === 'news')!.passed).toBe(false);
  });
  it('rejects poor risk/reward and extreme volatility', async () => {
    const a = await analysis();
    const rrFail = validateSetup(a, calm, { ...DEFAULT_SETTINGS, min_rr: 9 }, riskReward(a));
    expect(rrFail.find((c) => c.id === 'rr')!.passed).toBe(false);
    const vol = validateSetup({ ...a, volatility: { ...a.volatility, regime: 'extreme' } }, calm, DEFAULT_SETTINGS, riskReward(a));
    expect(vol.find((c) => c.id === 'volatility')!.passed).toBe(false);
  });
  it('requires an entry trigger: price merely "approaching" is not approved', async () => {
    const a = await analysis();
    const approaching = { ...a, candidate: { ...a.candidate!, entry_state: 'approaching' as const } };
    const hunter = new SetupHunterAgent();
    const ev = hunter.evaluate(approaching, null, DEFAULT_SETTINGS);
    expect(ev.approved).toBe(false);
  });
  it('agent output obeys its schema (analysis + approved setup)', async () => {
    const a = await analysis();
    expect(MarketAnalysisSchema.safeParse(a).success).toBe(true);
    const ev = new SetupHunterAgent().evaluate(a, null, { ...DEFAULT_SETTINGS });
    if (ev.setup) expect(ApprovedSetupSchema.safeParse(ev.setup).success).toBe(true);
  });
});

describe('risk management', () => {
  const sig = (o: Partial<Signal>): Signal => ({ id: '', signal_id: 'SMC-2026-0001', data_mode: 'LIVE', pair: 'EURUSD', direction: 'long', entry: 1, entry_low: 1, entry_high: 1.01, stop_loss: 0.9, take_profit_1: 1.1, take_profit_2: 1.2, take_profit_3: 1.3, confidence_score: 85, grade: 'HIGH', risk_reward: 2, setup_type: 'x', session: 'LONDON', news_risk: 'low', confirmations: [], score_breakdown: {} as any, technical_reasoning: '', news_reasoning: '', fingerprint: 'f', timestamp: new Date().toISOString(), status: 'PENDING', result: null, result_r: null, closed_at: null, telegram_state: 'SENT', telegram_message_id: 1, ...o });
  it('enforces the daily and simultaneous limits for LIVE signals only', () => {
    const now = Date.now();
    const three = [sig({ signal_id: 'a' }), sig({ signal_id: 'b' }), sig({ signal_id: 'c' })];
    expect(checkSignalLimits(DEFAULT_SETTINGS, three, now).allowed).toBe(false);
    expect(checkSignalLimits(DEFAULT_SETTINGS, three.map((s) => ({ ...s, data_mode: 'DEMO' as const })), now).allowed).toBe(true);
    const closed = three.map((s) => ({ ...s, status: 'STOPPED' as const, timestamp: new Date(now - 2 * 86_400_000).toISOString() }));
    expect(checkSignalLimits(DEFAULT_SETTINGS, closed, now).allowed).toBe(true);
    const open = [sig({ signal_id: 'a', timestamp: new Date(now - 2 * 86_400_000).toISOString() }), sig({ signal_id: 'b', timestamp: new Date(now - 2 * 86_400_000).toISOString() }), sig({ signal_id: 'c', timestamp: new Date(now - 2 * 86_400_000).toISOString() })];
    expect(checkSignalLimits(DEFAULT_SETTINGS, open, now).reason).toMatch(/Simultaneous/);
  });
  it('detects duplicate fingerprints and an open LIVE signal on the same pair+direction', () => {
    expect(findDuplicate([sig({})], 'f', 'GBPUSD', 'short', 'LIVE')).toBeDefined();
    expect(findDuplicate([sig({ fingerprint: 'zz' })], 'f', 'EURUSD', 'long', 'LIVE')).toBeDefined();
    expect(findDuplicate([sig({ fingerprint: 'zz', status: 'STOPPED' })], 'f', 'EURUSD', 'long', 'LIVE')).toBeUndefined();
  });
  it('validates and persists user settings; rejects invalid values', async () => {
    freshEnv();
    const ok = await updateSettings({ risk_per_trade: 1, min_rr: 2.5, news_blackout_minutes: 60, watchlist: ['EURUSD', 'EURGBP'] });
    expect(ok.ok).toBe(true);
    expect((await loadSettings()).watchlist).toEqual(['EURUSD', 'EURGBP']);
    expect((await updateSettings({ risk_per_trade: 3 })).ok).toBe(false);
    expect((await updateSettings({ watchlist: ['eur'] })).ok).toBe(false);
    expect((await updateSettings({ min_confidence: 20 })).ok).toBe(false);
  });
  it('Signal Command independently rejects a setup with a bad stop or sub-minimum R:R', async () => {
    const env = freshEnv();
    void env;
    const a = await analysis();
    const ev = new SetupHunterAgent().evaluate(a, null, DEFAULT_SETTINGS);
    const setup = ev.setup!;
    expect(SignalCommandAgent.sanity(setup, DEFAULT_SETTINGS)).toBeNull();
    expect(SignalCommandAgent.sanity({ ...setup, stop_loss: setup.entry_zone.high + 1 }, DEFAULT_SETTINGS)).toMatch(/wrong side/);
    expect(SignalCommandAgent.sanity(setup, { ...DEFAULT_SETTINGS, min_rr: 10 })).toMatch(/R:R/);
  });
});

describe('telegram', () => {
  const signal = (mode: 'LIVE' | 'DEMO'): Signal => ({ id: '1', signal_id: mode === 'LIVE' ? 'SMC-2026-0001' : 'DEMO-2026-0001', data_mode: mode, pair: 'XAUUSD', direction: 'long', entry: 3342.5, entry_low: 3340, entry_high: 3345, stop_loss: 3332, take_profit_1: 3355, take_profit_2: 3365, take_profit_3: 3380, confidence_score: 91, grade: 'PREMIUM', risk_reward: 3.8, setup_type: 'Liquidity Sweep + MSS + FVG', session: 'NEW YORK', news_risk: 'low', confirmations: ['H4 bullish structure', 'Strong R:R'], score_breakdown: {} as any, technical_reasoning: '', news_reasoning: '', fingerprint: 'f', timestamp: new Date().toISOString(), status: 'PENDING', result: null, result_r: null, closed_at: null, telegram_state: 'NOT_SENT', telegram_message_id: null });
  beforeEach(() => { freshEnv(); });

  it('formats the message exactly like the specification', () => {
    const t = formatSignalMessage(signal('LIVE'));
    for (const part of ['🔥 SMC TRADING SIGNAL', '📊 PAIR:\nXAUUSD', '🧠 BIAS:\nBULLISH', '🎯 ENTRY:\n3340.00 - 3345.00', '🛑 STOP LOSS:\n3332.00', '✅ TAKE PROFIT 1:\n3355.00', '🚀 TAKE PROFIT 3:\n3380.00', '⚖️ RISK / REWARD:\n1 : 3.8', '📈 CONFIDENCE SCORE:\n91 / 100', '🕐 SESSION:\nNEW YORK', '📰 NEWS RISK:\nLOW', '✓ H4 bullish structure', 'not financial advice', 'Signal ID:\nSMC-2026-0001']) expect(t).toContain(part);
  });
  it('sendTelegramSignal posts to the Bot API with the token only in the URL, and logs the message', async () => {
    const calls: any[] = [];
    const fetchMock = vi.fn(async (url: any, init: any) => { calls.push([String(url), JSON.parse(init.body)]); return { json: async () => ({ ok: true, result: { message_id: 42 } }) } as any; });
    const tg = new BotApiTelegramProvider('TOKEN123', '-100', fetchMock as any);
    const r = await sendTelegramSignal(signal('LIVE'), tg);
    expect(r).toEqual({ ok: true, messageId: 42 });
    expect(calls[0][0]).toBe('https://api.telegram.org/botTOKEN123/sendMessage');
    expect(calls[0][1].chat_id).toBe('-100');
    expect(calls[0][1].text).toContain('SMC-2026-0001');
  });
  it('refuses to send demo signals and reports API errors without leaking the token', async () => {
    const tg = new BotApiTelegramProvider('TOKEN123', '-100', (async () => { throw new Error('connect ECONNREFUSED https://api.telegram.org/botTOKEN123/sendMessage'); }) as any);
    expect((await sendTelegramSignal(signal('DEMO'), tg)).ok).toBe(false);
    const r = await sendTelegramSignal(signal('LIVE'), tg);
    expect(r.ok).toBe(false);
    expect(JSON.stringify(r)).not.toContain('TOKEN123');
    const bad = new BotApiTelegramProvider('T', 'C', (async () => ({ json: async () => ({ ok: false, description: 'chat not found' }) })) as any);
    expect(await bad.sendMessage('x')).toEqual({ ok: false, error: 'chat not found' });
  });
  it('commands: only the configured chat may use them; /pause and /resume toggle the runtime', async () => {
    process.env.TELEGRAM_CHAT_ID = '777';
    expect(await handleCommand('/status', 123)).toBeNull();
    expect(await handleCommand('/pause', 123)).toBeNull();
    expect(runtime().paused).toBe(false);
    expect(await handleCommand('/pause', 777)).toMatch(/paused/i);
    expect(runtime().paused).toBe(true);
    expect(await handleCommand('/status@MyBot', '777')).toMatch(/PAUSED/);
    expect(await handleCommand('/resume', 777)).toMatch(/resumed/i);
    expect(runtime().paused).toBe(false);
    expect(await handleCommand('/pairs', 777)).toContain('XAUUSD');
    expect(await handleCommand('/signals', 777)).toMatch(/No live signals/);
    expect(await handleCommand('/lastsignal', 777)).toMatch(/No live signals/);
    expect(await handleCommand('/nonsense', 777)).toMatch(/Unknown command/);
    delete process.env.TELEGRAM_CHAT_ID;
  });
  it('LIVE pipeline path: records the signal first, sends once, stores the Telegram message id', async () => {
    const { store } = freshEnv();
    process.env.TELEGRAM_CHAT_ID = '1';
    const a = await analysis();
    const setup = { ...new SetupHunterAgent().evaluate(a, null, DEFAULT_SETTINGS).setup!, data_mode: 'LIVE' as const };
    const tg = { name: 'm', isConfigured: () => true, sendMessage: vi.fn(async () => ({ ok: true, messageId: 9 })), getMe: async () => ({ ok: true }) };
    const cmd = new SignalCommandAgent(tg, () => Date.now(), { retryDelayMs: 0 });
    const r = await cmd.run({ setup, settings: DEFAULT_SETTINGS, send_telegram: true });
    expect(r.output!.outcome).toBe('created');
    expect(r.output!.signal!.signal_id).toMatch(/^SMC-\d{4}-0001$/);
    expect(tg.sendMessage).toHaveBeenCalledTimes(1);
    const stored = await store.getSignal(r.output!.signal!.signal_id);
    expect(stored).toMatchObject({ telegram_state: 'SENT', telegram_message_id: 9, status: 'PENDING', data_mode: 'LIVE' });
    // same setup again → duplicate, no second message
    const again = await cmd.run({ setup, settings: DEFAULT_SETTINGS, send_telegram: true });
    expect(again.output!.outcome).toBe('duplicate');
    expect(tg.sendMessage).toHaveBeenCalledTimes(1);
    delete process.env.TELEGRAM_CHAT_ID;
  });
  it('a Telegram outage never loses the signal', async () => {
    const { store } = freshEnv();
    const a = await analysis();
    const setup = { ...new SetupHunterAgent().evaluate(a, null, DEFAULT_SETTINGS).setup!, data_mode: 'LIVE' as const };
    const tg = { name: 'm', isConfigured: () => true, sendMessage: async () => ({ ok: false, error: 'boom' }), getMe: async () => ({ ok: false }) };
    const r = await new SignalCommandAgent(tg, () => Date.now(), { retryDelayMs: 0 }).run({ setup, settings: DEFAULT_SETTINGS, send_telegram: true });
    expect(r.output!.telegram_state).toBe('FAILED');
    expect((await store.listSignals({ mode: 'LIVE' }))).toHaveLength(1);
  });
});

describe('statistics come only from recorded results', () => {
  const base = { entry: 100, stop_loss: 95, take_profit_1: 105, take_profit_2: 110, take_profit_3: 120 };
  const mk = (id: string, status: Signal['status'], mode: 'LIVE' | 'DEMO', pair = 'EURUSD', day = 0): Signal => ({ ...base, id, signal_id: id, data_mode: mode, pair, direction: 'long', entry_low: 99, entry_high: 101, confidence_score: 85, grade: 'HIGH', risk_reward: 2, setup_type: '', session: '', news_risk: 'low', confirmations: [], score_breakdown: {} as any, technical_reasoning: '', news_reasoning: '', fingerprint: id, timestamp: new Date(Date.UTC(2026, 9, 1 + day, 12)).toISOString(), status, result: null, result_r: resultFor(base, status), closed_at: new Date(Date.UTC(2026, 9, 1 + day, 14)).toISOString(), telegram_state: 'SENT', telegram_message_id: null } as Signal);
  it('R multiples from recorded levels', () => {
    expect(resultFor(base, 'TP1')).toBe(1); expect(resultFor(base, 'TP2')).toBe(2); expect(resultFor(base, 'TP3')).toBe(4);
    expect(resultFor(base, 'STOPPED')).toBe(-1); expect(resultFor(base, 'EXPIRED')).toBeNull();
  });
  it('returns nulls and zeros — not invented numbers — with no closed signals', () => {
    const p = computePerformance([], 'LIVE');
    expect(p).toMatchObject({ total_signals: 0, win_rate: null, profit_factor: null, max_drawdown_r: null, best_pair: null, closed: 0 });
    const open = computePerformance([mk('a', 'PENDING', 'LIVE')], 'LIVE');
    expect(open.win_rate).toBeNull(); expect(open.open).toBe(1);
  });
  it('computes win rate, profit factor, drawdown and best/worst pair; never mixes LIVE with DEMO', () => {
    const sigs = [mk('1', 'TP2', 'LIVE', 'EURUSD', 0), mk('2', 'STOPPED', 'LIVE', 'GBPUSD', 1), mk('3', 'STOPPED', 'LIVE', 'GBPUSD', 2), mk('4', 'TP3', 'LIVE', 'EURUSD', 3), mk('5', 'TP3', 'DEMO', 'XAUUSD', 3)];
    const p = computePerformance(sigs, 'LIVE', Date.UTC(2026, 9, 4, 10));
    expect(p).toMatchObject({ total_signals: 4, closed: 4, wins: 2, losses: 2, win_rate: 50, profit_factor: 3, max_drawdown_r: 2, net_r: 4, signals_today: 1 });
    expect(p.best_pair).toEqual({ pair: 'EURUSD', net_r: 6 });
    expect(p.worst_pair).toEqual({ pair: 'GBPUSD', net_r: -2 });
    expect(computePerformance(sigs, 'DEMO').total_signals).toBe(1);
  });
});

describe('outcome tracker', () => {
  const s = { entry: 100, entry_low: 99, entry_high: 101, stop_loss: 95, take_profit_1: 105, take_profit_2: 110, take_profit_3: 120, direction: 'long', status: 'PENDING', timestamp: new Date(0).toISOString(), closed_at: null } as any;
  const c = (t: number, o: number, h: number, l: number, cl: number) => ({ t: t * 60_000, o, h, l, c: cl, v: 1 });
  it('activates on entry, then reaches TP1 → TP2', () => {
    const p = evaluateSignal(s, [c(1, 103, 104, 100.5, 102), c(2, 102, 106, 101.5, 105), c(3, 105, 111, 104, 110)], 10 * 60_000)!;
    expect(p.status).toBe('TP2'); expect(p.result_r).toBe(2);
  });
  it('is conservative when SL and TP print in the same candle (stop first)', () => {
    const p = evaluateSignal({ ...s, status: 'ACTIVE' }, [c(1, 100, 106, 94, 100)], 10 * 60_000)!;
    expect(p.status).toBe('STOPPED'); expect(p.result_r).toBe(-1);
  });
  it('cancels a setup that ran to TP1 without filling, stops one filled and stopped in the same bar, expires stale pending, ignores closed', () => {
    expect(evaluateSignal(s, [c(1, 108, 112, 106, 111)], 5 * 60_000)!.status).toBe('CANCELLED');
    expect(evaluateSignal(s, [c(1, 110, 111, 94, 96)], 5 * 60_000)!.status).toBe('STOPPED');
    expect(evaluateSignal(s, [c(1, 104, 104.5, 103, 104)], 25 * 3_600_000)!.status).toBe('EXPIRED');
    expect(evaluateSignal({ ...s, status: 'STOPPED' }, [], 0)).toBeNull();
  });
});

describe('news classification', () => {
  it('classifies impact and currencies from headlines', () => {
    expect(classifyImpact('Fed Chair Powell speaks as FOMC rate decision looms')).toBe('HIGH');
    expect(classifyImpact('US retail sales rise in September')).toBe('MEDIUM');
    expect(classifyImpact('Central bank announces emergency rate meeting')).toBe('EXTREME');
    expect(classifyImpact('Local football club wins')).toBe('LOW');
    expect(detectCurrencies('BOE and ECB hold rates; gold steady')).toEqual(expect.arrayContaining(['GBP', 'EUR', 'XAU']));
  });
  it('flags blackout windows around HIGH events and reports UNKNOWN without a calendar', () => {
    const now = Date.parse('2026-10-01T12:00:00Z');
    const ev = [{ id: 'e', title: 'US CPI', currency: 'USD', time: new Date(now + 10 * 60_000).toISOString(), impact: 'HIGH' as const, affected_assets: [] }];
    expect(pairRisk('XAUUSD', ev, [], now, 30, true)).toMatchObject({ blackout: true, level: 'high' });
    expect(pairRisk('EURGBP', ev, [], now, 30, true)).toMatchObject({ blackout: false, level: 'low' });
    expect(pairRisk('EURUSD', [{ ...ev[0], time: new Date(now + 90 * 60_000).toISOString() }], [], now, 30, true)).toMatchObject({ blackout: false, level: 'high' });
    expect(pairRisk('EURUSD', [], [], now, 30, false).level).toBe('unknown');
  });
});

describe('no secrets reach the client', () => {
  it('client code never imports server config, and the snapshot carries no credentials', async () => {
    const { buildSnapshot } = await freshEnv() && await import('@/lib/snapshot');
    process.env.TELEGRAM_BOT_TOKEN = 'SECRET_TOKEN_VALUE'; process.env.MARKET_DATA_API_KEY = ''; process.env.NEWS_API_KEY = 'SECRET_NEWS_KEY';
    const json = JSON.stringify(await buildSnapshot());
    expect(json).not.toContain('SECRET_TOKEN_VALUE'); expect(json).not.toContain('SECRET_NEWS_KEY');
    const walk = (dir: string): string[] => fs.readdirSync(dir, { withFileTypes: true }).flatMap((d) => d.isDirectory() ? walk(`${dir}/${d.name}`) : [`${dir}/${d.name}`]);
    const clientFiles = [...walk('components'), 'app/page.tsx', 'app/layout.tsx'].filter((f) => /\.tsx?$/.test(f));
    for (const f of clientFiles) {
      const src = fs.readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/@\/lib\/config|process\.env|@\/lib\/database|@\/lib\/telegram\/(provider|index)|@\/lib\/market\/(twelvedata|index)/);
    }
    delete process.env.TELEGRAM_BOT_TOKEN; delete process.env.NEWS_API_KEY;
  });
});
