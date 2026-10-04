'use client';
import { useEffect, useState } from 'react';
import { TIMEFRAMES, type Candle, type Timeframe } from '@/types';
import { CandleChart } from '../charts/CandleChart';
import { Chip, Empty, Json, Loading, num, trendTone, ViewShell } from '../ui/Comic';
import type { Snapshot } from '../world-types';

export function MarketView({ snap, onClose, onScan, scanning }: { snap: Snapshot | null; onClose: () => void; onScan: () => void; scanning: boolean }) {
  const analyses = snap ? Object.values(snap.analyses) : [];
  const [pair, setPair] = useState<string | null>(null);
  const [tf, setTf] = useState<Timeframe>('M15');
  const [candles, setCandles] = useState<Candle[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const sel = analyses.find((a) => a.pair === pair) ?? analyses.find((a) => a.candidate) ?? analyses[0];

  useEffect(() => {
    if (!sel) return;
    let dead = false;
    setCandles(null); setErr(null);
    fetch(`/api/market/${sel.pair}?tf=${tf}&count=90`, { cache: 'no-store' }).then(async (r) => {
      const j = await r.json();
      if (dead) return;
      if (!r.ok) setErr(j.error ?? 'MARKET DATA UNAVAILABLE'); else setCandles(j.candles);
    }).catch((e) => !dead && setErr(e.message));
    return () => { dead = true; };
  }, [sel?.pair, tf]); // eslint-disable-line react-hooks/exhaustive-deps

  const c = sel?.candidate;
  return (
    <ViewShell title="MARKET ANALYST" color="#2fa8ff" onClose={onClose} right={<button className="btn sm" onClick={onScan} disabled={scanning}>{scanning ? 'SCANNING…' : 'SCAN NOW'}</button>}>
      {!analyses.length ? <Empty title="NO ANALYSIS YET" hint="Run a scan (or RUN DEMO SIGNAL) and the Market Analyst will report structure, liquidity and imbalances per pair." /> : (
        <div style={{ display: 'grid', gap: 14 }}>
          {snap?.mode === 'DEMO' && <Chip tone="demo">DEMO DATA — simulated candles, not a live market</Chip>}
          <table className="tbl">
            <thead><tr><th>PAIR</th><th>PRICE</th><th>HTF BIAS</th><th>D1</th><th>H4</th><th>H1</th><th>M15</th><th>M5</th><th>MODEL</th></tr></thead>
            <tbody>
              {analyses.map((a) => (
                <tr key={a.pair} onClick={() => setPair(a.pair)} style={{ cursor: 'pointer', background: sel?.pair === a.pair ? 'rgba(47,168,255,.2)' : undefined }}>
                  <td><b>{a.pair}</b></td><td>{a.price}</td>
                  <td><Chip tone={a.htf_bias === 'neutral' ? 'warn' : trendTone(a.htf_bias)}>{a.htf_bias.toUpperCase()}</Chip></td>
                  {(['D1', 'H4', 'H1', 'M15', 'M5'] as const).map((k) => <td key={k}><Chip tone={trendTone(a.structure[k])}>{a.structure[k].slice(0, 4).toUpperCase()}</Chip></td>)}
                  <td>{a.candidate ? <Chip tone="info">{a.candidate.direction.toUpperCase()} · {a.candidate.entry_state.replace('_', ' ')}</Chip> : <span style={{ opacity: 0.6 }}>none</span>}</td>
                </tr>))}
            </tbody>
          </table>
          {sel && (
            <div style={{ display: 'grid', gap: 10 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                <b className="font-comic" style={{ fontSize: 24 }}>{sel.pair}</b>
                {TIMEFRAMES.map((t) => <button key={t} className={`btn sm ${t === tf ? '' : 'blue'}`} onClick={() => setTf(t)}>{t}</button>)}
                <Chip tone={sel.data_mode === 'DEMO' ? 'demo' : 'good'}>{sel.data_mode === 'DEMO' ? 'DEMO DATA' : 'LIVE'}</Chip>
              </div>
              {err ? <Empty title="MARKET DATA UNAVAILABLE" hint={err} /> : !candles ? <Loading what="LOADING CANDLES" /> : (
                <CandleChart candles={candles} overlay={tf === 'M15' || tf === 'M5' || tf === 'H1' ? (c ? { zone: { ...c.entry_zone, color: c.direction === 'long' ? '#2bff88' : '#ff3b3b' }, lines: [{ y: c.stop_loss, color: '#ff3b3b', label: 'SL' }, ...c.take_profits.map((y, i) => ({ y, color: '#2bff88', label: `TP${i + 1}` }))] } : undefined) : undefined} />)}
              <div className="stat" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: '6px 18px', fontSize: 13 }}>
                <div><b style={{ fontSize: 14 }}>Liquidity:</b> {sel.liquidity_detail}</div>
                <div><b style={{ fontSize: 14 }}>FVG / OB / Breaker:</b> {sel.fvg ? 'FVG ✓' : 'FVG ✗'} · {sel.order_block ? 'OB ✓' : 'OB ✗'} · {sel.breaker_block ? 'Breaker ✓' : 'Breaker ✗'}</div>
                <div><b style={{ fontSize: 14 }}>Premium/Discount:</b> {sel.premium_discount.toUpperCase()} · {sel.fib_zone}</div>
                <div><b style={{ fontSize: 14 }}>Volatility:</b> {sel.volatility.regime.toUpperCase()} (ATR M15 {sel.volatility.atr_m15}, H1 {sel.volatility.atr_h1})</div>
                <div><b style={{ fontSize: 14 }}>Session:</b> {sel.session} · M15 {sel.m15_event.replace('_', ' ')} · M5 {sel.m5_event.replace('_', ' ')}</div>
                <div><b style={{ fontSize: 14 }}>Info only (not scored):</b> RSI H1 {sel.indicators.rsi_h1}, M15 {sel.indicators.rsi_m15} · EMA trend {sel.indicators.ema_trend_h1}</div>
                <div><b style={{ fontSize: 14 }}>PDH/PDL:</b> {num(sel.levels.pdh)} / {num(sel.levels.pdl)} · <b>PWH/PWL:</b> {num(sel.levels.pwh)} / {num(sel.levels.pwl)}</div>
                <div><b style={{ fontSize: 14 }}>Support / Resistance:</b> {sel.levels.support.join(', ') || '—'} / {sel.levels.resistance.join(', ') || '—'}</div>
              </div>
              {c && <div className="stat" style={{ fontSize: 13 }}>
                <b className="font-comic" style={{ fontSize: 20 }}>ENTRY MODEL: {c.direction.toUpperCase()} on {c.zone_source}</b>
                Entry {c.entry_zone.low} – {c.entry_zone.high} · SL {c.stop_loss} · Invalidation {c.invalidation} · TP {c.take_profits.join(' / ')}{c.tp_projected.some(Boolean) ? ' (some projected)' : ''} · State: {c.entry_state.replace('_', ' ')} · M5 trigger {c.m5_confirmation ? 'yes' : 'no'}
                <div style={{ marginTop: 4 }}>{sel.confirmations.map((x) => <Chip key={x} tone="good">✓ {x}</Chip>)}</div>
              </div>}
              <details><summary style={{ cursor: 'pointer' }}>Raw agent output (JSON)</summary><Json data={sel} /></details>
            </div>)}
        </div>)}
    </ViewShell>
  );
}
