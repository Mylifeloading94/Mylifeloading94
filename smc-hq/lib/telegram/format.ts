import type { Signal } from '@/types';

const digits = (pair: string) => (pair.endsWith('JPY') ? 3 : pair === 'XAUUSD' ? 2 : 5);
const f = (pair: string, n: number) => n.toFixed(digits(pair));

export function formatSignalMessage(s: Signal): string {
  const p = s.pair;
  const bias = s.direction === 'long' ? 'BULLISH' : 'BEARISH';
  const lines = [
    '🔥 SMC TRADING SIGNAL',
    '',
    '━━━━━━━━━━━━━━━━━━',
    '',
    '📊 PAIR:', p, '',
    '🧠 BIAS:', bias, '',
    '📍 SETUP:', s.setup_type, '',
    '🎯 ENTRY:', `${f(p, s.entry_low)} - ${f(p, s.entry_high)}`, '',
    '🛑 STOP LOSS:', f(p, s.stop_loss), '',
    '✅ TAKE PROFIT 1:', f(p, s.take_profit_1), '',
    '✅ TAKE PROFIT 2:', f(p, s.take_profit_2), '',
    '🚀 TAKE PROFIT 3:', f(p, s.take_profit_3), '',
    '⚖️ RISK / REWARD:', `1 : ${s.risk_reward.toFixed(1)}`, '',
    '📈 CONFIDENCE SCORE:', `${Math.round(s.confidence_score)} / 100`, '',
    '🕐 SESSION:', s.session, '',
    '📰 NEWS RISK:', s.news_risk.toUpperCase(), '',
    '🔎 CONFIRMATIONS:', ...s.confirmations.map((c) => `✓ ${c}`), '',
    '━━━━━━━━━━━━━━━━━━', '',
    '⚠️ Educational analysis — not financial advice. Confidence score is not a probability of winning.', '',
    'Signal ID:', s.signal_id,
  ];
  return lines.join('\n');
}
