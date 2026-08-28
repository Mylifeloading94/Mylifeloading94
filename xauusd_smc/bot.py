"""
XAUUSD SMC bot — scan, execute on TradeLocker, report to Telegram.

Cycle (default every 60 seconds):
  1. refresh equity, roll daily/weekly counters
  2. manage open positions (TP1 -> close 50% + SL to breakeven, detect closes)
  3. run the gates (session, news, spread, volatility, risk limits)
  4. top-down analysis H4 -> H1 -> M15 -> M5
  5. grade, size, place the market order with SL/TP attached
  6. post the trade to Telegram immediately after the broker confirms
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import time
from typing import Dict, List, Optional

from . import chart, notify, smc
from .config import Config, PIP_USD, USD_PER_PIP_PER_LOT
from .news import NewsFilter
from .risk import RiskManager, money_risk, position_size, utcnow
from .tradelocker import TradeLocker, TradeLockerError, parse_position

log = logging.getLogger("xauusd_smc.bot")

# How far back to pull each timeframe, and how often to refresh it.
TF_SPEC = {
    "H4":  {"days": 40, "refresh": 900},
    "H1":  {"days": 12, "refresh": 600},
    "M15": {"days": 4,  "refresh": 120},
    "M5":  {"days": 2,  "refresh": 0},     # every cycle
}


def setup_logging(cfg: Config, verbose: bool = False) -> None:
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(cfg.log_file))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers, force=True)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


class Bot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.broker = TradeLocker(cfg)
        self.tg = notify.Telegram(cfg)
        self.news = NewsFilter(cfg)
        self.risk: Optional[RiskManager] = None
        self._bars: Dict[str, List[dict]] = {}
        self._bars_at: Dict[str, float] = {}
        self._last_block_msg = ""
        self._cycles = 0

    # -- data --------------------------------------------------------------
    def bars(self, tf: str) -> List[dict]:
        """Cached, CLOSED bars only — the forming candle is always dropped."""
        spec = TF_SPEC[tf]
        now = time.time()
        if tf not in self._bars or now - self._bars_at.get(tf, 0) >= spec["refresh"]:
            raw = self.broker.bars(self.cfg.symbol, tf, spec["days"])
            bars = smc.normalize_bars(raw)
            if bars:
                self._bars[tf] = bars[:-1]     # drop the in-progress candle
                self._bars_at[tf] = now
            elif tf not in self._bars:
                self._bars[tf] = []
        return self._bars.get(tf, [])

    # -- gates -------------------------------------------------------------
    def in_session(self, now: Optional[dt.datetime] = None) -> bool:
        if not self.cfg.session_only:
            return True
        n = now or utcnow()
        if n.weekday() >= 5:
            return False
        mins = n.hour * 60 + n.minute
        for h1, m1, h2, m2 in self.cfg.session_windows:
            if h1 * 60 + m1 <= mins < h2 * 60 + m2:
                return True
        return False

    def gate(self, equity: float, open_positions: int) -> Optional[str]:
        if not self.in_session():
            return "outside London/NY session"
        news = self.news.blackout()
        if news:
            return news
        blocked = self.risk.blocked_reason(equity, open_positions)
        if blocked:
            return blocked
        return None

    # -- position management ----------------------------------------------
    def manage_positions(self) -> Optional[int]:
        """
        TP1 -> close 50% and move the stop to breakeven; report closures.
        Returns the number of positions actually open at the broker (None when
        the poll failed) so positions opened outside the bot still count.
        """
        tracked = dict(self.risk.state.open_trades)
        try:
            live = {p["id"]: p for p in
                    (parse_position(r) for r in self.broker.positions()) if p}
        except TradeLockerError as e:
            log.warning("position poll failed: %s", e)
            return None
        if not tracked:
            return len(live)

        for pos_id, rec in tracked.items():
            pos = live.get(str(pos_id))
            if pos is None:
                if str(pos_id).startswith("dry-"):
                    continue          # dry-run trades never reach the broker
                pnl = float(rec.get("last_pnl", 0.0) or 0.0)
                pnl += float(rec.get("realized_partial", 0.0) or 0.0)
                pips = pnl / (max(rec.get("lots", 0.01), 0.01) * USD_PER_PIP_PER_LOT)
                self.risk.register_close(pos_id, pnl, "closed at broker (SL/TP or manual)")
                self.tg.send(notify.close_alert(
                    rec.get("symbol", self.cfg.symbol), rec.get("side", ""),
                    pnl, pips, "SL / TP / manual close"))
                log.info("position %s closed, pnl %.2f", pos_id, pnl)
                continue

            rec["last_pnl"] = pos["pnl"]
            self.risk.state.open_trades[str(pos_id)] = rec
            if rec.get("be_done"):
                continue

            # Infer the current price from unrealized P/L (no extra quote call).
            entry, lots = rec.get("entry", pos["entry"]), max(pos["qty"], 1e-9)
            move = pos["pnl"] / (lots * USD_PER_PIP_PER_LOT) * PIP_USD
            price = entry + move if rec.get("side") == "buy" else entry - move
            tp1 = rec.get("tp1")
            hit = (price >= tp1) if rec.get("side") == "buy" else (price <= tp1)
            if not tp1 or not hit:
                continue

            close_lots = round(max(self.cfg.min_lots,
                                   pos["qty"] * self.cfg.tp1_close_fraction), 2)
            realized = 0.0
            if self.cfg.dry_run:
                log.info("[dry-run] would close %.2f lots and move SL to BE", close_lots)
            else:
                if self.broker.close_position(str(pos_id), close_lots):
                    realized = money_risk(close_lots, abs(tp1 - entry))
                    rec["realized_partial"] = realized
                else:
                    log.warning("partial close failed on %s", pos_id)
                    continue
                self.broker.modify_position(str(pos_id), stop_loss=entry)
            rec["be_done"] = True
            rec["sl"] = entry
            self.risk.state.open_trades[str(pos_id)] = rec
            self.risk.save()
            self.risk.journal({"event": "tp1", "position_id": pos_id,
                               "closed_lots": close_lots, "realized": realized})
            self.tg.send(notify.breakeven_alert(
                rec.get("side", "").upper(), rec.get("symbol", self.cfg.symbol),
                entry, close_lots))

    # -- execution ---------------------------------------------------------
    def execute(self, setup: smc.Setup, equity: float) -> bool:
        cfg = self.cfg
        risk_usd = equity * cfg.risk_pct(setup.grade)
        lots = position_size(risk_usd, setup.risk_usd_per_lot, cfg)
        if lots <= 0:
            log.warning("computed lot size 0 for risk $%.0f / stop %.2f — skipped",
                        risk_usd, setup.risk_usd_per_lot)
            return False
        actual_risk = money_risk(lots, setup.risk_usd_per_lot)
        log.info("EXECUTE %s %s grade %s entry %.2f sl %.2f tp1 %.2f tp2 %.2f "
                 "lots %.2f risk $%.0f", setup.symbol, setup.side, setup.grade,
                 setup.entry, setup.sl, setup.tp1, setup.tp2, lots, actual_risk)

        order_id, position = "dry-run", None
        if cfg.dry_run:
            log.info("[dry-run] order not sent to the broker")
        else:
            before = self.broker.open_position_ids()
            res = self.broker.place_market_order(cfg.symbol, setup.side, lots,
                                                 setup.sl, setup.tp2)
            if not res["ok"]:
                log.error("order rejected: %s", res["raw"])
                self.tg.send(f"⚠️ <b>ORDER REJECTED</b>\n\n{cfg.symbol} {setup.side.upper()}"
                             f"\n<code>{str(res['raw'])[:300]}</code>")
                return False
            order_id = res["order_id"]
            position = self.broker.new_position_for(cfg.symbol, before)
            if position and position.get("entry"):
                planned, setup.entry = setup.entry, position["entry"]
                if abs(planned - setup.entry) > 0.05:
                    log.info("filled at %.2f (planned %.2f)", setup.entry, planned)

        record = {
            "symbol": cfg.symbol, "side": setup.side, "grade": setup.grade,
            "entry": setup.entry, "sl": setup.sl, "tp1": setup.tp1,
            "tp2": setup.tp2, "lots": lots, "risk_usd": actual_risk,
            "order_id": order_id,
            "position_id": (position or {}).get("id", f"dry-{int(time.time())}"),
            "fingerprint": smc.fingerprint(setup), "reasons": setup.reasons,
            "opened": utcnow().isoformat(),
        }
        self.risk.register_trade(record)
        self.risk.state.last_setup_fingerprint = record["fingerprint"]
        self.risk.save()

        # --- Telegram, immediately after the broker confirms ---------------
        caption = notify.trade_alert(setup, lots, actual_risk, equity,
                                     order_id, cfg.tl_env, cfg.dry_run)
        img = chart.render(self.bars("M15"), f"{cfg.symbol} • 15M", setup.entry,
                           setup.sl, setup.tp1, setup.tp2, setup.direction,
                           os.path.join(cfg.chart_dir, f"{int(time.time())}.png"))
        if img:
            self.tg.photo(img, caption)
        else:
            self.tg.send(caption)
        return True

    # -- one cycle ---------------------------------------------------------
    def cycle(self) -> Optional[smc.Setup]:
        cfg = self.cfg
        self._cycles += 1
        equity = self.broker.equity()
        if self.risk is None:
            self.risk = RiskManager(cfg, equity)
        for msg in self.risk.roll_periods(equity):
            log.info(msg)

        live_n = self.manage_positions()
        open_n = len(self.risk.state.open_trades)
        if live_n is not None:
            open_n = max(open_n, live_n)

        blocked = self.gate(equity, open_n)
        if blocked:
            if blocked != self._last_block_msg:
                log.info("standing down — %s", blocked)
                self._last_block_msg = blocked
                if blocked.startswith(("daily", "weekly")):
                    self.risk.latch_halt(blocked)
                    self.tg.send(notify.halt_alert(blocked,
                                 f"Equity ${equity:,.2f}. No new trades until the "
                                 f"period resets."))
            return None
        self._last_block_msg = ""

        quote = self.broker.quote(cfg.symbol)
        if not quote:
            log.warning("no quote available")
            return None
        if quote["spread"] > cfg.max_spread_usd:
            log.info("spread $%.2f > $%.2f — skipping", quote["spread"],
                     cfg.max_spread_usd)
            return None

        h4, h1, m15, m5 = (self.bars("H4"), self.bars("H1"),
                           self.bars("M15"), self.bars("M5"))
        if min(len(h4), len(h1), len(m15), len(m5)) == 0:
            log.warning("bar data unavailable (h4=%d h1=%d m15=%d m5=%d)",
                        len(h4), len(h1), len(m15), len(m5))
            return None

        a15 = smc.atr(m15, 14)
        if a15 / PIP_USD < cfg.min_atr_pips:
            log.debug("range too tight (M15 ATR $%.2f) — skipping", a15)
            return None

        setup = smc.analyze(cfg.symbol, h4, h1, m15, m5, cfg)
        if setup is None:
            log.debug("cycle %d: no setup", self._cycles)
            return None
        log.info("candidate %s %s grade %s | %s", setup.symbol, setup.direction,
                 setup.grade, " | ".join(setup.reasons))

        if not cfg.grade_allowed(setup.grade):
            log.info("grade %s below MIN_GRADE %s — no trade", setup.grade,
                     cfg.min_grade)
            return setup
        fp = smc.fingerprint(setup)
        if fp == self.risk.state.last_setup_fingerprint:
            log.debug("setup already traded (%s)", fp)
            return setup
        if any(t.get("fingerprint") == fp
               for t in self.risk.state.open_trades.values()):
            return setup

        priced = smc.reprice_for_market_entry(setup, quote["bid"], quote["ask"], cfg)
        if priced is None:
            log.info("setup dropped at repricing: %s", setup.rejected)
            return setup

        self.execute(priced, equity)
        return priced

    # -- run ---------------------------------------------------------------
    def start(self) -> None:
        cfg = self.cfg
        self.broker.login()
        equity = self.broker.equity()
        self.risk = RiskManager(cfg, equity)
        ins = self.broker.instrument(cfg.symbol)
        self.tg.send(
            f"🤖 <b>XAUUSD SMC BOT ONLINE</b>\n\n"
            f"🏦 {cfg.tl_env.upper()} • account <code>{self.broker.account_id}</code>\n"
            f"💵 Equity: <b>${equity:,.2f}</b>\n"
            f"📊 {ins.get('name')} • scanning every {cfg.scan_seconds}s\n"
            f"🎯 Min grade <b>{cfg.min_grade}</b> • risk "
            f"{cfg.risk_pct('A+')*100:.1f}% (A+) / {cfg.risk_pct('A')*100:.1f}% (A)"
            f" / {cfg.risk_pct('B')*100:.1f}% (B)\n"
            f"🛡 Daily stop {cfg.max_consecutive_losses} losses or "
            f"{cfg.daily_loss_pct*100:.0f}% • weekly {cfg.weekly_loss_pct*100:.0f}%"
            + ("\n🧪 <b>DRY RUN</b> — no orders will be sent" if cfg.dry_run else ""))
        log.info("bot online (%s, equity $%.2f, dry_run=%s)",
                 cfg.tl_env, equity, cfg.dry_run)

        failures = 0
        while True:
            started = time.time()
            try:
                self.cycle()
                failures = 0
            except TradeLockerError as e:
                failures += 1
                log.error("broker error (%d): %s", failures, e)
                if failures in (3, 10):
                    self.tg.send(f"⚠️ <b>BROKER ERROR</b>\n\n<code>{str(e)[:300]}</code>")
                time.sleep(min(60 * failures, 300))
            except KeyboardInterrupt:
                log.info("stopped by user")
                self.tg.send("🛑 <b>BOT STOPPED</b>")
                return
            except Exception as e:                      # keep the loop alive
                failures += 1
                log.exception("unexpected error in cycle: %s", e)
                if failures == 3:
                    self.tg.send(f"⚠️ <b>BOT ERROR</b>\n\n<code>{str(e)[:300]}</code>")
            time.sleep(max(1.0, self.cfg.scan_seconds - (time.time() - started)))
