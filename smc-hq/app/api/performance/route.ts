import { NextResponse } from 'next/server';
import { getStore } from '@/lib/database';
import { computePerformance } from '@/lib/stats';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** GET /api/performance?mode=LIVE|DEMO (default LIVE). Statistics are never blended across modes. */
export async function GET(req: Request) {
  const mode = new URL(req.url).searchParams.get('mode') === 'DEMO' ? 'DEMO' : 'LIVE';
  const store = await getStore();
  return NextResponse.json(computePerformance(await store.listSignals(), mode));
}
