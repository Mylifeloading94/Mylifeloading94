import type { CalendarEvent, ImpactLevel, NewsItem } from '@/types';

const CURRENCY_KEYWORDS: [string, RegExp][] = [
  ['USD', /\b(fed|federal reserve|fomc|powell|us dollar|dollar index|dxy|treasury|u\.s\.|us cpi|us ppi|nfp|nonfarm|non-farm|white house)\b/i],
  ['EUR', /\b(ecb|lagarde|eurozone|euro area|euro zone|\beuro\b|bundesbank)\b/i],
  ['GBP', /\b(boe|bank of england|bailey|sterling|\buk\b|britain|pound)\b/i],
  ['JPY', /\b(boj|bank of japan|ueda|yen|japan|mof intervention)\b/i],
  ['CHF', /\b(snb|swiss national bank|swiss franc|switzerland)\b/i],
  ['AUD', /\b(rba|reserve bank of australia|aussie|australia)\b/i],
  ['NZD', /\b(rbnz|reserve bank of new zealand|kiwi|new zealand)\b/i],
  ['CAD', /\b(boc|bank of canada|loonie|canada|canadian)\b/i],
  ['XAU', /\b(gold|bullion|xau)\b/i],
];

const EXTREME = /\b(emergency (rate|meeting)|intervention|invasion|declares? war|default|bank run|black swan|circuit breaker|flash crash|surprise (rate )?(cut|hike)|market halt)\b/i;
const HIGH = /\b(cpi|inflation rate|nonfarm|non-farm|nfp|fomc|rate decision|interest rate decision|rate (hike|cut)|raises rates|cuts rates|holds rates|powell|lagarde|bailey|ueda|jackson hole|fed (chair|speech|minutes)|dot plot|war|sanctions|tariff)\b/i;
const MEDIUM = /\b(gdp|ppi|retail sales|pmi|unemployment|jobless|employment|payrolls|trade balance|consumer confidence|ism|housing|durable goods|central bank|speech|minutes)\b/i;

const POS = /\b(surge|rally|rallies|beat|beats|strong|jump|gain|gains|rise|rises|optimis|upbeat|record high|boost)\b/i;
const NEG = /\b(plunge|slump|miss|misses|weak|fall|falls|drop|drops|fear|crisis|recession|cut|downgrade|selloff|sell-off|war|slide)\b/i;

export const detectCurrencies = (text: string): string[] => CURRENCY_KEYWORDS.filter(([, re]) => re.test(text)).map(([c]) => c);

export function classifyImpact(text: string): ImpactLevel {
  if (EXTREME.test(text)) return 'EXTREME';
  if (HIGH.test(text)) return 'HIGH';
  if (MEDIUM.test(text)) return 'MEDIUM';
  return 'LOW';
}

/** Watchlist symbols that contain any affected currency; gold is exposed to USD and XAU headlines. */
export function affectedAssets(currencies: string[], watchlist: string[]): string[] {
  const set = new Set(currencies);
  return watchlist.filter((p) => {
    const base = p.slice(0, 3), quote = p.slice(3);
    if (p === 'XAUUSD') return set.has('XAU') || set.has('USD');
    return set.has(base) || set.has(quote);
  });
}

export function sentimentOf(text: string): number {
  const p = POS.test(text) ? 1 : 0, n = NEG.test(text) ? 1 : 0;
  return p - n;
}

const EFFECT: Record<ImpactLevel, string> = {
  LOW: 'Limited expected volatility',
  MEDIUM: 'Moderate volatility possible around release',
  HIGH: 'Elevated volatility and spread widening likely',
  EXTREME: 'Disorderly price action possible — stand aside',
};

export function buildNewsItem(
  raw: { id: string; headline: string; source: string; published_at: string; url?: string },
  watchlist: string[],
  channel: 'news' | 'social',
): NewsItem {
  const currencies = detectCurrencies(raw.headline);
  const impact = classifyImpact(raw.headline);
  return {
    id: raw.id, headline: raw.headline, source: raw.source, published_at: raw.published_at, impact,
    currencies, affected_assets: affectedAssets(currencies, watchlist),
    potential_effect: currencies.length ? `${currencies.join('/')}: ${EFFECT[impact]}` : EFFECT[impact],
    sentiment: sentimentOf(raw.headline), channel, url: raw.url,
  };
}

const RANK: Record<ImpactLevel, number> = { LOW: 0, MEDIUM: 1, HIGH: 2, EXTREME: 3 };
export const impactRank = (i: ImpactLevel) => RANK[i];

/**
 * Per-pair risk from scheduled events + very recent headlines.
 * Blackout = HIGH/EXTREME event from 15 min after the release to `blackoutMin` before it (doubled for EXTREME).
 */
export function pairRisk(
  pair: string,
  events: CalendarEvent[],
  recent: NewsItem[],
  now: number,
  blackoutMin: number,
  calendarAvailable: boolean,
) {
  const ccys = pair === 'XAUUSD' ? ['XAU', 'USD'] : [pair.slice(0, 3), pair.slice(3)];
  let level: 'low' | 'medium' | 'high' | 'extreme' = 'low';
  let blackout = false;
  let reason = 'No relevant scheduled events';
  let minutes: number | null = null;
  const lvl = (i: ImpactLevel) => i.toLowerCase() as 'low' | 'medium' | 'high' | 'extreme';
  let best = -1;
  const bump = (to: typeof level, why: string, mins: number | null) => {
    const r = RANK[to.toUpperCase() as ImpactLevel];
    if (r > best) { best = r; level = to; reason = why; minutes = mins; }
  };
  for (const ev of events) {
    if (!ccys.includes(ev.currency)) continue;
    const mins = (Date.parse(ev.time) - now) / 60_000;
    if (mins < -15 || mins > 240) continue;
    const win = ev.impact === 'EXTREME' ? blackoutMin * 2 : blackoutMin;
    if ((ev.impact === 'HIGH' || ev.impact === 'EXTREME') && mins <= win) blackout = true;
    bump(lvl(ev.impact), `${ev.currency} ${ev.title} ${mins >= 0 ? `in ${Math.round(mins)}m` : `${Math.round(-mins)}m ago`}`, mins);
  }
  for (const n of recent) {
    if (!n.currencies.some((c) => ccys.includes(c))) continue;
    const age = (now - Date.parse(n.published_at)) / 60_000;
    if (age < 0 || age > 30) continue;
    if (n.impact === 'EXTREME') { blackout = true; bump('extreme', `Breaking: ${n.headline.slice(0, 60)}`, null); }
    else if (n.impact === 'HIGH') { bump('high', `Recent high-impact headline (${Math.round(age)}m ago)`, null); }
  }
  if (!calendarAvailable && level === 'low') { return { level: 'unknown' as const, blackout, reason: 'Economic calendar unavailable — scheduled-event risk cannot be verified', minutes_to_event: null }; }
  return { level, blackout, reason, minutes_to_event: minutes === null ? null : Math.round(minutes) };
}
