import { describe, expect, it, vi } from 'vitest';
import { TwelveDataProvider, toProviderSymbol } from '@/lib/market/twelvedata';
import { MarketDataUnavailableError } from '@/lib/market/types';
import { NewsApiProvider } from '@/lib/news/newsapi';
import { XFeedProvider } from '@/lib/social/x';
import { UnavailableNewsProvider } from '@/lib/news/demo';
import { NewsIntelligenceAgent } from '@/lib/agents/newsIntelligence';
import { MarketAnalystAgent } from '@/lib/agents/marketAnalyst';
import { freshEnv } from './helpers';

const res = (body: unknown, ok = true, status = 200) => ({ ok, status, json: async () => body }) as any;

describe('Twelve Data provider', () => {
  const values = Array.from({ length: 60 }, (_, i) => ({ datetime: `2026-10-01 ${String(Math.floor(i / 12)).padStart(2, '0')}:${String((i % 12) * 5).padStart(2, '0')}:00`, open: '1.1', high: '1.2', low: '1.0', close: '1.15', volume: '10' }));
  it('maps symbols, parses UTC candles, requests ascending order and caches', async () => {
    const f = vi.fn(async () => res({ status: 'ok', values }));
    const p = new TwelveDataProvider('KEY', f as any);
    expect(toProviderSymbol('XAUUSD')).toBe('XAU/USD');
    const c = await p.getCandles('EURUSD', 'M5', 30);
    expect(c).toHaveLength(30);
    expect(c[0].t).toBe(Date.parse('2026-10-01T02:30:00Z'));
    const url = String((f.mock.calls[0] as any[])[0]);
    expect(url).toContain('symbol=EUR%2FUSD'); expect(url).toContain('interval=5min'); expect(url).toContain('order=ASC'); expect(url).toContain('timezone=UTC');
    await p.getCandles('EURUSD', 'M5', 30);
    expect(f).toHaveBeenCalledTimes(1);
    expect(p.mode).toBe('LIVE');
  });
  it('turns API errors, HTTP errors and thin data into MARKET DATA UNAVAILABLE', async () => {
    await expect(new TwelveDataProvider('K', (async () => res({ status: 'error', message: 'rate limit' })) as any).getCandles('EURUSD', 'H1', 10)).rejects.toThrow(/MARKET DATA UNAVAILABLE.*rate limit/);
    await expect(new TwelveDataProvider('K', (async () => { throw new Error('ENOTFOUND'); }) as any).getCandles('EURUSD', 'H1', 10)).rejects.toBeInstanceOf(MarketDataUnavailableError);
    await expect(new TwelveDataProvider('K', (async () => res({ status: 'ok', values: values.slice(0, 5) })) as any).getCandles('EURUSD', 'H1', 3)).rejects.toThrow(/only 5 candles/);
  });
  it('Market Analyst fails closed (no analysis) when the live provider is unavailable', async () => {
    freshEnv();
    const p = new TwelveDataProvider('K', (async () => res({ status: 'error', message: 'bad key' })) as any);
    const r = await new MarketAnalystAgent(p, { maxAttempts: 2, retryDelayMs: 0 }).run({ pair: 'EURUSD' });
    expect(r.ok).toBe(false); expect(r.output).toBeNull(); expect(r.error).toMatch(/MARKET DATA UNAVAILABLE/); expect(r.attempts).toBe(2);
  });
});

describe('news & social providers', () => {
  it('NewsAPI sends the key as a header (not in the URL) and maps articles', async () => {
    const f = vi.fn(async () => res({ articles: [{ title: 'Fed holds rates; dollar slips', publishedAt: '2026-10-01T10:00:00Z', source: { name: 'Wire' }, url: 'https://x/1' }, { title: '[Removed]', publishedAt: 'x', source: {} }] }));
    const p = new NewsApiProvider('NKEY', f as any);
    const h = await p.getHeadlines();
    expect(h).toHaveLength(1); expect(h[0]).toMatchObject({ headline: 'Fed holds rates; dollar slips', source: 'Wire' });
    const [url, init] = f.mock.calls[0] as any[];
    expect(String(url)).not.toContain('NKEY'); expect(init.headers['X-Api-Key']).toBe('NKEY');
    expect((await p.getCalendar()).available).toBe(false);
  });
  it('X API uses a bearer token and maps tweets', async () => {
    const f = vi.fn(async () => res({ data: [{ id: '1', text: 'FOMC statement released', created_at: '2026-10-01T18:00:00Z', author_id: '9' }] }));
    const posts = await new XFeedProvider('XTOKEN', f as any).getPosts();
    expect(posts[0]).toMatchObject({ id: 'x-1', text: 'FOMC statement released' });
    expect((f.mock.calls[0] as any[])[1].headers.Authorization).toBe('Bearer XTOKEN');
  });
  it('News Intelligence degrades honestly in LIVE mode without a key (feed unavailable, risk UNKNOWN, no demo data)', async () => {
    freshEnv();
    const agent = new NewsIntelligenceAgent(new UnavailableNewsProvider(), null, () => Date.now(), { retryDelayMs: 0 });
    const r = await agent.run({ watchlist: ['EURUSD', 'XAUUSD'], blackout_minutes: 30, manual_events: [] });
    expect(r.output).toMatchObject({ data_mode: 'LIVE', available: false, calendar_available: false, items: [] });
    expect(r.output!.pair_risk.XAUUSD.level).toBe('unknown');
    expect(r.output!.summary).toMatch(/UNAVAILABLE/);
  });
  it('manual calendar events create real blackouts even without a news key', async () => {
    freshEnv();
    const now = Date.now();
    const agent = new NewsIntelligenceAgent(new UnavailableNewsProvider(), null, () => now, { retryDelayMs: 0 });
    const r = await agent.run({ watchlist: ['EURUSD', 'GBPJPY'], blackout_minutes: 30, manual_events: [{ id: 'm', title: 'US NFP', currency: 'USD', time: new Date(now + 20 * 60_000).toISOString(), impact: 'HIGH', affected_assets: [] }] });
    expect(r.output!.pair_risk.EURUSD).toMatchObject({ blackout: true, level: 'high' });
    expect(r.output!.pair_risk.GBPJPY.blackout).toBe(false);
    expect(r.output!.next_event?.title).toBe('US NFP');
  });
});
