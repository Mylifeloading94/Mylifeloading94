import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { FileStore, setStoreForTests } from '@/lib/database';
import { resetBus } from '@/lib/events/bus';
import { resetRuntime } from '@/lib/state';

export function freshEnv() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'smc-test-'));
  const store = new FileStore(dir);
  setStoreForTests(store);
  resetRuntime();
  resetBus();
  return { dir, store };
}
