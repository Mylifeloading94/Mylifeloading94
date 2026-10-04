import { z } from 'zod';
import { MarketAnalysisSchema, type Candle, type MarketAnalysis, type Timeframe } from '@/types';
import { buildMarketAnalysis, type CandleSet } from '@/lib/analysis/analyze';
import { sessionAt } from '@/lib/analysis/sessions';
import { MarketDataUnavailableError, type MarketDataProvider } from '@/lib/market/types';
import { BaseAgent } from './base';

const COUNTS: Record<Timeframe, number> = { D1: 60, H4: 150, H1: 320, M15: 320, M5: 300 };
const Input = z.object({ pair: z.string().regex(/^[A-Z]{6}$/) });
export type MarketAnalystInput = z.infer<typeof Input>;

/** Agent 1 — multi-timeframe price-action analysis (D1/H4/H1/M15/M5). */
export class MarketAnalystAgent extends BaseAgent<MarketAnalystInput, MarketAnalysis> {
  readonly id = 'market_analyst' as const;
  readonly inputSchema = Input;
  readonly outputSchema = MarketAnalysisSchema;
  constructor(private provider: MarketDataProvider, opts?: ConstructorParameters<typeof BaseAgent>[0]) { super(opts); }

  protected async execute({ pair }: MarketAnalystInput) {
    const tfs = Object.keys(COUNTS) as Timeframe[];
    const results = await Promise.all(tfs.map((tf) => this.provider.getCandles(pair, tf, COUNTS[tf])));
    const candles = Object.fromEntries(tfs.map((tf, i) => [tf, results[i]])) as CandleSet;
    for (const tf of tfs) if (candles[tf].length < (tf === 'D1' ? 20 : 40)) throw new MarketDataUnavailableError(`${pair} ${tf}: only ${candles[tf].length} candles`);
    const now = this.provider.now();
    const lastM5: Candle = candles.M5[candles.M5.length - 1];
    if (this.provider.mode === 'LIVE' && sessionAt(now) !== 'MARKET CLOSED' && now - lastM5.t > 25 * 60_000) {
      throw new MarketDataUnavailableError(`${pair}: latest M5 candle is ${Math.round((now - lastM5.t) / 60_000)} min old`);
    }
    const analysis = buildMarketAnalysis(pair, candles, this.provider.mode, now);
    return { output: analysis, summary: `${pair}: ${analysis.summary}` };
  }
}
