import type { CalendarEvent } from '@/types';
import type { NewsProvider, RawHeadline } from './types';

/** Headlines from NewsAPI.org (licensed API, no scraping). NewsAPI has no economic calendar. */
export class NewsApiProvider implements NewsProvider {
  readonly name = 'NewsAPI.org';
  readonly mode = 'LIVE' as const;
  private cache: { at: number; data: RawHeadline[] } | null = null;
  constructor(private apiKey: string, private fetchImpl: typeof fetch = fetch) {}
  isAvailable() { return !!this.apiKey; }

  async getHeadlines(): Promise<RawHeadline[]> {
    if (this.cache && Date.now() - this.cache.at < 120_000) return this.cache.data;
    const url = new URL('https://newsapi.org/v2/everything');
    url.searchParams.set('q', '(forex OR "central bank" OR "interest rates" OR inflation OR "Federal Reserve" OR ECB OR gold OR NFP OR CPI)');
    url.searchParams.set('language', 'en');
    url.searchParams.set('sortBy', 'publishedAt');
    url.searchParams.set('pageSize', '40');
    const res = await this.fetchImpl(url, { headers: { 'X-Api-Key': this.apiKey }, cache: 'no-store' });
    if (!res.ok) throw new Error(`NewsAPI HTTP ${res.status}`);
    const json: any = await res.json();
    const data: RawHeadline[] = (json.articles ?? []).map((a: any, i: number) => ({
      id: `na-${Date.parse(a.publishedAt)}-${i}`, headline: String(a.title ?? ''), source: a.source?.name ?? 'NewsAPI',
      published_at: a.publishedAt, url: a.url,
    })).filter((h: RawHeadline) => h.headline && h.headline !== '[Removed]');
    this.cache = { at: Date.now(), data };
    return data;
  }

  async getCalendar() { return { available: false, events: [] as CalendarEvent[] }; }
}
