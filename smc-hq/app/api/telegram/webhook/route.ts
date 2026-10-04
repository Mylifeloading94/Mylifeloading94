import { NextResponse } from 'next/server';
import { config } from '@/lib/config';
import { handleCommand } from '@/lib/telegram/commands';
import { getTelegramProvider } from '@/lib/telegram';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** Telegram webhook. Protected by TELEGRAM_WEBHOOK_SECRET (header) when set, and by chat-id allow-listing always. */
export async function POST(req: Request) {
  const secret = config.telegramWebhookSecret;
  if (secret && req.headers.get('x-telegram-bot-api-secret-token') !== secret) return NextResponse.json({ ok: false }, { status: 401 });
  const update = await req.json().catch(() => null);
  const msg = update?.message ?? update?.edited_message;
  if (!msg?.text || msg.chat?.id === undefined) return NextResponse.json({ ok: true });
  const reply = await handleCommand(String(msg.text), msg.chat.id);
  if (reply) await getTelegramProvider().sendMessage(reply, String(msg.chat.id));
  return NextResponse.json({ ok: true });
}
