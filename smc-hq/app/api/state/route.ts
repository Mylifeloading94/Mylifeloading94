import { NextResponse } from 'next/server';
import { buildSnapshot } from '@/lib/snapshot';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** Full world snapshot (no secrets). */
export async function GET() {
  return NextResponse.json(await buildSnapshot());
}
