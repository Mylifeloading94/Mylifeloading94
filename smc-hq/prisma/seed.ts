/**
 * Seed script: `npm run db:seed`
 *  - stores the default risk settings if none exist
 *  - runs ONE real pass of the demo pipeline so the world isn't empty (signal is recorded as DEMO, never LIVE)
 * It never fabricates results or performance statistics.
 */
try { process.loadEnvFile?.('.env'); } catch { /* no .env — fine */ }

async function main() {
  const { getStore, storeNote } = await import('../lib/database');
  const { DEFAULT_SETTINGS } = await import('../types');
  const { runDemoSignal } = await import('../lib/pipeline');
  const store = await getStore();
  const counts = await store.counts();
  if (counts.signals === 0) await store.saveSettings(DEFAULT_SETTINGS);
  console.log(`Database: ${storeNote()}`);
  const r = await runDemoSignal({ pace: false });
  const s = r.signals[0];
  console.log(s?.outcome === 'created' ? `Seeded demo signal ${s.signal!.signal_id} (${s.signal!.pair}, ${s.signal!.confidence_score}/100) — DEMO DATA` : `No demo signal created: ${s?.outcome ?? r.failures.join('; ')}`);
  console.log('Counts:', await store.counts());
  process.exit(0);
}
main().catch((e) => { console.error(e); process.exit(1); });
