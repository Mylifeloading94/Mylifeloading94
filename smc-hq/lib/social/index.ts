import { config } from '@/lib/config';
import { DemoSocialProvider } from './demo';
import { XFeedProvider } from './x';
import type { SocialFeedProvider } from './types';
export * from './types';

export function getSocialProvider(): SocialFeedProvider | null {
  if (config.mode === 'DEMO') return new DemoSocialProvider();
  return config.xKey ? new XFeedProvider(config.xKey) : null;
}
export { DemoSocialProvider } from './demo';
