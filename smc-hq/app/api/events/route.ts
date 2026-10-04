import { recentEvents, subscribe } from '@/lib/events/bus';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** Server-Sent Events: live agent-bus stream for the 3D world. */
export async function GET(req: Request) {
  const enc = new TextEncoder();
  let unsub: (() => void) | undefined;
  let beat: ReturnType<typeof setInterval> | undefined;
  const stream = new ReadableStream({
    start(controller) {
      const send = (obj: unknown) => { try { controller.enqueue(enc.encode(`data: ${JSON.stringify(obj)}\n\n`)); } catch { /* closed */ } };
      controller.enqueue(enc.encode('retry: 3000\n\n'));
      for (const e of recentEvents(20)) send(e);
      unsub = subscribe(send);
      beat = setInterval(() => { try { controller.enqueue(enc.encode(': ping\n\n')); } catch { /* closed */ } }, 15000);
      req.signal.addEventListener('abort', () => { unsub?.(); if (beat) clearInterval(beat); try { controller.close(); } catch { /* already closed */ } });
    },
    cancel() { unsub?.(); if (beat) clearInterval(beat); },
  });
  return new Response(stream, { headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache, no-transform', connection: 'keep-alive', 'x-accel-buffering': 'no' } });
}
