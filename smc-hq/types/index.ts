import { z } from 'zod';

/* ------------------------------------------------------------------ */
/* Primitives                                                          */
/* ------------------------------------------------------------------ */
export const TIMEFRAMES = ['D1', 'H4', 'H1', 'M15', 'M5'] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

export const DEFAULT_WATCHLIST = [
  'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD',
  'NZDUSD', 'EURJPY', 'GBPJPY', 'CADJPY', 'AUDJPY', 'XAUUSD',
] as const;

/** DEMO data is simulated. LIVE comes from a configured provider. BACKTEST is never mixed in. */
export type DataMode = 'LIVE' | 'DEMO';

export interface Candle { t: number; o: number; h: number; l: number; c: number; v: number }

export const AGENT_IDS = ['market_analyst', 'news_intelligence', 'setup_hunter', 'signal_command'] as const;
export type AgentId = (typeof AGENT_IDS)[number];
export const AGENT_LABELS: Record<AgentId, string> = {
  market_analyst: 'MARKET ANALYST',
  news_intelligence: 'NEWS INTELLIGENCE',
  setup_hunter: 'SETUP HUNTER',
  signal_command: 'SIGNAL COMMAND',
};
export type AgentStatus = 'idle' | 'working' | 'error' | 'paused' | 'offline';

/* ------------------------------------------------------------------ */
/* Inter-agent message schemas (snake_case JSON, validated with zod)   */
/* ------------------------------------------------------------------ */
const trend = z.enum(['bullish', 'bearish', 'ranging']);
const bias = z.enum(['bullish', 'bearish', 'neutral']);
const zone = z.object({ low: z.number(), high: z.number() });
export const newsRiskLevel = z.enum(['low', 'medium', 'high', 'extreme', 'unknown']);
export type NewsRiskLevel = z.infer<typeof newsRiskLevel>;
const dataMode = z.enum(['LIVE', 'DEMO']);

/** Agent 1 output */
export const MarketAnalysisSchema = z.object({
  pair: z.string(),
  timestamp: z.string(),
  data_mode: dataMode,
  price: z.number(),
  session: z.string(),
  htf_bias: bias,
  structure: z.object({ D1: trend, H4: trend, H1: trend, M15: trend, M5: trend }),
  m15_event: z.string(), // e.g. "MSS_BULLISH", "BOS_BEARISH", "NONE"
  m5_event: z.string(),
  liquidity_event: z.enum(['sell_side_sweep', 'buy_side_sweep', 'none']),
  liquidity_detail: z.string(),
  liquidity_quality: z.enum(['equal_levels', 'htf_level', 'swing', 'none']),
  sweep_time: z.number().nullable(),
  sweep_extreme: z.number().nullable(),
  fvg: z.boolean(),
  order_block: z.boolean(),
  breaker_block: z.boolean(),
  premium_discount: z.enum(['premium', 'discount', 'equilibrium']),
  fib_zone: z.string(),
  volatility: z.object({ atr_m15: z.number(), atr_h1: z.number(), regime: z.enum(['low', 'normal', 'high', 'extreme']) }),
  indicators: z.object({ rsi_h1: z.number(), rsi_m15: z.number(), ema_trend_h1: z.enum(['above', 'below', 'mixed']) }),
  levels: z.object({
    pdh: z.number().nullable(), pdl: z.number().nullable(),
    pwh: z.number().nullable(), pwl: z.number().nullable(),
    session_high: z.number().nullable(), session_low: z.number().nullable(),
    support: z.array(z.number()), resistance: z.array(z.number()),
  }),
  candidate: z.object({
    direction: z.enum(['long', 'short']),
    entry_zone: zone,
    stop_loss: z.number(),
    invalidation: z.number(),
    take_profits: z.array(z.number()).length(3),
    tp_projected: z.array(z.boolean()).length(3), // true = R-multiple fallback, not a real liquidity level
    entry_state: z.enum(['in_zone', 'approaching', 'extended', 'invalidated']),
    m5_confirmation: z.boolean(),
    zone_source: z.string(),
  }).nullable(),
  confirmations: z.array(z.string()),
  summary: z.string(),
});
export type MarketAnalysis = z.infer<typeof MarketAnalysisSchema>;

