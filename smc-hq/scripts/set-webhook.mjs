// Registers (or removes) the Telegram webhook so the bot can answer /status, /signals, ...
//   npm run telegram:webhook            → set   (needs PUBLIC_APP_URL, a public https URL)
//   npm run telegram:webhook -- --delete
// Reads TELEGRAM_BOT_TOKEN / PUBLIC_APP_URL / TELEGRAM_WEBHOOK_SECRET from .env (node --env-file).
const token = process.env.TELEGRAM_BOT_TOKEN;
if (!token) { console.error('TELEGRAM_BOT_TOKEN is not set (add it to .env)'); process.exit(1); }
const api = (m, body) => fetch(`https://api.telegram.org/bot${token}/${m}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}) }).then((r) => r.json());

if (process.argv.includes('--delete')) {
  console.log(await api('deleteWebhook', { drop_pending_updates: true }));
} else {
  const base = (process.env.PUBLIC_APP_URL || '').replace(/\/$/, '');
  if (!base.startsWith('https://')) { console.error('PUBLIC_APP_URL must be a public https:// URL (e.g. an ngrok / cloudflared tunnel or your deployment)'); process.exit(1); }
  const body = { url: `${base}/api/telegram/webhook`, allowed_updates: ['message'] };
  if (process.env.TELEGRAM_WEBHOOK_SECRET) body.secret_token = process.env.TELEGRAM_WEBHOOK_SECRET;
  console.log(await api('setWebhook', body));
  console.log(await api('getWebhookInfo'));
}
