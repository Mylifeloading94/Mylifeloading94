import { config } from '@/lib/config';
import { getStore, storeNote } from '@/lib/database';
import { recentEvents } from '@/lib/events/bus';
import { loadSettings } from '@/lib/risk/settings';
import { runtime } from '@/lib/state';
import { telegramStatus } from '@/lib/telegram';

/** Everything the browser needs. Contains NO secrets — only booleans/labels derived from them. */
export async function buildSnapshot() {
  const rt = runtime();
  const store = await getStore();
  const [settings, signals, tg] = await Promise.all([loadSettings(), store.listSignals({ limit: 50 }), telegramStatus()]);
  const live = config.mode === 'LIVE';
  // LIVE reads ONLINE only after a successful live analysis — a configured key alone proves nothing.
  const marketState = rt.unavailableReason ? 'UNAVAILABLE' : live ? (Object.keys(rt.analyses).length ? 'ONLINE' : 'STANDBY') : 'DEMO';
  const newsState = !rt.news ? (live && !config.newsKey ? 'UNAVAILABLE' : live ? 'STANDBY' : 'DEMO') : !rt.news.available ? 'UNAVAILABLE' : live ? 'ONLINE' : 'DEMO';
  const agents = Object.values(rt.agents);
  return {
    mode: config.mode,
    paused: rt.paused,
    scanning: rt.scanning,
    now: new Date().toISOString(),
    system: {
      market: { state: marketState, detail: rt.unavailableReason ?? (live ? (marketState === 'STANDBY' ? 'Live provider configured — no scan completed yet' : 'Live provider') : 'DEMO DATA — simulated') },
      news: { state: newsState, detail: live ? (config.newsKey ? 'NewsAPI' : 'NEWS_API_KEY not set') : 'DEMO DATA — simulated' },
      agents: { online: agents.filter((a) => a.status !== 'error' && a.status !== 'offline').length, total: agents.length },
      telegram: tg,
      database: storeNote(),
    },
    agents: Object.fromEntries(agents.map((a) => [a.id, a])),
    analyses: rt.analyses,
    news: rt.news,
    news_at: rt.newsAt,
    hunter: rt.hunter,
    lastSignal: rt.lastSignal ?? signals[0] ?? null,
    signals,
    settings,
    last_scan_at: rt.lastScanAt,
    events: recentEvents(60),
  };
}