/** Agent 2 output */
export const impactLevel = z.enum(['LOW', 'MEDIUM', 'HIGH', 'EXTREME']);
export type ImpactLevel = z.infer<typeof impactLevel>;
export const NewsItemSchema = z.object({
  id: z.string(),
  headline: z.string(),
  source: z.string(),
  published_at: z.string(),
  impact: impactLevel,
  currencies: z.array(z.string()),
  affected_assets: z.array(z.string()),
  potential_effect: z.string(),
  sentiment: z.number(), // -1..1 (lexicon based, USD-centric polarity is not inferred)
  channel: z.enum(['news', 'social']),
  url: z.string().optional(),
});
export type NewsItem = z.infer<typeof NewsItemSchema>;
export const CalendarEventSchema = z.object({
  id: z.string(),
  title: z.string(),
  currency: z.string(),
  time: z.string(),
  impact: impactLevel,
  affected_assets: z.array(z.string()),
  manual: z.boolean().optional(),
});
export type CalendarEvent = z.infer<typeof CalendarEventSchema>;
export const PairRiskSchema = z.object({
  level: newsRiskLevel,
  blackout: z.boolean(),
  reason: z.string(),
  minutes_to_event: z.number().nullable(),
});
export const NewsIntelSchema = z.object({
  timestamp: z.string(),
  data_mode: dataMode,
  available: z.boolean(),
  calendar_available: z.boolean(),
  items: z.array(NewsItemSchema),
  upcoming_events: z.array(CalendarEventSchema),
  next_event: CalendarEventSchema.nullable(),
  countdown_seconds: z.number().nullable(),
  sentiment: z.object({ score: z.number(), label: z.enum(['risk_off', 'neutral', 'risk_on', 'unknown']) }),
  pair_risk: z.record(PairRiskSchema),
  summary: z.string(),
});
export type NewsIntel = z.infer<typeof NewsIntelSchema>;

/** Agent 3 output (and the document Signal Command receives). Mirrors the spec's example JSON. */
export const ScoreBreakdownSchema = z.object({
  market_structure: z.number(), liquidity: z.number(), fvg_ob: z.number(), htf_alignment: z.number(),
  entry_confirmation: z.number(), risk_reward: z.number(), session: z.number(), news: z.number(), volatility: z.number(),
});
export type ScoreBreakdown = z.infer<typeof ScoreBreakdownSchema>;
export const ValidationCheckSchema = z.object({ id: z.string(), label: z.string(), passed: z.boolean(), detail: z.string() });
export type ValidationCheck = z.infer<typeof ValidationCheckSchema>;

export const ApprovedSetupSchema = z.object({
  pair: z.string(),
  timestamp: z.string(),
  data_mode: dataMode,
  direction: z.enum(['long', 'short']),
  bias: bias,
  market_structure: trend,
  liquidity_event: z.enum(['sell_side_sweep', 'buy_side_sweep']),
  fvg: z.boolean(),
  setup_type: z.string(),
  entry_zone: zone,
  stop_loss: z.number(),
  take_profits: z.array(z.number()).length(3),
  risk_reward: z.number(),
  news_risk: newsRiskLevel,
  confidence_score: z.number(),
  grade: z.enum(['PREMIUM', 'VERY_HIGH', 'HIGH', 'STANDARD']),
  score_breakdown: ScoreBreakdownSchema,
  session: z.string(),
  confirmations: z.array(z.string()),
  technical_reasoning: z.string(),
  news_reasoning: z.string(),
  fingerprint: z.string(),
});
export type ApprovedSetup = z.infer<typeof ApprovedSetupSchema>;

export const SetupEvaluationSchema = z.object({
  pair: z.string(),
  timestamp: z.string(),
  data_mode: dataMode,
  direction: z.enum(['long', 'short']).nullable(),
  confidence_score: z.number(),
  grade: z.enum(['PREMIUM', 'VERY_HIGH', 'HIGH', 'STANDARD', 'REJECTED']),
  score_breakdown: ScoreBreakdownSchema,
  checks: z.array(ValidationCheckSchema),
  approved: z.boolean(),
  rejection_reasons: z.array(z.string()),
  warnings: z.array(z.string()),
  setup: ApprovedSetupSchema.nullable(),
});
export type SetupEvaluation = z.infer<typeof SetupEvaluationSchema>;

