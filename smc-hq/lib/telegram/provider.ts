import { config } from '@/lib/config';

export interface SendResult { ok: boolean; messageId?: number; error?: string }

/** Swap-able transport. The bot token is read server-side only and never serialised to clients. */
export interface TelegramProvider {
  readonly name: string;
  isConfigured(): boolean;
  sendMessage(text: string, chatId?: string): Promise<SendResult>;
  getMe(): Promise<{ ok: boolean; username?: string; error?: string }>;
}

export class BotApiTelegramProvider implements TelegramProvider {
  readonly name = 'Telegram Bot API';
  constructor(private token: string, private chatId: string, private fetchImpl: typeof fetch = fetch) {}
  isConfigured() { return !!(this.token && this.chatId); }

  private async call(method: string, body?: object): Promise<any> {
    const res = await this.fetchImpl(`https://api.telegram.org/bot${this.token}/${method}`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}),
    });
    return res.json();
  }

  async sendMessage(text: string, chatId = this.chatId): Promise<SendResult> {
    if (!this.isConfigured()) return { ok: false, error: 'Telegram not configured' };
    try {
      const json = await this.call('sendMessage', { chat_id: chatId, text, disable_web_page_preview: true });
      if (!json.ok) return { ok: false, error: String(json.description ?? 'Telegram error') };
      return { ok: true, messageId: json.result?.message_id };
    } catch (e) {
      // never echo the URL (it contains the token)
      return { ok: false, error: `Network error: ${(e as Error).message.replace(this.token, '***')}` };
    }
  }

  async getMe() {
    if (!this.token) return { ok: false, error: 'TELEGRAM_BOT_TOKEN not set' };
    try {
      const json = await this.call('getMe');
      return json.ok ? { ok: true, username: json.result?.username as string } : { ok: false, error: String(json.description) };
    } catch (e) { return { ok: false, error: (e as Error).message.replace(this.token, '***') }; }
  }
}

export const getTelegramProvider = (): TelegramProvider => new BotApiTelegramProvider(config.telegramToken, config.telegramChatId);
