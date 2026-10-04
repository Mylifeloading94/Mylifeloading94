import type { ApprovedSetup, MarketAnalysis, ScoreBreakdown, Settings, ValidationCheck } from '@/types';

export const MAX_POINTS: ScoreBreakdown = {
  market_structure: 20, liquidity: 15, fvg_ob: 15, htf_alignment: 15,
  entry_confirmation: 10, risk_reward: 10, session: 5, news: 5, volatility: 5,
};

export type Grade = 'PREMIUM' | 'VERY_HIGH' | 'HIGH' | 'STANDARD' | 'REJECTED';
export const gradeOf = (score: number, min: number): Grade =>
  score >= 90 ? 'PREMIUM' : score >= 85 ? 'VERY_HIGH' : score >= 80 ? 'HIGH' : score >= min ? 'STANDARD' : 'REJECTED';

export interface NewsRiskInput { level: 'low' | 'medium' | 'high' | 'extreme' | 'unknown'; blackout: boolean; reason: string }

const ASIA_PAIRS = /JPY|AUD|NZD/;

/** Risk/reward measured from the zone midpoint to TP2 (the primary target). */
export function riskReward(a: MarketAnalysis): number {
  const c = a.candidate;
  if (!c) return 0;
  const mid = (c.entry_zone.low + c.entry_zone.high) / 2;
  const risk = Math.abs(mid - c.stop_loss);
  return risk > 0 ? Math.abs(c.take_profits[1] - mid) / risk : 0;
}

export function sessionPoints(session: string, pair: string): number {
  if (session === 'LONDON/NEW YORK') return 5;
  if (session === 'LONDON' || session === 'NEW YORK') return 4;
  if (session === 'ASIAN') return ASIA_PAIRS.test(pair) ? 4 : 1;
  return 0;
}

/**
 * Transparent additive score. Every point comes from a stated observation below.
 * RSI / moving averages are reported by the Market Analyst but are NOT scored — indicator agreement is not an
 * independent confirmation of price-action structure.
 */
export function scoreSetup(a: MarketAnalysis, news: NewsRiskInput): { breakdown: ScoreBreakdown; total: number; rr: number; notes: string[] } {
  const c = a.candidate;
  const b: ScoreBreakdown = { market_structure: 0, liquidity: 0, fvg_ob: 0, htf_alignment: 0, entry_confirmation: 0, risk_reward: 0, session: 0, news: 0, volatility: 0 };
  const notes: string[] = [];
  if (!c) return { breakdown: b, total: 0, rr: 0, notes: ['No complete entry model (needs sweep + structure shift + FVG/OB)'] };
  const want = c.direction === 'long' ? 'bullish' : 'bearish';
  const align = (t: string, full: number) => (t === want ? full : t === 'ranging' ? Math.min(2, full) : 0);

  // Market structure (20)
  b.market_structure += align(a.structure.H4, 8) + align(a.structure.H1, 6);
  if (a.confirmations.includes('M15 MSS')) b.market_structure += 6;
  else if (a.confirmations.includes('M15 BOS')) b.market_structure += 3;

  // Liquidity (15)
  const sideOk = (c.direction === 'long' && a.liquidity_event === 'sell_side_sweep') || (c.direction === 'short' && a.liquidity_event === 'buy_side_sweep');
  if (sideOk) {
    b.liquidity += a.liquidity_quality === 'swing' ? 6 : a.liquidity_quality === 'none' ? 0 : 10;
    const ageH = a.sweep_time ? (Date.parse(a.timestamp) - a.sweep_time) / 3_600_000 : 99;
    b.liquidity += ageH <= 3 ? 5 : ageH <= 8 ? 4 : ageH <= 24 ? 2 : 0;
    if (ageH > 24) notes.push('Liquidity sweep is stale (>24h)');
  }

  // Imbalance / order block (15)
  if (a.fvg) b.fvg_ob += 8;
  if (a.order_block) b.fvg_ob += 4;
  if (c.zone_source === 'FVG+OB') b.fvg_ob += 1; // FVG and OB overlap = confluence
  b.fvg_ob = Math.min(15, b.fvg_ob);

  // HTF alignment (15)
  b.htf_alignment += a.structure.D1 === want ? 5 : 0;
  b.htf_alignment += a.structure.H4 === want ? 5 : 0;
  const favourable = c.direction === 'long' ? 'discount' : 'premium';
  b.htf_alignment += a.premium_discount === favourable ? 5 : a.premium_discount === 'equilibrium' ? 2 : 0;
  if (a.premium_discount !== favourable && a.premium_discount !== 'equilibrium') notes.push(`Entry is in ${a.premium_discount} for a ${c.direction}`);

  // Entry confirmation (10)
  b.entry_confirmation += c.entry_state === 'in_zone' ? 5 : c.entry_state === 'approaching' ? 2 : 0;
  b.entry_confirmation += c.m5_confirmation ? 5 : 0;

  // Risk / reward (10) — capped when the TP2 is a projection rather than real liquidity
  const rr = riskReward(a);
  const rrPts = rr >= 3 ? 10 : rr >= 2.5 ? 8 : rr >= 2 ? 6 : rr >= 1.5 ? 2 : 0;
  b.risk_reward = c.tp_projected[1] ? Math.min(rrPts, 6) : rrPts;
  if (c.tp_projected[1]) notes.push('TP2 is a projected R-multiple, not a liquidity level');

  b.session = sessionPoints(a.session, a.pair);
  b.news = news.blackout ? 0 : news.level === 'low' ? 5 : news.level === 'medium' ? 3 : news.level === 'unknown' ? 2 : news.level === 'high' ? 1 : 0;
  b.volatility = a.volatility.regime === 'normal' ? 5 : a.volatility.regime === 'extreme' ? 0 : 3;

  const total = Object.values(b).reduce((x, y) => x + y, 0);
  return { breakdown: b, total, rr, notes };
}

