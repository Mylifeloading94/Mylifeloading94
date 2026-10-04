import type { DataMode } from '@/types';
export interface SocialPost { id: string; text: string; author: string; published_at: string; url?: string }
export interface SocialFeedProvider {
  readonly name: string;
  readonly mode: DataMode;
  isAvailable(): boolean;
  getPosts(now: number): Promise<SocialPost[]>;
}
