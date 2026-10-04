import type { DataMode } from '@/types';

/** Server-only configuration. Never import this from a client component. */
const env = (k: string) => (process.env[k] ?? '').trim();

export const config = {
  get telegramToken() { return env('TELEGRAM_BOT_TOKEN'); },
  get telegramChatId() { return env('TELEGRAM_CHAT_ID'); },
  get telegramWebhookSecret() { return env('TELEGRAM_WEBHOOK_SECRET'); },
  get marketKey() { return env('MARKET_DATA_API_KEY'); },
  get newsKey() { return env('NEWS_API_KEY'); },
  get xKey() { return env('X_API_KEY'); },
  get databaseUrl() { return env('DATABASE_URL'); },
  get dataDir() { return env('DATA_DIR') || '.data'; },
  get scanIntervalSeconds() { return Number(env('SCAN_INTERVAL_SECONDS')) || 0; },
  get telegramConfigured() { return !!(this.telegramToken && this.telegramChatId); },
  /** LIVE only when a market data key exists and DEMO_MODE is not forced. */
  get mode(): DataMode {
    if (env('DEMO_MODE').toLowerCase() === 'true') return 'DEMO';
    return this.marketKey ? 'LIVE' : 'DEMO';
  },
};
