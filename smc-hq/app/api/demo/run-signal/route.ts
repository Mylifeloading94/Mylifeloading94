import { NextResponse } from 'next/server';
import { runDemoSignal } from '@/lib/pipeline';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 60;

/** RUN DEMO SIGNAL — simulated XAUUSD pipeline. Body: { blackout?: boolean } simulates a high-impact release. Never sends to Telegram. */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const r = await runDemoSignal({ blackout: !!body?.blackout });
  if (r.skipped) return NextResponse.json({ ok: false, skipped: r.skipped }, { status: 409 });
  const ev = r.hunter?.evaluations[0] ?? null;
  const out = r.signals[0] ?? null;
  return NextResponse.json({
    ok: r.failures.length === 0,
    data_mode: 'DEMO',
    failures: r.failures,
    analysis: r.analyses[0] ?? null,
    news: r.news ? { summary: r.news.summary, pair_risk: r.news.pair_risk['XAUUSD'] ?? null, next_event: r.news.next_event } : null,
    evaluation: ev,
    outcome: out?.outcome ?? (ev && !ev.approved ? 'rejected' : 'none'),
    reason: out?.reason ?? ev?.rejection_reasons[0] ?? null,
    signal: out?.signal ?? null,
    telegram_preview: out?.preview ?? null,
    telegram_sent: false,
  });
}
