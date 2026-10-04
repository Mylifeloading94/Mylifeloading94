import type { CalendarEvent } from '@/types';
import type { NewsProvider, RawHeadline } from './types';

/** Simulated headlines/calendar relative to the demo clock. Everything here is DEMO DATA. */
export class DemoNewsProvider implements NewsProvider {
  readonly name = 'DEMO DATA (simulated)';
  readonly mode = 'DEMO' as const;
  constructor(private opts: { blackout?: boolean } = {}) {}
  isAvailable() { return true; }

  async getHeadlines(now: number): Promise<RawHeadline[]> {
    const at = (m: number) => new Date(now - m * 60_000).toISOString();
    const list: [number, string, string][] = [
      [4, 'Gold steadies as traders await US data; dollar edges lower', 'DEMO Wire'],
      [11, 'Fed speaker says policy is well positioned, sees inflation easing gradually', 'DEMO Wire'],
      [19, 'ECB officials signal patience on rate cuts as eurozone PMI beats estimates', 'DEMO Markets'],
      [27, 'Yen slides as BOJ Ueda keeps policy unchanged', 'DEMO Markets'],
      [38, 'UK retail sales rise more than expected, sterling gains', 'DEMO Markets'],
      [52, 'RBA minutes show board debated holding rates; Aussie dollar firm', 'DEMO Wire'],
    ];
    if (this.opts.blackout) list.unshift([2, 'US CPI release imminent: markets brace for inflation rate surprise', 'DEMO Wire']);
    return list.map(([m, headline, source], i) => ({ id: `demo-n-${i}-${Math.floor(now / 3_600_000)}`, headline, source, published_at: at(m) }));
  }

  async getCalendar(now: number) {
    const at = (m: number) => new Date(now + m * 60_000).toISOString();
    const events: CalendarEvent[] = [
      { id: 'demo-e1', title: 'US Core PCE (simulated)', currency: 'USD', time: at(this.opts.blackout ? 12 : 330), impact: 'HIGH', affected_assets: [] },
      { id: 'demo-e2', title: 'Eurozone Consumer Confidence (simulated)', currency: 'EUR', time: at(190), impact: 'MEDIUM', affected_assets: [] },
      { id: 'demo-e3', title: 'BOE Governor Speech (simulated)', currency: 'GBP', time: at(420), impact: 'HIGH', affected_assets: [] },
      { id: 'demo-e4', title: 'Australia Employment Change (simulated)', currency: 'AUD', time: at(780), impact: 'HIGH', affected_assets: [] },
    ];
    return { available: true, events };
  }
}

/** Used in LIVE mode when no news key is configured: says so instead of faking data. */
export class UnavailableNewsProvider implements NewsProvider {
  readonly name = 'NEWS UNAVAILABLE';
  readonly mode = 'LIVE' as const;
  isAvailable() { return false; }
  async getHeadlines() { return []; }
  async getCalendar() { return { available: false, events: [] as CalendarEvent[] }; }
}
