import { NextResponse } from 'next/server';
import { runScan } from '@/lib/pipeline';
import { trackOpenSignals } from '@/lib/tracker';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 300;

/** Runs one full scan of the watchlist (live provider when configured, otherwise DEMO). */
export async function POST() {
  const r = await runScan({ paceMs: 120, stageDelayMs: 400 });
  const tracking = r.mode === 'LIVE' ? await trackOpenSignals().catch(() => null) : null;
  return NextResponse.json({
    mode: r.mode, skipped: r.skipped, scanned: r.analyses.length, failures: r.failures,
    approved: r.hunter?.approved.length ?? 0, signals: r.signals.map((s) => ({ outcome: s.outcome, reason: s.reason, signal_id: s.signal?.signal_id ?? null })),
    best: r.hunter?.best ?? null, tracking,
  });
}
