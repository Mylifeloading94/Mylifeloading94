import path from 'node:path';
import { config } from '@/lib/config';
import { FileStore } from './file';
import { PrismaStore } from './prisma';
import type { Store } from './types';

export * from './types';
export { FileStore } from './file';

const g = globalThis as unknown as { __smcStore?: Promise<Store>; __smcStoreNote?: string };

/**
 * PostgreSQL when DATABASE_URL is set (and reachable); otherwise a local JSON file under DATA_DIR.
 * The fallback is announced in the logs and via /api/health so nobody mistakes it for Postgres.
 */
export function getStore(): Promise<Store> {
  if (!g.__smcStore) {
    g.__smcStore = (async () => {
      if (config.databaseUrl) {
        try {
          const s = await PrismaStore.connect();
          g.__smcStoreNote = 'PostgreSQL via Prisma';
          return s;
        } catch (e) {
          console.error('[db] DATABASE_URL set but Prisma failed — falling back to file store:', (e as Error).message);
          g.__smcStoreNote = `file store (Prisma failed: ${(e as Error).message.split('\n')[0]})`;
        }
      } else g.__smcStoreNote = 'file store (DATABASE_URL not set)';
      return new FileStore(path.resolve(process.cwd(), config.dataDir));
    })();
  }
  return g.__smcStore;
}
export const storeNote = () => g.__smcStoreNote ?? 'not initialised';

/** Test helper: inject a store. */
export function setStoreForTests(s: Store) { g.__smcStore = Promise.resolve(s); g.__smcStoreNote = 'test store'; }
