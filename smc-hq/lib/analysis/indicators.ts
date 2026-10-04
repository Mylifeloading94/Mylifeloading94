import type { Candle } from '@/types';

export function ema(values: number[], n: number): number[] {
  const out: number[] = [];
  const k = 2 / (n + 1);
  let prev = values[0] ?? 0;
  for (let i = 0; i < values.length; i++) {
    prev = i === 0 ? values[0] : values[i] * k + prev * (1 - k);
    out.push(prev);
  }
  return out;
}

export function sma(values: number[], n: number): number[] {
  const out: number[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= n) sum -= values[i - n];
    out.push(i >= n - 1 ? sum / n : NaN);
  }
  return out;
}

/** Wilder RSI. Returns an array aligned with closes (NaN until warmed up). */
export function rsi(closes: number[], n = 14): number[] {
  const out: number[] = new Array(closes.length).fill(NaN);
  if (closes.length <= n) return out;
  let gain = 0, loss = 0;
  for (let i = 1; i <= n; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  gain /= n; loss /= n;
  out[n] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  for (let i = n + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gain = (gain * (n - 1) + Math.max(d, 0)) / n;
    loss = (loss * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

/** Wilder ATR aligned with candles. */
export function atr(c: Candle[], n = 14): number[] {
  const out: number[] = new Array(c.length).fill(NaN);
  if (c.length === 0) return out;
  const tr = c.map((x, i) => (i === 0 ? x.h - x.l : Math.max(x.h - x.l, Math.abs(x.h - c[i - 1].c), Math.abs(x.l - c[i - 1].c))));
  let prev = 0;
  for (let i = 0; i < c.length; i++) {
    if (i < n) { prev += tr[i]; if (i === n - 1) { prev /= n; out[i] = prev; } }
    else { prev = (prev * (n - 1) + tr[i]) / n; out[i] = prev; }
  }
  // back-fill warm-up so callers never see NaN
  const first = out.find((v) => !Number.isNaN(v)) ?? tr[0];
  for (let i = 0; i < c.length; i++) if (Number.isNaN(out[i])) out[i] = first;
  return out;
}

export const last = <T>(a: T[]): T => a[a.length - 1];
