// Runs the demo pipeline once in the terminal and prints the Telegram preview. Usage: npx tsx scripts/demo-cli.ts
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';
process.env.DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'smc-cli-'));
(async () => {
  const { runDemoSignal } = await import('../lib/pipeline');
  const r = await runDemoSignal({ pace: false });
  const ev = r.hunter?.evaluations[0];
  console.log('SCORE', ev?.confidence_score, ev?.grade, JSON.stringify(ev?.score_breakdown));
  console.log(ev?.checks.map((c) => `${c.passed ? '✓' : '✗'} ${c.label}: ${c.detail}`).join('\n'));
  console.log('WARN', ev?.warnings);
  console.log(r.signals[0]?.preview ?? r.failures);
})();
