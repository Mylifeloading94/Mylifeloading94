import { beforeEach, describe, expect, it, vi } from 'vitest';
import { freshEnv } from './helpers';
import { runDemoSignal, runScan } from '@/lib/pipeline';
import { DemoMarketProvider, demoAnchor } from '@/lib/market';
import { recentEvents } from '@/lib/events/bus';
import { DemoNewsProvider } from '@/lib/news';
import type { TelegramProvider } from '@/lib/telegram';

const noTelegram = (): TelegramProvider & { sendMessage: ReturnType<typeof vi.fn> } => ({
  name: 'mock', isConfigured: () => true, sendMessage: vi.fn(async () => ({ ok: true, messageId: 1 })), getMe: async () => ({ ok: true }),
});

describe('demo signal pipeline', () => {
  let env: ReturnType<typeof freshEnv>;
  beforeEach(() => { env = freshEnv(); });

  it('runs analyst → news → hunter → command and stores a DEMO signal', async () => {
    const r = await runDemoSignal({ pace: false });
    expect(r.failures).toEqual([]);
    expect(r.analyses).toHaveLength(1);
    expect(r.analyses[0].pair).toBe('XAUUSD');
    expect(r.analyses[0].htf_bias).toBe('bullish');
    expect(r.analyses[0].liquidity_event).toBe('sell_side_sweep');
    expect(r.hunter!.approved).toHaveLength(1);
    const out = r.signals[0];
    expect(out.outcome).toBe('created');
    const sig = out.signal!;
    expect(sig.data_mode).toBe('DEMO');
    expect(sig.signal_id).toMatch(/^DEMO-\d{4}-0001$/);
    expect(sig.confidence_score).toBeGreaterThanOrEqual(80);
    expect(sig.telegram_state).toBe('DEMO_PREVIEW');
    expect(out.preview).toContain('SMC TRADING SIGNAL');
    expect(await env.store.listSignals({ mode: 'DEMO' })).toHaveLength(1);
    expect(await env.store.listSignals({ mode: 'LIVE' })).toHaveLength(0);
  });

  it('publishes the message flow on the bus in pipeline order', async () => {
    await runDemoSignal({ pace: false });
    const types: string[] = recentEvents(300).map((e) => e.type);
    const order = ['pipeline.start', 'market.analysis', 'news.intel', 'setup.evaluated', 'setup.approved', 'signal.created', 'telegram.preview', 'pipeline.end'];
    let at = -1;
    for (const t of order) { const i = types.indexOf(t, at + 1); expect(i, t).toBeGreaterThan(at); at = i; }
  });

  it('never sends a demo signal to Telegram, even with credentials', async () => {
    const tg = noTelegram();
    await runScan({ pairs: ['XAUUSD'], provider: new DemoMarketProvider({ anchor: demoAnchor() }), telegram: tg, demoSalt: 'x', sendTelegram: true });
    expect(tg.sendMessage).not.toHaveBeenCalled();
  });

  it('blocks the same setup twice (duplicate prevention)', async () => {
    const provider = new DemoMarketProvider({ anchor: demoAnchor() });
    const a = await runScan({ pairs: ['XAUUSD'], provider, agentOpts: { retryDelayMs: 0 } });
    const b = await runScan({ pairs: ['XAUUSD'], provider, agentOpts: { retryDelayMs: 0 } });
    expect(a.signals[0].outcome).toBe('created');
    expect(b.signals[0].outcome).toBe('duplicate');
    expect(await env.store.listSignals()).toHaveLength(1);
  });

  it('rejects the setup when a HIGH-impact release falls inside the blackout window', async () => {
    const r = await runScan({
      pairs: ['XAUUSD'], provider: new DemoMarketProvider({ anchor: demoAnchor() }),
      newsProvider: new DemoNewsProvider({ blackout: true }), demoSalt: 'b',
    });
    const ev = r.hunter!.evaluations[0];
    expect(ev.approved).toBe(false);
    expect(ev.rejection_reasons.join(' ')).toMatch(/News risk/);
    expect(r.signals).toHaveLength(0);
    expect(await env.store.listSignals()).toHaveLength(0);
  });

  it('is robust across simulated-clock shifts (every repeated demo click works)', async () => {
    for (let k = 0; k < 12; k++) {
      const r = await runDemoSignal({ pace: false });
      expect(r.signals[0]?.outcome, `run ${k + 1}: ${JSON.stringify(r.hunter?.evaluations[0]?.rejection_reasons)}`).toBe('created');
    }
    const ids = (await env.store.listSignals({ mode: 'DEMO' })).map((s) => s.signal_id);
    expect(new Set(ids).size).toBe(12);
  });

  it('scans the whole default watchlist and rejects pairs with no model, with reasons', async () => {
    const r = await runScan({ provider: new DemoMarketProvider({ anchor: demoAnchor() }), demoSalt: 's' });
    expect(r.hunter!.scanned).toBe(12);
    expect(r.hunter!.evaluations.every((e) => e.approved || e.rejection_reasons.length > 0)).toBe(true);
    expect(r.hunter!.evaluations.every((e) => e.data_mode === 'DEMO')).toBe(true);
  });

  it('reports MARKET DATA UNAVAILABLE and generates no signal when the provider fails', async () => {
    const broken = new DemoMarketProvider();
    broken.getCandles = async () => { throw new Error('MARKET DATA UNAVAILABLE: boom'); };
    const r = await runScan({ pairs: ['XAUUSD'], provider: broken, agentOpts: { maxAttempts: 2, retryDelayMs: 0 } });
    expect(r.signals).toHaveLength(0);
    expect(r.hunter).toBeNull();
    expect(r.failures[0]).toMatch(/MARKET DATA UNAVAILABLE/);
    const { runtime } = await import('@/lib/state');
    expect(runtime().unavailableReason).toMatch(/MARKET DATA UNAVAILABLE/);
    expect(runtime().agents.market_analyst.status).toBe('error');
  });
});
