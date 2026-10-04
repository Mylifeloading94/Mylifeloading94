import { NextResponse } from 'next/server';
import { getMarketProvider } from '@/lib/market';
import { runtime as rt } from '@/lib/state';
import { TIMEFRAMES, type Timeframe } from '@/types';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** GET /api/market/XAUUSD?tf=M15&count=120 — candles from the active provider, labelled with its data mode. */
export async function GET(req: Request, { params }: { params: { pair: string } }) {
  const u = new URL(req.url);
  const tf = (u.searchParams.get('tf') ?? 'M15') as Timeframe;
  const count = Math.min(500, Number(u.searchParams.get('count')) || 120);
  const pair = params.pair.toUpperCase();
  if (!/^[A-Z]{6}$/.test(pair) || !TIMEFRAMES.includes(tf)) return NextResponse.json({ error: 'Invalid pair or timeframe' }, { status: 400 });
  const p = getMarketProvider();
  try {
    return NextResponse.json({ pair, tf, data_mode: p.mode, provider: p.name, candles: await p.getCandles(pair, tf, count) });
  } catch (e) {
    if (p.mode === 'LIVE') rt().unavailableReason = (e as Error).message; // surfaces in the status bar; cleared by the next successful scan
    return NextResponse.json({ error: (e as Error).message, data_mode: p.mode }, { status: 503 });
  }
}
