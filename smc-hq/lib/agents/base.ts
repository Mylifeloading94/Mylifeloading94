import type { ZodType } from 'zod';
import type { AgentId, AgentSnapshot } from '@/types';
import { AGENT_LABELS } from '@/types';
import { emit } from '@/lib/events/bus';
import { runtime } from '@/lib/state';
import { getStore } from '@/lib/database';

export interface AgentResult<O> {
  ok: boolean;
  output: O | null;
  error: string | null;
  summary: string;
  timestamp: string;
  duration_ms: number;
  attempts: number;
}

export class NonRetryableError extends Error {}

export interface AgentOptions { maxAttempts?: number; retryDelayMs?: number }

/**
 * Common contract: validated input → execute() → validated output, with status, logging, retries,
 * timestamps and a concise reasoning summary (decision factors only — never chain-of-thought).
 */
export abstract class BaseAgent<I, O> {
  abstract readonly id: AgentId;
  abstract readonly inputSchema: ZodType<I, any, any>;
  abstract readonly outputSchema: ZodType<O, any, any>;
  protected maxAttempts: number;
  protected retryDelayMs: number;

  constructor(opts: AgentOptions = {}) {
    this.maxAttempts = opts.maxAttempts ?? 3;
    this.retryDelayMs = opts.retryDelayMs ?? 400;
  }

  get name() { return AGENT_LABELS[this.id]; }
  protected abstract execute(input: I): Promise<{ output: unknown; summary: string }>;

  get snapshot(): AgentSnapshot { return runtime().agents[this.id]; }

  setStatus(status: AgentSnapshot['status'], summary?: string) {
    const snap = this.snapshot;
    snap.status = status;
    if (summary) snap.summary = summary;
    emit('agent.status', this.id, 'world', { id: this.id, status, summary: snap.summary });
  }

  async log(level: 'info' | 'warn' | 'error', message: string) {
    const entry = { ts: new Date().toISOString(), level, message };
    const snap = this.snapshot;
    snap.logs.push(entry);
    if (snap.logs.length > 40) snap.logs.shift();
    emit('agent.log', this.id, 'system', { id: this.id, ...entry });
    try { (await getStore()).logActivity({ agent: this.id, ...entry }); } catch { /* logging must never break an agent */ }
  }

  async run(rawInput: unknown): Promise<AgentResult<O>> {
    const started = Date.now();
    const snap = this.snapshot;
    const parsed = this.inputSchema.safeParse(rawInput);
    if (!parsed.success) {
      const msg = `Invalid input: ${parsed.error.issues.map((i) => `${i.path.join('.')} ${i.message}`).join('; ')}`;
      snap.failures++; snap.error = msg;
      this.setStatus('error');
      await this.log('error', msg);
      return { ok: false, output: null, error: msg, summary: msg, timestamp: new Date().toISOString(), duration_ms: 0, attempts: 0 };
    }
    this.setStatus('working');

    let lastErr = 'unknown error';
    for (let attempt = 1; attempt <= this.maxAttempts; attempt++) {
      try {
        const { output, summary } = await this.execute(parsed.data);
        const out = this.outputSchema.safeParse(output);
        if (!out.success) throw new NonRetryableError(`Output failed schema validation: ${out.error.issues[0]?.path.join('.')} ${out.error.issues[0]?.message}`);
        snap.runs++; snap.error = null; snap.last_run = new Date().toISOString(); snap.last_duration_ms = Date.now() - started;
        this.setStatus('idle', summary);
        await this.log('info', `${summary} (${snap.last_duration_ms} ms${attempt > 1 ? `, attempt ${attempt}` : ''})`);
        return { ok: true, output: out.data, error: null, summary, timestamp: snap.last_run, duration_ms: snap.last_duration_ms, attempts: attempt };
      } catch (e) {
        lastErr = (e as Error).message;
        await this.log(attempt < this.maxAttempts && !(e instanceof NonRetryableError) ? 'warn' : 'error', `Attempt ${attempt}/${this.maxAttempts} failed: ${lastErr}`);
        if (e instanceof NonRetryableError || attempt === this.maxAttempts) break;
        if (this.retryDelayMs) await new Promise((r) => setTimeout(r, this.retryDelayMs * 2 ** (attempt - 1)));
      }
    }
    snap.failures++; snap.error = lastErr; snap.last_run = new Date().toISOString();
    this.setStatus('error', `Failed: ${lastErr}`);
    return { ok: false, output: null, error: lastErr, summary: lastErr, timestamp: snap.last_run, duration_ms: Date.now() - started, attempts: this.maxAttempts };
  }
}
