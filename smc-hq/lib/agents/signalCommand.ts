import { z } from 'zod';
import { ApprovedSetupSchema, SettingsSchema, type ApprovedSetup, type Settings, type Signal } from '@/types';
import { getStore } from '@/lib/database';
import { emit } from '@/lib/events/bus';
import { checkSignalLimits, findDuplicate } from '@/lib/risk/limits';
import { formatSignalMessage, sendTelegramSignal, type TelegramProvider } from '@/lib/telegram';
import { runtime } from '@/lib/state';
import { BaseAgent } from './base';

const Input = z.object({
  setup: ApprovedSetupSchema,
  settings: SettingsSchema,
  send_telegram: z.boolean().default(true),
  /** Appended to the fingerprint so repeated *demo* clicks are distinct. Never used for LIVE. */
  demo_salt: z.string().optional(),
});
export type SignalCommandInput = z.infer<typeof Input>;

export const SignalCommandOutputSchema = z.object({
  outcome: z.enum(['created', 'duplicate', 'limit_reached', 'invalid', 'paused']),
  reason: z.string(),
  signal: z.custom<Signal>().nullable(),
  telegram_state: z.enum(['NOT_SENT', 'SENT', 'FAILED', 'DEMO_PREVIEW', 'DISABLED']),
  preview: z.string(),
});
export type SignalCommandOutput = z.infer<typeof SignalCommandOutputSchema>;

/** Agent 4 — final validation, signal ID, persistence, Telegram dispatch (LIVE only) and world update. */
export class SignalCommandAgent extends BaseAgent<SignalCommandInput, SignalCommandOutput> {
  readonly id = 'signal_command' as const;
  readonly inputSchema = Input;
  readonly outputSchema = SignalCommandOutputSchema;
  constructor(private telegram: TelegramProvider, private clock: () => number, opts?: ConstructorParameters<typeof BaseAgent>[0]) { super(opts); }

  /** Independent re-check of the arithmetic — Signal Command does not simply trust upstream. */
  static sanity(s: ApprovedSetup, settings: Settings): string | null {
    const mid = (s.entry_zone.low + s.entry_zone.high) / 2;
    const long = s.direction === 'long';
    if (s.entry_zone.low >= s.entry_zone.high) return 'Entry zone is inverted or empty';
    if (long ? s.stop_loss >= s.entry_zone.low : s.stop_loss <= s.entry_zone.high) return 'Stop-loss is on the wrong side of the entry zone';
    const [t1, t2, t3] = s.take_profits;
    if (long ? !(t1 < t2 && t2 < t3 && t1 > mid) : !(t1 > t2 && t2 > t3 && t1 < mid)) return 'Take-profit levels are not ordered in the trade direction';
    const rr = Math.abs(t2 - mid) / Math.abs(mid - s.stop_loss);
    if (rr + 0.05 < settings.min_rr) return `Recomputed R:R 1:${rr.toFixed(2)} is below the 1:${settings.min_rr} minimum`;
    if (s.confidence_score < settings.min_confidence) return `Confidence ${s.confidence_score} below minimum ${settings.min_confidence}`;
    return null;
  }

  protected async execute({ setup, settings, send_telegram, demo_salt }: SignalCommandInput) {
    const fail = (outcome: SignalCommandOutput['outcome'], reason: string) => ({
      output: { outcome, reason, signal: null, telegram_state: 'NOT_SENT' as const, preview: '' } satisfies SignalCommandOutput,
      summary: `${setup.pair}: ${outcome.replace('_', ' ')} — ${reason}`,
    });
    if (setup.data_mode === 'LIVE' && runtime().paused) return fail('paused', 'Signal generation is paused (/pause)');
    const bad = SignalCommandAgent.sanity(setup, settings);
    if (bad) return fail('invalid', bad);

    const store = await getStore();
    const now = this.clock();
    const recent = await store.listSignals({ mode: setup.data_mode });
    const fingerprint = demo_salt && setup.data_mode === 'DEMO' ? `${setup.fingerprint}|${demo_salt}` : setup.fingerprint;
    const dup = findDuplicate(recent, fingerprint, setup.pair, setup.direction, setup.data_mode);
    if (dup) return fail('duplicate', `Already signalled as ${dup.signal_id}`);
    if (setup.data_mode === 'LIVE') {
      const lim = checkSignalLimits(settings, recent, Date.now());
      if (!lim.allowed) return fail('limit_reached', lim.reason);
    }

    const year = new Date(now).getUTCFullYear();
    const mid = (setup.entry_zone.low + setup.entry_zone.high) / 2;
    const signal: Signal = {
      id: '', signal_id: await store.nextSignalId(setup.data_mode, year), data_mode: setup.data_mode, pair: setup.pair,
      direction: setup.direction, entry: Number(mid.toFixed(5)), entry_low: setup.entry_zone.low, entry_high: setup.entry_zone.high,
      stop_loss: setup.stop_loss, take_profit_1: setup.take_profits[0], take_profit_2: setup.take_profits[1], take_profit_3: setup.take_profits[2],
      confidence_score: setup.confidence_score, grade: setup.grade, risk_reward: setup.risk_reward, setup_type: setup.setup_type,
      session: setup.session, news_risk: setup.news_risk, confirmations: setup.confirmations, score_breakdown: setup.score_breakdown,
      technical_reasoning: setup.technical_reasoning, news_reasoning: setup.news_reasoning, fingerprint,
      timestamp: new Date(setup.data_mode === 'DEMO' ? now : Date.now()).toISOString(), status: 'PENDING', result: null, result_r: null, closed_at: null,
      telegram_state: setup.data_mode === 'DEMO' ? 'DEMO_PREVIEW' : 'NOT_SENT', telegram_message_id: null,
    };
    // Record first, then send: a Telegram outage must never lose a signal.
    let saved = await store.insertSignal(signal);
    emit('signal.created', 'signal_command', 'world', { signal_id: saved.signal_id, pair: saved.pair, data_mode: saved.data_mode });
    const preview = formatSignalMessage(saved);

    let tg: SignalCommandOutput['telegram_state'] = saved.telegram_state;
    if (saved.data_mode === 'DEMO') {
      emit('telegram.preview', 'signal_command', 'telegram', { signal_id: saved.signal_id, text: preview });
    } else if (!send_telegram) {
      tg = 'DISABLED';
    } else {
      const res = await sendTelegramSignal(saved, this.telegram);
      tg = res.ok ? 'SENT' : 'FAILED';
      const upd = await store.updateSignal(saved.signal_id, { telegram_state: tg, telegram_message_id: res.ok ? res.messageId ?? null : null });
      if (upd) saved = upd;
      if (!res.ok) await this.log('error', `Telegram send failed for ${saved.signal_id}: ${res.error}`);
    }
    runtime().lastSignal = saved;
    return {
      output: { outcome: 'created' as const, reason: 'Signal recorded', signal: saved, telegram_state: tg, preview },
      summary: `${saved.signal_id} ${saved.pair} ${saved.direction.toUpperCase()} · ${saved.data_mode === 'DEMO' ? 'demo preview (not sent)' : `Telegram ${tg}`}`,
    };
  }
}
