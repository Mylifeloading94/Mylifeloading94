import { z } from 'zod';
import { CalendarEventSchema, NewsIntelSchema, type CalendarEvent, type NewsIntel, type NewsItem } from '@/types';
import { affectedAssets, buildNewsItem, impactRank, pairRisk } from '@/lib/news/classify';
import type { NewsProvider } from '@/lib/news/types';
import type { SocialFeedProvider } from '@/lib/social/types';
import { BaseAgent } from './base';

const Input = z.object({
  watchlist: z.array(z.string()).min(1),
  blackout_minutes: z.number().positive(),
  manual_events: z.array(CalendarEventSchema),
});
export type NewsInput = z.infer<typeof Input>;

/** Agent 2 — monitors licensed news / social feeds and scheduled events; warns Setup Hunter about dangerous windows. */
export class NewsIntelligenceAgent extends BaseAgent<NewsInput, NewsIntel> {
  readonly id = 'news_intelligence' as const;
  readonly inputSchema = Input;
  readonly outputSchema = NewsIntelSchema;
  constructor(
    private news: NewsProvider,
    private social: SocialFeedProvider | null,
    private clock: () => number,
    opts?: ConstructorParameters<typeof BaseAgent>[0],
  ) { super(opts); }

  protected async execute(input: NewsInput) {
    const now = this.clock();
    let available = this.news.isAvailable();
    let items: NewsItem[] = [];
    let calendar: { available: boolean; events: CalendarEvent[] } = { available: false, events: [] };
    if (available) {
      try {
        const heads = await this.news.getHeadlines(now);
        items.push(...heads.map((h) => buildNewsItem(h, input.watchlist, 'news')));
        calendar = await this.news.getCalendar(now);
      } catch (e) {
        available = false;
        await this.log('warn', `News provider failed: ${(e as Error).message}`);
      }
    }
    if (this.social?.isAvailable()) {
      try {
        const posts = await this.social.getPosts(now);
        items.push(...posts.map((p) => buildNewsItem({ id: p.id, headline: p.text, source: p.author, published_at: p.published_at, url: p.url }, input.watchlist, 'social')));
      } catch (e) { await this.log('warn', `Social feed failed: ${(e as Error).message}`); }
    }
    items = items.sort((a, b) => b.published_at.localeCompare(a.published_at)).slice(0, 40);

    const manual = input.manual_events.map((e) => ({ ...e, manual: true }));
    const events = [...calendar.events, ...manual]
      .map((e) => ({ ...e, affected_assets: affectedAssets([e.currency], input.watchlist) }))
      .filter((e) => Date.parse(e.time) > now - 15 * 60_000)
      .sort((a, b) => a.time.localeCompare(b.time));
    // A manually-entered schedule counts as calendar coverage; an empty one does not.
    const calendarAvailable = calendar.available || manual.length > 0;
    const upcoming = events.filter((e) => Date.parse(e.time) >= now);
    const next = upcoming.find((e) => impactRank(e.impact) >= 2) ?? upcoming[0] ?? null;

    const scored = items.filter((i) => i.sentiment !== 0);
    const avg = scored.length ? scored.reduce((s, i) => s + i.sentiment, 0) / scored.length : 0;
    const sentiment = !available || !items.length
      ? { score: 0, label: 'unknown' as const }
      : { score: Number(avg.toFixed(2)), label: avg > 0.25 ? ('risk_on' as const) : avg < -0.25 ? ('risk_off' as const) : ('neutral' as const) };

    const pair_risk: NewsIntel['pair_risk'] = {};
    for (const p of input.watchlist) pair_risk[p] = pairRisk(p, events, items, now, input.blackout_minutes, calendarAvailable);

    const blackouts = Object.entries(pair_risk).filter(([, r]) => r.blackout).map(([p]) => p);
    const summary = !available
      ? 'News feed UNAVAILABLE — news risk cannot be verified'
      : blackouts.length
        ? `BLACKOUT on ${blackouts.length} pair(s): ${blackouts.slice(0, 4).join(', ')}${blackouts.length > 4 ? '…' : ''}`
        : next ? `Calm window · next ${next.impact} event: ${next.currency} ${next.title}` : 'Calm window · no scheduled high-impact events';

    const out: NewsIntel = {
      timestamp: new Date(now).toISOString(),
      data_mode: this.news.mode,
      available,
      calendar_available: calendarAvailable,
      items,
      upcoming_events: upcoming.slice(0, 12),
      next_event: next,
      countdown_seconds: next ? Math.max(0, Math.round((Date.parse(next.time) - now) / 1000)) : null,
      sentiment,
      pair_risk,
      summary,
    };
    return { output: out, summary };
  }
}
