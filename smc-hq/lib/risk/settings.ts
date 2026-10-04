import { SettingsSchema, type Settings } from '@/types';
import { getStore } from '@/lib/database';

export async function loadSettings(): Promise<Settings> {
  const s = await getStore();
  const raw = await s.getSettings();
  const parsed = SettingsSchema.safeParse(raw);
  return parsed.success ? parsed.data : (await import('@/types')).DEFAULT_SETTINGS;
}

export async function updateSettings(patch: unknown): Promise<{ ok: true; settings: Settings } | { ok: false; error: string }> {
  const current = await loadSettings();
  const merged = SettingsSchema.safeParse({ ...current, ...(patch as object) });
  if (!merged.success) return { ok: false, error: merged.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; ') };
  const store = await getStore();
  await store.saveSettings(merged.data);
  return { ok: true, settings: merged.data };
}