export const HunterReportSchema = z.object({
  timestamp: z.string(),
  data_mode: dataMode,
  scanned: z.number(),
  evaluations: z.array(SetupEvaluationSchema),
  approved: z.array(ApprovedSetupSchema),
  rejected_count: z.number(),
  unavailable: z.array(z.string()),
  best: z.object({ pair: z.string(), score: z.number() }).nullable(),
});
export type HunterReport = z.infer<typeof HunterReportSchema>;

/* ------------------------------------------------------------------ */
/* Signals                                                             */
/* ------------------------------------------------------------------ */
export const SIGNAL_STATUSES = ['PENDING', 'ACTIVE', 'TP1', 'TP2', 'TP3', 'STOPPED', 'EXPIRED', 'CANCELLED'] as const;
export type SignalStatus = (typeof SIGNAL_STATUSES)[number];
export type TelegramState = 'NOT_SENT' | 'SENT' | 'FAILED' | 'DEMO_PREVIEW' | 'DISABLED';

export interface Signal {
  id: string;
  signal_id: string;
  data_mode: DataMode;
  pair: string;
  direction: 'long' | 'short';
  entry: number;            // zone midpoint
  entry_low: number;
  entry_high: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
  take_profit_3: number;
  confidence_score: number;
  grade: string;
  risk_reward: number;
  setup_type: string;
  session: string;
  news_risk: string;
  confirmations: string[];
  score_breakdown: ScoreBreakdown;
  technical_reasoning: string;
  news_reasoning: string;
  fingerprint: string;
  timestamp: string;
  status: SignalStatus;
  result: string | null;    // "TP2 +2.4R" / "STOPPED -1R"
  result_r: number | null;
  closed_at: string | null;
  telegram_state: TelegramState;
  telegram_message_id: number | null;
}

/* ------------------------------------------------------------------ */
/* Settings                                                            */
/* ------------------------------------------------------------------ */
export const SettingsSchema = z.object({
  risk_per_trade: z.union([z.literal(0.25), z.literal(0.5), z.literal(1), z.literal(2)]),
  max_daily_signals: z.number().int().min(1).max(20),
  max_simultaneous_signals: z.number().int().min(1).max(20),
  min_rr: z.number().min(1).max(10),
  min_confidence: z.number().min(70).max(100),
  news_blackout_minutes: z.union([z.literal(15), z.literal(30), z.literal(60)]),
  watchlist: z.array(z.string().regex(/^[A-Z]{6}$/)).min(1).max(30),
  manual_events: z.array(CalendarEventSchema).max(50),
});
export type Settings = z.infer<typeof SettingsSchema>;
export const DEFAULT_SETTINGS: Settings = {
  risk_per_trade: 0.5,
  max_daily_signals: 3,
  max_simultaneous_signals: 3,
  min_rr: 2.0,
  min_confidence: 80,
  news_blackout_minutes: 30,
  watchlist: [...DEFAULT_WATCHLIST],
  manual_events: [],
};

/* ------------------------------------------------------------------ */
/* Events on the internal bus                                          */
/* ------------------------------------------------------------------ */
export type BusEventType =
  | 'agent.status' | 'agent.log' | 'market.analysis' | 'news.intel' | 'hunter.progress'
  | 'setup.evaluated' | 'setup.approved' | 'signal.created' | 'telegram.sent' | 'telegram.preview'
  | 'telegram.failed' | 'system' | 'pipeline.start' | 'pipeline.end';

export interface BusEvent<T = unknown> {
  id: string;
  ts: string;
  type: BusEventType;
  from: AgentId | 'system' | 'telegram';
  to: AgentId | 'system' | 'telegram' | 'world';
  payload: T;
}

export interface AgentLogEntry { ts: string; level: 'info' | 'warn' | 'error'; message: string }
export interface AgentSnapshot {
  id: AgentId;
  name: string;
  status: AgentStatus;
  last_run: string | null;
  last_duration_ms: number | null;
  summary: string;          // concise decision factors only — never chain-of-thought
  error: string | null;
  runs: number;
  failures: number;
  logs: AgentLogEntry[];
}
