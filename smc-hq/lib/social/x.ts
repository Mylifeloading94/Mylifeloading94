import type { SocialFeedProvider, SocialPost } from './types';

export const X_ACCOUNTS = ['federalreserve', 'ecb', 'bankofengland', 'bankofjapan_en', 'RBAInfo', 'RBNZ', 'bankofcanada', 'snbnews', 'BLS_gov', 'USTreasury'];

/** X (Twitter) API v2 recent search with a bearer token the user supplies. No scraping. */
export class XFeedProvider implements SocialFeedProvider {
  readonly name = 'X API v2';
  readonly mode = 'LIVE' as const;
  private cache: { at: number; data: SocialPost[] } | null = null;
  constructor(private bearer: string, private fetchImpl: typeof fetch = fetch) {}
  isAvailable() { return !!this.bearer; }

  async getPosts(): Promise<SocialPost[]> {
    if (this.cache && Date.now() - this.cache.at < 180_000) return this.cache.data;
    const q = `(${X_ACCOUNTS.map((a) => `from:${a}`).join(' OR ')}) -is:retweet`;
    const url = new URL('https://api.twitter.com/2/tweets/search/recent');
    url.searchParams.set('query', q);
    url.searchParams.set('max_results', '30');
    url.searchParams.set('tweet.fields', 'created_at,author_id');
    const res = await this.fetchImpl(url, { headers: { Authorization: `Bearer ${this.bearer}` }, cache: 'no-store' });
    if (!res.ok) throw new Error(`X API HTTP ${res.status}`);
    const json: any = await res.json();
    const data: SocialPost[] = (json.data ?? []).map((t: any) => ({
      id: `x-${t.id}`, text: String(t.text), author: String(t.author_id), published_at: t.created_at,
      url: `https://x.com/i/web/status/${t.id}`,
    }));
    this.cache = { at: Date.now(), data };
    return data;
  }
}
