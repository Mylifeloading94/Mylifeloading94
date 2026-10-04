import { config } from '@/lib/config';
import { DemoMarketProvider } from './demo';
import { TwelveDataProvider } from './twelvedata';
import type { MarketDataProvider } from './types';

export * from './types';
export { DemoMarketProvider, demoAnchor } from './demo';

const g = globalThis as unknown as { __smcMarket?: MarketDataProvider; __smcMarketKey?: string };

/** Provider selection is the only place that knows which vendor is in use. */
export function getMarketProvider(): MarketDataProvider {
  const key = `${config.mode}:${config.marketKey}`;
  if (!g.__smcMarket || g.__smcMarketKey !== key) {
    g.__smcMarket = config.mode === 'LIVE' ? new TwelveDataProvider(config.marketKey) : new DemoMarketProvider();
    g.__smcMarketKey = key;
  }
  return g.__smcMarket;
}
