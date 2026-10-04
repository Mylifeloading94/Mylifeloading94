import { NextResponse } from 'next/server';
import { telegramStatus } from '@/lib/telegram';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() { return NextResponse.json(await telegramStatus()); }
