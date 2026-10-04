import type { AgentOptions } from '@/lib/agents/base';
import { MarketAnalystAgent } from '@/lib/agents/marketAnalyst';
import { NewsIntelligenceAgent } from '@/lib/agents/newsIntelligence';
import { SetupHunterAgent } from '@/lib/agents/setupHunter';
import { SignalCommandAgent, type SignalCommandOutput } from '@/lib/agents/signalCommand';
import { getStore } from '@/lib/database';
import { emit } from '@/lib/events/bus';
import { getMarketProvider, DemoMarketProvider, demoAnchor, type MarketDataProvider } from '@/lib/market';
import { sessionAt } from '@/lib/analysis/sessions';
import { DemoNewsProvider, getNewsProvider, type NewsProvider } from '@/lib/news';
import { DemoSocialProvider, getSocialProvider, type SocialFeedProvider } from '@/lib/social';
import { loadSettings } from '@/lib/risk/settings';
import { runtime } from '@/lib/state';
import { getTelegramProvider, type TelegramProvider } from '@/lib/telegram';
import type { HunterReport, MarketAnalysis, NewsIntel } from '@/types';

export interface ScanOptions {
  pairs?: string[];
  provider?: MarketDataProvider;
  newsProvider?: NewsProvider;
  social?: SocialFeedProvider | null;
  telegram?: TelegramProvider;
  /** Delay (ms) between pairs while the Hunter scans — lets the 3D radar visibly sweep. */
  paceMs?: number;
  /** Delay (ms) between pipeline stages — makes the hand-offs visible in the world. */
  stageDelayMs?: number;
  sendTelegram?: boolean;
  demoSalt?: string;
  agentOpts?: AgentOptions;
  /** Scans from the scheduler/UI respect /pause; a demo run does not. */
  respectPause?: boolean;
}

export interface ScanResult {
  skipped: string | null;
  mode: 'LIVE' | 'DEMO';
  analyses: MarketAnalysis[];
  news: NewsIntel | null;
  hunter: HunterReport | null;
  signals: SignalCommandOutput[];
  failures: string[];
}

const sleep = (ms: number) => (ms > 0 ? new Promise((r) => setTimeout(r, ms)) : Promise.resolve());

