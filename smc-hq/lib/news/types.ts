import type { CalendarEvent, DataMode } from '@/types';

export interface RawHeadline { id: string; headline: string; source: string; published_at: string; url?: string }

export interface NewsProvider {
  readonly name: string;
  readonly mode: DataMode;
  /** false when the provider has no credentials / cannot be reached. */
  isAvailable(): boolean;
  getHeadlines(now: number): Promise<RawHeadline[]>;
  /** Scheduled releases. `available:false` means the provider has no calendar at all. */
  getCalendar(now: number): Promise<{ available: boolean; events: CalendarEvent[] }>;
}
