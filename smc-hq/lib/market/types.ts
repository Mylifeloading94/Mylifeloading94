import type { Candle, DataMode, Timeframe } from '@/types';

/** Swap implementations without touching agents. */
export interface MarketDataProvider {
  readonly name: string;
  readonly mode: DataMode;
  /** Epoch ms the provider considers "now" (simulated clock in demo mode). */
  now(): number;
  getCandles(pair: string, tf: Timeframe, count: number): Promise<Candle[]>;
  getPrice(pair: string): Promise<number>;
}

export class MarketDataUnavailableError extends Error {
  constructor(detail: string) {
    super(`MARKET DATA UNAVAILABLE: ${detail}`);
    this.name = 'MarketDataUnavailableError';
  }
}
