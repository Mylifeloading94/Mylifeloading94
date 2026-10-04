import { NextResponse } from 'next/server';
import { getTelegramProvider } from '@/lib/telegram';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** Sends a clearly-labelled connectivity test message (not a signal). */
export async function POST() {
  const tg = getTelegramProvider();
  if (!tg.isConfigured()) return NextResponse.json({ ok: false, error: 'Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env' }, { status: 400 });
  const r = await tg.sendMessage('✅ SMC Trading HQ — Telegram connection test. This is not a trading signal.');
  return NextResponse.json(r, { status: r.ok ? 200 : 502 });
}
