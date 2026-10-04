import { NextResponse } from 'next/server';
import { getStore } from '@/lib/database';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** GET /api/signals?mode=LIVE|DEMO&limit=100 */
export async function GET(req: Request) {
  const u = new URL(req.url);
  const mode = u.searchParams.get('mode');
  const limit = Math.min(500, Number(u.searchParams.get('limit')) || 100);
  const store = await getStore();
  const signals = await store.listSignals({ mode: mode === 'LIVE' || mode === 'DEMO' ? mode : undefined, limit });
  return NextResponse.json({ signals });
}
