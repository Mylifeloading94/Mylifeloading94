import { NextResponse } from 'next/server';
import { getStore } from '@/lib/database';
import { resultFor } from '@/lib/stats';
import { SIGNAL_STATUSES, type SignalStatus } from '@/types';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** PATCH { status } — record an outcome manually. R is derived from the recorded levels. */
export async function PATCH(req: Request, { params }: { params: { signalId: string } }) {
  const body = await req.json().catch(() => null);
  const status = body?.status as SignalStatus;
  if (!SIGNAL_STATUSES.includes(status)) return NextResponse.json({ error: `status must be one of ${SIGNAL_STATUSES.join(', ')}` }, { status: 422 });
  const store = await getStore();
  const s = await store.getSignal(params.signalId);
  if (!s) return NextResponse.json({ error: 'Signal not found' }, { status: 404 });
  const r = resultFor(s, status);
  const final = ['TP3', 'STOPPED', 'EXPIRED', 'CANCELLED'].includes(status);
  const updated = await store.updateSignal(params.signalId, {
    status, result_r: r, result: r === null ? status : `${status} ${r > 0 ? '+' : ''}${r}R`,
    closed_at: final || status === 'TP1' || status === 'TP2' ? new Date().toISOString() : null,
  });
  return NextResponse.json(updated);
}
