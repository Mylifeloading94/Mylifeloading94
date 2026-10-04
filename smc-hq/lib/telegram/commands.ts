import { config } from '@/lib/config';
import { getStore } from '@/lib/database';
import { emit } from '@/lib/events/bus';
import { loadSettings } from '@/lib/risk/settings';
import { runtime } from '@/lib/state';
import { formatSignalMessage } from './format';

export const HELP = [
  'SMC Trading HQ commands:',
  '/status — system & agent status',
  '/signals — last 5 live signals',
  '/lastsignal — most recent live signal',
  '/pairs — watchlist',
  '/pause — stop generating signals',
  '/resume — resume signal generation',
].join('\n');

/**
 * Handles one incoming Telegram message. Returns the reply text, or null to stay silent.
 * Only the configured TELEGRAM_CHAT_ID may issue commands (anyone else is ignored — pause/resume are privileged).
 */
export async function handleCommand(text: string, chatId: string | number): Promise<string | null> {
  if (!config.telegramChatId || String(chatId) !== config.telegramChatId) return null;
  const cmd = text.trim().split(/\s+/)[0].toLowerCase().replace(/@\w+$/, '');
  const rt = runtime();
  const store = await getStore();
  switch (cmd) {
    case '/start':
    case '/help':
      return HELP;
    case '/status': {
      const live = (await store.listSignals({ mode: 'LIVE' }));
      const today = live.filter((s) => s.timestamp.slice(0, 10) === new Date().toISOString().slice(0, 10)).length;
      const lines = Object.values(rt.agents).map((a) => `• ${a.name}: ${a.status.toUpperCase()}`);
      return [
        `SMC TRADING HQ — ${config.mode} MODE${config.mode === 'DEMO' ? ' (simulated data)' : ''}`,
        rt.paused ? '⏸ PAUSED' : '▶ RUNNING',
        ...lines,
        `Signals today: ${today}`,
        `Last scan: ${rt.lastScanAt ?? 'never'}`,
      ].join('\n');
    }
    case '/signals': {
      const live = await store.listSignals({ mode: 'LIVE', limit: 5 });
      if (!live.length) return 'No live signals recorded yet.';
      return live.map((s) => `${s.signal_id} · ${s.pair} ${s.direction.toUpperCase()} · ${s.confidence_score}/100 · ${s.status}`).join('\n');
    }
    case '/lastsignal': {
      const [last] = await store.listSignals({ mode: 'LIVE', limit: 1 });
      return last ? formatSignalMessage(last) : 'No live signals recorded yet.';
    }
    case '/pairs':
      return `Watchlist:\n${(await loadSettings()).watchlist.join(', ')}`;
    case '/pause':
      rt.paused = true;
      emit('system', 'telegram', 'world', { level: 'warn', message: 'Paused via Telegram' });
      return '⏸ Signal generation paused. Use /resume to continue.';
    case '/resume':
      rt.paused = false;
      emit('system', 'telegram', 'world', { level: 'info', message: 'Resumed via Telegram' });
      return '▶ Signal generation resumed.';
    default:
      return cmd.startsWith('/') ? `Unknown command.\n\n${HELP}` : null;
  }
}
