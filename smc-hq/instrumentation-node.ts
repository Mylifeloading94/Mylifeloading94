/** Optional server-side auto-scan. Enabled with SCAN_INTERVAL_SECONDS (>= 30). Node runtime only. */
const sec = Number(process.env.SCAN_INTERVAL_SECONDS);
const g = globalThis as unknown as { __smcTimer?: NodeJS.Timeout };

if (sec >= 30 && !g.__smcTimer) {
  g.__smcTimer = setInterval(async () => {
    try {
      const { runScan } = await import('./lib/pipeline');
      const { trackOpenSignals } = await import('./lib/tracker');
      await runScan();
      await trackOpenSignals();
    } catch (e) { console.error('[auto-scan]', (e as Error).message); }
  }, sec * 1000);
  console.log(`[smc-hq] auto-scan every ${sec}s`);
}
export {};
