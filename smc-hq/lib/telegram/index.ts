import type { Signal } from '@/types';
import { getStore } from '@/lib/database';
import { emit } from '@/lib/events/bus';
import { formatSignalMessage } from './format';
import { getTelegramProvider, type TelegramProvider } from './provider';

export * from './provider';
export { formatSignalMessage } from './format';

/**
 * Sends an approved LIVE signal. DEMO signals are refused unconditionally — they are previews only.
 * Called only by Signal Command after it has validated and recorded the signal.
 */
export async function sendTelegramSignal(signal: Signal, provider: TelegramProvider = getTelegramProvider()) {
  if (signal.data_mode !== 'LIVE') return { ok: false as const, error: 'Demo signals are never sent to Telegram' };
  if (!provider.isConfigured()) return { ok: false as const, error: 'Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)' };
  const text = formatSignalMessage(signal);
  const res = await provider.sendMessage(text);
  const store = await getStore();
  await store.logTelegram({ ts: new Date().toISOString(), signal_id: signal.signal_id, direction: 'outbound', ok: res.ok, message_id: res.messageId ?? null, text, error: res.error ?? null });
  emit(res.ok ? 'telegram.sent' : 'telegram.failed', 'signal_command', 'telegram', { signal_id: signal.signal_id, error: res.error ?? null });
  return res.ok ? { ok: true as const, messageId: res.messageId } : { ok: false as const, error: res.error ?? 'unknown' };
}

let statusCache: { at: number; value: { state: 'CONNECTED' | 'NOT_CONFIGURED' | 'ERROR'; detail: string } } | null = null;
export async function telegramStatus(provider: TelegramProvider = getTelegramProvider()) {
  if (!provider.isConfigured()) return { state: 'NOT_CONFIGURED' as const, detail: 'Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID' };
  if (statusCache && Date.now() - statusCache.at < 60_000) return statusCache.value;
  const me = await provider.getMe();
  const value = me.ok ? { state: 'CONNECTED' as const, detail: me.username ? `@${me.username}` : 'bot ok' } : { state: 'ERROR' as const, detail: me.error ?? 'unreachable' };
  statusCache = { at: Date.now(), value };
  return value;
}
