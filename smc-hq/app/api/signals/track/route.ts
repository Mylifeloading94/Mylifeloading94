import { NextResponse } from 'next/server';
import { trackOpenSignals } from '@/lib/tracker';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** Re-evaluates open LIVE signals against provider candles (entry / TP / SL). */
export async function POST() { return NextResponse.json(await trackOpenSignals()); }
