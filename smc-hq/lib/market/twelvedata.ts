import type { Candle, Timeframe } from '@/types';
import { MarketDataUnavailableError, type MarketDataProvider } from './types';

const INTERVAL: Record<Timeframe, string> = { D1: '1day', H4: '4h', H1: '1h', M15: '15min', M5: '5min' };
const TTL_MS: Record<Timeframe, number> = { M5: 30_000, M15: 60_000, H1: 5 * 60_000, H4: 15 * 60_000, D1: 60 * 60_000 };

export const toProviderSymbol = (pair: string) => `${pair.slice(0, 3)}/${pair.slice(3)}`;

/** Live provider using the Twelve Data REST API. Server-side only; the key never reaches the browser. */
export class TwelveDataProvider implements MarketDataProvider {
  readonly name = 'Twelve Data';
  readonly mode = 'LIVE' as const;
  private cache = new Map<string, { at: number; data: Candle[] }>();
  constructor(private apiKey: string, private fetchImpl: typeof fetch = fetch) {}

  now() { return Date.now(); }

  async getCandles(pair: string, tf: Timeframe, count: number): Promise<Candle[]> {
    const key = `${pair}:${tf}`;
    const hit = this.cache.get(key);
    if (hit && Date.now() - hit.at < TTL_MS[tf] && hit.data.length >= count) return hit.data.slice(-count);
    const url = new URL('https://api.twelvedata.com/time_series');
    url.searchParams.set('symbol', toProviderSymbol(pair));
    url.searchParams.set('interval', INTERVAL[tf]);
    url.searchParams.set('outputsize', String(Math.max(count, 250)));
    url.searchParams.set('timezone', 'UTC');
    url.searchParams.set('order', 'ASC');
    url.searchParams.set('apikey', this.apiKey);
    let json: any;
    try {
      const res = await this.fetchImpl(url, { cache: 'no-store' });
      json = await res.json();
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      throw new MarketDataUnavailableError(`${pair} ${tf}: ${(e as Error).message}`);
    }
    if (json?.status === 'error' || !Array.isArray(json?.values)) {
      throw new MarketDataUnavailableError(`${pair} ${tf}: ${json?.message ?? 'malformed response'}`);
    }
    const data: Candle[] = json.values.map((v: any) => ({
      t: Date.parse(`${String(v.datetime).replace(' ', 'T')}${String(v.datetime).length <= 10 ? 'T00:00:00' : ''}Z`),
      o: +v.open, h: +v.high, l: +v.low, c: +v.close, v: +(v.volume ?? 0),
    })).filter((c: Candle) => Number.isFinite(c.t) && Number.isFinite(c.c));
    if (data.length < 30) throw new MarketDataUnavailableError(`${pair} ${tf}: only ${data.length} candles returned`);
    this.cache.set(key, { at: Date.now(), data });
    return data.slice(-count);
  }

  async getPrice(pair: string): Promise<number> {
    const m5 = await this.getCandles(pair, 'M5', 5);
    return m5[m5.length - 1].c;
  }
}