/** The ten pre-approval validations (+ an independent-confirmation gate). */
export function validateSetup(a: MarketAnalysis, news: NewsRiskInput, settings: Settings, rr: number): ValidationCheck[] {
  const c = a.candidate;
  const want = c ? (c.direction === 'long' ? 'bullish' : 'bearish') : null;
  const chk = (id: string, label: string, passed: boolean, detail: string): ValidationCheck => ({ id, label, passed, detail });
  if (!c || !want) {
    return [chk('entry_model', 'Complete entry model', false, 'No sweep + structure shift + imbalance sequence found')];
  }
  const mid = (c.entry_zone.low + c.entry_zone.high) / 2;
  const risk = Math.abs(mid - c.stop_loss);
  const sideOk = (c.direction === 'long' && a.liquidity_event === 'sell_side_sweep') || (c.direction === 'short' && a.liquidity_event === 'buy_side_sweep');
  const tp = c.take_profits;
  const ordered = c.direction === 'long' ? tp[0] < tp[1] && tp[1] < tp[2] && tp[0] > c.entry_zone.high : tp[0] > tp[1] && tp[1] > tp[2] && tp[0] < c.entry_zone.low;
  const slSide = c.direction === 'long' ? c.stop_loss < Math.min(c.invalidation, c.entry_zone.low) : c.stop_loss > Math.max(c.invalidation, c.entry_zone.high);
  const riskAtr = risk / a.volatility.atr_m15;
  const shift = a.confirmations.some((x) => x === 'M15 MSS' || x === 'M15 BOS');
  const tradable = !['MARKET CLOSED', 'OFF-HOURS'].includes(a.session);
  const groups = [
    a.structure.H4 === want && shift,
    sideOk,
    a.fvg || a.order_block,
    a.htf_bias === want,
    c.entry_state === 'in_zone' && c.m5_confirmation,
  ].filter(Boolean).length;
  return [
    chk('htf_bias', '1. HTF directional bias', a.htf_bias === want, `Bias ${a.htf_bias.toUpperCase()} vs ${c.direction.toUpperCase()} model`),
    chk('structure', '2. Market structure', a.structure.H4 === want && shift, `H4 ${a.structure.H4}, M15 ${shift ? 'shift confirmed' : 'no shift'}`),
    chk('liquidity', '3. Liquidity event', sideOk, a.liquidity_detail),
    chk('entry', '4. Entry confirmation', c.entry_state === 'in_zone' && c.m5_confirmation, `Price ${c.entry_state.replace('_', ' ')}, M5 trigger ${c.m5_confirmation ? 'yes' : 'no'}`),
    chk('stop', '5. Logical stop-loss', slSide && riskAtr >= 0.8 && riskAtr <= 10, `SL ${c.stop_loss} (${riskAtr.toFixed(1)}× M15 ATR from entry), beyond manipulation extreme ${c.invalidation}`),
    chk('tp', '6. Logical take-profit', ordered, `TP ${tp.join(' / ')}${c.tp_projected.some(Boolean) ? ' (some projected)' : ''}`),
    chk('rr', '7. Risk / reward', rr >= settings.min_rr, `1:${rr.toFixed(2)} to TP2 (min 1:${settings.min_rr.toFixed(1)})`),
    chk('volatility', '8. Current volatility', a.volatility.regime !== 'extreme', `Regime ${a.volatility.regime}, M15 ATR ${a.volatility.atr_m15}`),
    chk('news', '9. News risk', !news.blackout && news.level !== 'extreme', `${news.level.toUpperCase()} — ${news.reason}`),
    chk('session', '10. Trading session', tradable, a.session),
    chk('independent', '+ Independent confirmation groups', groups >= 4, `${groups}/5 groups (structure, liquidity, imbalance, HTF bias, entry trigger)`),
  ];
}

export function technicalReasoning(a: MarketAnalysis): string {
  const c = a.candidate!;
  return [
    `HTF bias ${a.htf_bias} (D1 ${a.structure.D1}, H4 ${a.structure.H4}, H1 ${a.structure.H1})`,
    a.liquidity_detail,
    `${a.m15_event.replace('_', ' ')} on M15 after the sweep`,
    `Entry zone from ${c.zone_source}; price in ${a.premium_discount}; ${a.fib_zone}`,
  ].join('. ');
}

export function buildFingerprint(a: MarketAnalysis): string {
  return `${a.pair}|${a.candidate?.direction}|${a.sweep_time ?? 'x'}`;
}

export type { ApprovedSetup };
