import { config } from '@/lib/config';
import { DemoNewsProvider, UnavailableNewsProvider } from './demo';
import { NewsApiProvider } from './newsapi';
import type { NewsProvider } from './types';

export * from './types';
export * from './classify';

/** DEMO market data ⇒ DEMO news. LIVE ⇒ real feed or an explicit "unavailable". Never mixed. */
export function getNewsProvider(opts: { blackout?: boolean } = {}): NewsProvider {
  if (config.mode === 'DEMO') return new DemoNewsProvider(opts);
  return config.newsKey ? new NewsApiProvider(config.newsKey) : new UnavailableNewsProvider();
}
export { DemoNewsProvider } from './demo';
