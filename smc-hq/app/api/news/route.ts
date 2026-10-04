import { NextResponse } from 'next/server';
import { runtime as rt } from '@/lib/state';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** Latest News Intelligence report (populated by scans). */
export async function GET() {
  const n = rt().news;
  return n ? NextResponse.json(n) : NextResponse.json({ empty: true, message: 'No news report yet — run a scan.' });
}
