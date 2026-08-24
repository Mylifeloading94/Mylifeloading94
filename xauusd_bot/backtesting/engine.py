"""
Event-driven backtester on the M1 clock.

At every M1 bar the engine, in this order:
   1. rolls day/week risk counters,
   2. manages the OPEN position against THIS bar's high/low (stop first),
   3. only then looks at the signal produced by the PREVIOUS bar's close and
      opens a new position at THIS bar's open.

That ordering is what makes the fills honest: a signal computed from the close
of bar i can only ever be filled at the open of bar i+1.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from xauusd_bot.backtesting import simulator as sim
from xauusd_bot.config import Config
from xauusd_bot.risk.risk_manager import RiskManager


@dataclass
class Position:
    ts_open: pd.Timestamp
    direction: int
    entry: float
    stop: float
    orig_stop: float
    tp1: float
    tp2: float
    lots: float
    lots_open: float
    strategy: str
    regime: str
    regime_conf: float
    setup_score: float
    grade: str
    session: str
    spread_at_entry: float
    atr_at_entry: float
    risk_money: float
    risk_percent: float
    r_distance: float
    entry_slippage: float
    reason: str
    news_status: str
    realised: float = 0.0
    partial_done: bool = False
    be_moved: bool = False
    mfe: float = 0.0
    mae: float = 0.0
    bars_held: int = 0
    exit_slippage: float = 0.0


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series
    rejections: dict
    stats: dict
    risk_events: list = field(default_factory=list)
    signals_seen: int = 0


class Backtester:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def run(self, F: pd.DataFrame, R: pd.DataFrame, sig: pd.DataFrame,
            scores: pd.DataFrame, news_mask: pd.Series | None = None,
            equity0: float | None = None) -> BacktestResult:
        cfg = self.cfg
        eq = cfg.initial_equity if equity0 is None else equity0
        rm = RiskManager(cfg, eq)

        spread = sim.spread_series(F, cfg)
        news = news_mask if news_mask is not None else pd.Series(False, index=F.index)

        o = F["open"].values; h = F["high"].values
        l = F["low"].values;  c = F["close"].values
        atr5 = F["M5_atr"].ffill().values
        sess = F["session"].values
        tday = F["tday"].values
        hour = F["hour"].values
        gap = F["bar_gap_min"].values
        sp = spread.values
        nw = news.values
        sdir = sig["dir"].values
        ssl = sig["sl"].values
        sstrat = sig["strategy"].values
        sreason = sig["reason"].values
        sscore = scores["setup_score"].values
        sgrade = scores["grade"].values
        regime = R["regime"].values
        rconf = R["regime_conf"].values
        idx = F.index

        e = cfg.exits
        thr = cfg.score.threshold
        max_gap = cfg.execution.max_data_age_seconds / 60.0

        pos: Position | None = None
        trades: list[dict] = []
        equity_curve = np.empty(len(F)); equity_curve[:] = np.nan
        signals_seen = 0
        last_exit_i = -10_000
        cooldown = 5   # M1 bars after a close before a new entry (no revenge trading)

        for i in range(1, len(F)):
            ts = idx[i]
            rm.on_bar(ts, tday[i], eq)

            # ---------------- 1. manage the open position on THIS bar
            if pos is not None:
                pos.bars_held += 1
                d = pos.direction
                # MFE / MAE in R
                fav = (h[i] - pos.entry) if d > 0 else (pos.entry - l[i])
                adv = (pos.entry - l[i]) if d > 0 else (h[i] - pos.entry)
                pos.mfe = max(pos.mfe, fav / pos.r_distance)
                pos.mae = max(pos.mae, adv / pos.r_distance)

                bar = {"open": o[i], "high": h[i], "low": l[i], "close": c[i]}
                hit_stop = (l[i] <= pos.stop) if d > 0 else (h[i] >= pos.stop)
                hit_tp1 = (h[i] >= pos.tp1) if d > 0 else (l[i] <= pos.tp1)
                hit_tp2 = (h[i] >= pos.tp2) if d > 0 else (l[i] <= pos.tp2)

                closed = False
                # PESSIMISTIC: stop is checked before any target in the same bar
                if hit_stop:
                    f = sim.exit_fill_stop(bar, pos.stop, d, sp[i], cfg, bool(nw[i]))
                    eq, tr = self._close(pos, f.price, pos.lots_open, ts, eq,
                                         "STOP" if not pos.be_moved else "BE_STOP", f.slippage)
                    trades.append(tr); rm.on_close(tr["pnl"], eq, ts); closed = True
                elif e.tp_model == "partial" and not pos.partial_done and hit_tp1:
                    part = round(pos.lots * e.partial_frac, 8)
                    f = sim.exit_fill_limit(pos.tp1, d, sp[i], cfg)
                    eq, _ = self._partial(pos, f.price, part, eq)
                    pos.partial_done = True
                    pos.lots_open = round(pos.lots - part, 8)
                    # move to breakeven + buffer once TP1 is banked
                    buf = e.be_buffer_atr * pos.atr_at_entry
                    pos.stop = pos.entry + d * buf
                    pos.be_moved = True
                    if hit_tp2:
                        f2 = sim.exit_fill_limit(pos.tp2, d, sp[i], cfg)
                        eq, tr = self._close(pos, f2.price, pos.lots_open, ts, eq, "TP2", 0.0)
                        trades.append(tr); rm.on_close(tr["pnl"], eq, ts); closed = True
                elif hit_tp2 or (e.tp_model == "full" and hit_tp1):
                    tgt = pos.tp2 if hit_tp2 else pos.tp1
                    f = sim.exit_fill_limit(tgt, d, sp[i], cfg)
                    eq, tr = self._close(pos, f.price, pos.lots_open, ts, eq,
                                         "TP2" if hit_tp2 else "TP1", 0.0)
                    trades.append(tr); rm.on_close(tr["pnl"], eq, ts); closed = True

                if not closed and pos is not None:
                    # breakeven / trailing management (no stop is ever widened)
                    r_now = ((c[i] - pos.entry) if d > 0 else (pos.entry - c[i])) / pos.r_distance
                    if not pos.be_moved and r_now >= e.breakeven_at_r:
                        buf = e.be_buffer_atr * pos.atr_at_entry
                        newstop = pos.entry + d * buf
                        if (d > 0 and newstop > pos.stop) or (d < 0 and newstop < pos.stop):
                            pos.stop = newstop; pos.be_moved = True
                    if e.tp_model in ("trail", "partial") and r_now >= e.trail_start_r:
                        trail = c[i] - d * e.trail_atr_mult * atr5[i]
                        if (d > 0 and trail > pos.stop) or (d < 0 and trail < pos.stop):
                            pos.stop = trail
                    # time stop
                    if pos.bars_held >= e.max_hold_minutes:
                        f = sim.exit_fill_market(c[i], d, sp[i], cfg)
                        eq, tr = self._close(pos, f.price, pos.lots_open, ts, eq, "TIME", f.slippage)
                        trades.append(tr); rm.on_close(tr["pnl"], eq, ts); closed = True
                    # end-of-day flat rule (no overnight gold exposure)
                    elif hour[i] >= cfg.sessions.flat_by_utc or \
                            (idx[i].dayofweek == 4 and hour[i] >= cfg.sessions.friday_cutoff_utc + 2):
                        f = sim.exit_fill_market(c[i], d, sp[i], cfg)
                        eq, tr = self._close(pos, f.price, pos.lots_open, ts, eq, "SESSION_END", f.slippage)
                        trades.append(tr); rm.on_close(tr["pnl"], eq, ts); closed = True

                if closed:
                    pos = None
                    last_exit_i = i

            equity_curve[i] = eq

            # ---------------- 2. consider a NEW entry from the PREVIOUS bar's signal
            j = i - 1
            if pos is not None or sdir[j] == 0:
                continue
            signals_seen += 1
            if i - last_exit_i < cooldown:
                rm.rejections["cooldown"] = rm.rejections.get("cooldown", 0) + 1
                continue
            if sscore[j] < thr:
                rm.rejections["setup_score_below_threshold"] = \
                    rm.rejections.get("setup_score_below_threshold", 0) + 1
                continue
            if not np.isfinite(ssl[j]):
                rm.rejections["no_stop"] = rm.rejections.get("no_stop", 0) + 1
                continue
            if sp[i] > cfg.costs.max_spread:
                rm.rejections["spread_blocked"] = rm.rejections.get("spread_blocked", 0) + 1
                continue
            if nw[j] or nw[i]:
                rm.rejections["news_blackout"] = rm.rejections.get("news_blackout", 0) + 1
                continue
            if gap[i] > max_gap:
                rm.rejections["stale_data"] = rm.rejections.get("stale_data", 0) + 1
                continue

            d = int(sdir[j])
            fill = sim.entry_fill(o[i], d, sp[i], cfg)
            entry = fill.price
            stop = float(ssl[j])
            # the stop was computed off the signal bar's close; re-validate it
            # against the ACTUAL fill, and require it still be on the right side
            r_dist = abs(entry - stop)
            if r_dist <= 0 or (d > 0 and stop >= entry) or (d < 0 and stop <= entry):
                rm.rejections["stop_invalid_after_fill"] = \
                    rm.rejections.get("stop_invalid_after_fill", 0) + 1
                continue
            if fill.slippage > cfg.costs.max_slippage:
                rm.rejections["slippage_blocked"] = rm.rejections.get("slippage_blocked", 0) + 1
                continue

            tp1 = entry + d * e.tp1_r * r_dist
            tp2 = entry + d * e.tp2_r * r_dist
            main_tp = tp2 if e.tp_model != "full" else tp1
            dec = rm.approve(entry, stop, main_tp, d)
            if not dec.approved:
                continue

            pos = Position(
                ts_open=ts, direction=d, entry=entry, stop=stop, orig_stop=stop,
                tp1=tp1, tp2=tp2, lots=dec.sizing.lots, lots_open=dec.sizing.lots,
                strategy=str(sstrat[j]), regime=str(regime[j]), regime_conf=float(rconf[j]),
                setup_score=float(sscore[j]), grade=str(sgrade[j]), session=str(sess[i]),
                spread_at_entry=float(sp[i]), atr_at_entry=float(atr5[i]),
                risk_money=dec.sizing.risk_money, risk_percent=dec.sizing.risk_percent_actual,
                r_distance=r_dist, entry_slippage=fill.slippage, reason=str(sreason[j]),
                news_status="blocked" if nw[i] else "clear",
            )
            rm.on_open()

        # force-close anything still open at the end of the dataset
        if pos is not None:
            f = sim.exit_fill_market(c[-1], pos.direction, sp[-1], cfg)
            eq, tr = self._close(pos, f.price, pos.lots_open, idx[-1], eq, "END_OF_DATA", f.slippage)
            trades.append(tr)

        equity_curve[0] = cfg.initial_equity if equity0 is None else equity0
        eqs = pd.Series(equity_curve, index=idx).ffill()
        tdf = pd.DataFrame(trades)
        return BacktestResult(trades=tdf, equity=eqs, rejections=dict(rm.rejections),
                              stats={"final_equity": eq, "max_dd_live": rm.s.max_dd},
                              risk_events=rm.s.lock_events, signals_seen=signals_seen)

    # ------------------------------------------------------------------ helpers
    def _pnl(self, pos: Position, price: float, lots: float) -> float:
        return pos.direction * (price - pos.entry) * lots * self.cfg.instrument.contract_size

    def _partial(self, pos: Position, price: float, lots: float, eq: float):
        gross = self._pnl(pos, price, lots)
        comm = sim.commission(lots, self.cfg)
        pos.realised += gross - comm
        return eq + gross - comm, gross

    def _close(self, pos: Position, price: float, lots: float, ts, eq: float,
               reason: str, slippage: float):
        gross = self._pnl(pos, price, lots)
        comm = sim.commission(lots, self.cfg)
        total = pos.realised + gross - comm
        eq2 = eq + gross - comm
        r_mult = total / pos.risk_money if pos.risk_money else 0.0
        tr = {
            "ts_open": pos.ts_open, "ts_close": ts, "symbol": self.cfg.instrument.symbol,
            "direction": "LONG" if pos.direction > 0 else "SHORT",
            "strategy": pos.strategy, "regime": pos.regime, "regime_conf": pos.regime_conf,
            "setup_score": pos.setup_score, "grade": pos.grade, "session": pos.session,
            "entry": round(pos.entry, 3), "stop": round(pos.orig_stop, 3),
            "tp1": round(pos.tp1, 3), "tp2": round(pos.tp2, 3),
            "exit": round(price, 3), "exit_reason": reason,
            "lots": pos.lots, "risk_money": round(pos.risk_money, 4),
            "risk_percent": round(pos.risk_percent, 4),
            "r_distance": round(pos.r_distance, 3),
            "pnl": round(total, 4), "r_multiple": round(r_mult, 4),
            "mfe_r": round(pos.mfe, 3), "mae_r": round(pos.mae, 3),
            "bars_held": pos.bars_held, "spread": round(pos.spread_at_entry, 3),
            "atr": round(pos.atr_at_entry, 3),
            "entry_slippage": round(pos.entry_slippage, 4),
            "exit_slippage": round(slippage, 4),
            "commission": round(comm, 4),
            "news_status": pos.news_status, "entry_reason": pos.reason,
            "equity_after": round(eq2, 4),
        }
        return eq2, tr
