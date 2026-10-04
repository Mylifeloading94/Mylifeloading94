import { NextResponse } from 'next/server';
import { config } from '@/lib/config';
import { getStore, storeNote } from '@/lib/database';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  const store = await getStore();
  return NextResponse.json({ ok: true, mode: config.mode, database: { kind: store.kind, note: storeNote(), counts: await store.counts() }, telegram_configured: config.telegramConfigured, news_configured: !!config.newsKey, x_configured: !!config.xKey });
}
