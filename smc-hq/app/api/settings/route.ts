import { NextResponse } from 'next/server';
import { loadSettings, updateSettings } from '@/lib/risk/settings';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() { return NextResponse.json(await loadSettings()); }

export async function PUT(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== 'object') return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  const r = await updateSettings(body);
  return r.ok ? NextResponse.json(r.settings) : NextResponse.json({ error: r.error }, { status: 422 });
}
