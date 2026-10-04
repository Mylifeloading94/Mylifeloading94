import type { SocialFeedProvider, SocialPost } from './types';

export class DemoSocialProvider implements SocialFeedProvider {
  readonly name = 'DEMO DATA (simulated)';
  readonly mode = 'DEMO' as const;
  isAvailable() { return true; }
  async getPosts(now: number): Promise<SocialPost[]> {
    const at = (m: number) => new Date(now - m * 60_000).toISOString();
    return [
      { id: 'demo-s1', text: 'DEMO: Fed official: inflation progress continues, rate path data-dependent', author: '@demo_fed_watch', published_at: at(7) },
      { id: 'demo-s2', text: 'DEMO: Gold holds bid near highs as real yields soften', author: '@demo_macro', published_at: at(15) },
    ];
  }
}
