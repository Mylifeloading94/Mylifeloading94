import { z } from 'zod';
import {
  ApprovedSetupSchema, HunterReportSchema, MarketAnalysisSchema, NewsIntelSchema, SettingsSchema,
  type ApprovedSetup, type HunterReport, type MarketAnalysis, type NewsIntel, type Settings, type SetupEvaluation,
} from '@/types';
import { emit } from '@/lib/events/bus';
import { buildFingerprint, gradeOf, riskReward, scoreSetup, technicalReasoning, validateSetup, type NewsRiskInput } from '@/lib/scoring/score';
import { BaseAgent } from './base';

const Input = z.object({
  analyses: z.array(MarketAnalysisSchema),
  news: NewsIntelSchema.nullable(),
  settings: SettingsSchema,
  unavailable: z.array(z.string()).default([]),
});
export type HunterInput = z.infer<typeof Input>;

const label = (zs: string) => (zs === 'FVG+OB' ? 'FVG + Order Block' : zs);

function whyNoModel(a: MarketAnalysis): string {
  if (a.htf_bias === 'neutral') return 'No HTF bias — D1/H4/H1 are not aligned';
  if (a.liquidity_event === 'none') return 'No liquidity sweep found';
  const wantSweep = a.htf_bias === 'bullish' ? 'sell_side_sweep' : 'buy_side_sweep';
  if (a.liquidity_event !== wantSweep) return `Latest sweep is ${a.liquidity_event.replace('_', '-')}, which opposes the ${a.htf_bias} bias`;
  return 'Sweep found, but no post-sweep structure shift with an unmitigated FVG/order block';
}

/** Agent 3 — the decision engine. Scores each pair transparently, validates, and only then approves. */
export class SetupHunterAgent extends BaseAgent<HunterInput, HunterReport> {
  readonly id = 'setup_hunter' as const;
  readonly inputSchema = Input;
  readonly outputSchema = HunterReportSchema;
  constructor(private paceMs = 0, opts?: ConstructorParameters<typeof BaseAgent>[0]) { super(opts); }

  protected async execute({ analyses, news, settings, unavailable }: HunterInput) {
    const evaluations: SetupEvaluation[] = [];
    const approved: ApprovedSetup[] = [];
    let i = 0;
    for (const a of analyses) {
      i++;
      emit('hunter.progress', 'setup_hunter', 'world', { pair: a.pair, index: i, total: analyses.length });
      const ev = this.evaluate(a, news, settings);
      evaluations.push(ev);
      if (ev.setup) approved.push(ev.setup);
      emit('setup.evaluated', 'setup_hunter', 'world', { pair: a.pair, score: ev.confidence_score, approved: ev.approved, grade: ev.grade, reasons: ev.rejection_reasons.slice(0, 2) });
      if (this.paceMs) await new Promise((r) => setTimeout(r, this.paceMs));
    }
    approved.sort((x, y) => y.confidence_score - x.confidence_score);
    const bestEv = [...evaluations].sort((x, y) => y.confidence_score - x.confidence_score)[0];
    const mode = analyses[0]?.data_mode ?? 'DEMO';
    const report: HunterReport = {
      timestamp: new Date().toISOString(), data_mode: mode, scanned: analyses.length, evaluations, approved,
      rejected_count: evaluations.length - approved.length, unavailable,
      best: bestEv ? { pair: bestEv.pair, score: bestEv.confidence_score } : null,
    };
    const summary = approved.length
      ? `${approved.length} approved · best ${approved[0].pair} ${approved[0].confidence_score}/100`
      : `0 approved of ${analyses.length} scanned${bestEv ? ` · best ${bestEv.pair} ${bestEv.confidence_score}/100` : ''}${unavailable.length ? ` · ${unavailable.length} pair(s) data unavailable` : ''}`;
    return { output: report, summary };
  }

  evaluate(a: MarketAnalysis, news: NewsIntel | null, settings: Settings): SetupEvaluation {
    const pr = news?.pair_risk[a.pair];
    const newsRisk: NewsRiskInput = pr ?? { level: 'unknown', blackout: false, reason: 'News Intelligence produced no data for this pair' };
    const { breakdown, total, rr, notes } = scoreSetup(a, newsRisk);
    const base = { pair: a.pair, timestamp: new Date().toISOString(), data_mode: a.data_mode, score_breakdown: breakdown };
    const c = a.candidate;
    if (!c) {
      return { ...base, direction: null, confidence_score: 0, grade: 'REJECTED', checks: validateSetup(a, newsRisk, settings, 0), approved: false, rejection_reasons: [whyNoModel(a)], warnings: [], setup: null };
    }
    const checks = validateSetup(a, newsRisk, settings, rr);
    const reasons = checks.filter((x) => !x.passed).map((x) => `${x.label}: ${x.detail}`);
    const grade = gradeOf(total, settings.min_confidence);
    if (grade === 'REJECTED') reasons.push(`Confidence ${total}/100 is below the ${settings.min_confidence} minimum`);
    const warnings = [...notes];
    if (newsRisk.level === 'unknown') warnings.push(newsRisk.reason);
    if (newsRisk.level === 'high' && !newsRisk.blackout) warnings.push(`Downgraded: ${newsRisk.reason}`);
    const ok = reasons.length === 0 && grade !== 'REJECTED';
    let setup: ApprovedSetup | null = null;
    if (ok) {
      const long = c.direction === 'long';
      const sweep = long ? 'Sell-side' : 'Buy-side';
      const shift = a.confirmations.includes('M15 MSS') ? 'MSS' : 'BOS';
      const confirmations = [...a.confirmations];
      if (rr >= 3) confirmations.push('Strong R:R'); else confirmations.push(`R:R 1:${rr.toFixed(1)}`);
      setup = {
        pair: a.pair, timestamp: new Date().toISOString(), data_mode: a.data_mode, direction: c.direction,
        bias: a.htf_bias, market_structure: a.structure.H4, liquidity_event: long ? 'sell_side_sweep' : 'buy_side_sweep',
        fvg: a.fvg, setup_type: `${sweep} Liquidity Sweep + ${shift} + ${label(c.zone_source)}`,
        entry_zone: c.entry_zone, stop_loss: c.stop_loss, take_profits: c.take_profits as [number, number, number],
        risk_reward: Number(rr.toFixed(2)), news_risk: newsRisk.level, confidence_score: total,
        grade: grade as ApprovedSetup['grade'], score_breakdown: breakdown, session: a.session, confirmations,
        technical_reasoning: technicalReasoning(a), news_reasoning: newsRisk.reason, fingerprint: buildFingerprint(a),
      };
    }
    return { ...base, direction: c.direction, confidence_score: total, grade, checks, approved: ok, rejection_reasons: reasons, warnings, setup };
  }
}