/** MARKET DATA → MARKET ANALYST → NEWS INTELLIGENCE → SETUP HUNTER → SIGNAL COMMAND → TELEGRAM */
export async function runScan(opts: ScanOptions = {}): Promise<ScanResult> {
  const rt = runtime();
  const provider = opts.provider ?? getMarketProvider();
  const result: ScanResult = { skipped: null, mode: provider.mode, analyses: [], news: null, hunter: null, signals: [], failures: [] };
  if (rt.scanning) return { ...result, skipped: 'A scan is already running' };
  if (opts.respectPause !== false && rt.paused) return { ...result, skipped: 'Paused (/pause)' };
  if (provider.mode === 'LIVE' && sessionAt(provider.now()) === 'MARKET CLOSED') {
    rt.unavailableReason = null;
    return { ...result, skipped: 'Forex market is closed' };
  }

  rt.scanning = true;
  const settings = await loadSettings();
  const store = await getStore();
  const pairs = opts.pairs ?? settings.watchlist;
  const stage = opts.stageDelayMs ?? 0;
  emit('pipeline.start', 'system', 'world', { mode: provider.mode, pairs });

  try {
    const clock = () => provider.now();
    const analyst = new MarketAnalystAgent(provider, opts.agentOpts);
    const newsAgent = new NewsIntelligenceAgent(opts.newsProvider ?? getNewsProvider(), opts.social === undefined ? getSocialProvider() : opts.social, clock, opts.agentOpts);
    const hunter = new SetupHunterAgent(opts.paceMs ?? 0, opts.agentOpts);
    const command = new SignalCommandAgent(opts.telegram ?? getTelegramProvider(), clock, opts.agentOpts);

    /* 1 — Market Analyst */
    const unavailable: string[] = [];
    for (const pair of pairs) {
      emit('hunter.progress', 'market_analyst', 'world', { pair, phase: 'analysing' });
      const r = await analyst.run({ pair });
      if (r.ok && r.output) {
        result.analyses.push(r.output);
        rt.analyses[pair] = r.output;
        emit('market.analysis', 'market_analyst', 'setup_hunter', r.output);
        store.logAnalysis(r.output).catch(() => undefined);
      } else {
        unavailable.push(pair);
        result.failures.push(`${pair}: ${r.error}`);
      }
      if (opts.paceMs && pairs.length > 1) await sleep(Math.min(opts.paceMs, 150));
    }
    rt.unavailableReason = result.analyses.length === 0 ? (result.failures[0] ?? 'MARKET DATA UNAVAILABLE') : null; // cleared by any successful analysis
    if (result.analyses.length === 0) {
      emit('system', 'system', 'world', { level: 'error', message: rt.unavailableReason });
      return result; // MARKET DATA UNAVAILABLE — no signal can be generated
    }
    await sleep(stage);

    /* 2 — News Intelligence */
    const nr = await newsAgent.run({ watchlist: settings.watchlist, blackout_minutes: settings.news_blackout_minutes, manual_events: settings.manual_events });
    if (nr.ok && nr.output) {
      result.news = nr.output; rt.news = nr.output; rt.newsAt = Date.now();
      emit('news.intel', 'news_intelligence', 'setup_hunter', nr.output);
      store.logNews(nr.output).catch(() => undefined);
    } else result.failures.push(`news: ${nr.error}`);
    await sleep(stage);

    /* 3 — Setup Hunter */
    const hr = await hunter.run({ analyses: result.analyses, news: result.news, settings, unavailable });
    if (!hr.ok || !hr.output) { result.failures.push(`hunter: ${hr.error}`); return result; }
    result.hunter = hr.output; rt.hunter = hr.output;
    for (const ev of hr.output.evaluations) store.logScore(ev).catch(() => undefined);
    await sleep(stage);

    /* 4 — Signal Command */
    for (const setup of hr.output.approved) {
      emit('setup.approved', 'setup_hunter', 'signal_command', setup);
      await sleep(stage);
      const cr = await command.run({ setup, settings, send_telegram: opts.sendTelegram ?? true, demo_salt: opts.demoSalt });
      if (cr.ok && cr.output) result.signals.push(cr.output); else result.failures.push(`signal_command: ${cr.error}`);
    }
    rt.lastScanAt = new Date().toISOString();
    return result;
  } finally {
    rt.scanning = false;
    rt.lastScanAt = new Date().toISOString();
    emit('pipeline.end', 'system', 'world', { signals: result.signals.filter((s) => s.outcome === 'created').length, failures: result.failures.length });
  }
}

/**
 * "RUN DEMO SIGNAL": a self-contained, clearly-labelled DEMO run on XAUUSD. It never talks to Telegram
 * and records its signal with data_mode=DEMO so it can never pollute LIVE statistics.
 */
export async function runDemoSignal(opts: { blackout?: boolean; pace?: boolean } = {}): Promise<ScanResult> {
  const rt = runtime();
  const k = ++rt.demoRuns;
  const provider = new DemoMarketProvider({ anchor: demoAnchor(Date.now(), -((k - 1) % 12) * 15) });
  const slow = opts.pace !== false;
  return runScan({
    pairs: ['XAUUSD'],
    provider,
    newsProvider: new DemoNewsProvider({ blackout: !!opts.blackout }),
    social: new DemoSocialProvider(),
    paceMs: slow ? 700 : 0,
    stageDelayMs: slow ? 1100 : 0,
    sendTelegram: false,
    demoSalt: `run-${k}-${Date.now().toString(36)}`,
    respectPause: false,
  });
}
