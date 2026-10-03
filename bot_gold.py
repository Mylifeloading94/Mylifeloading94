"""
XAUUSD bot for TradeLocker (tradelocker-python SDK).

    python3 bot_gold.py --config configs/gold_scalp.json               # DRY RUN (default)
    python3 bot_gold.py --config configs/gold_intraday.json --live     # sends orders

Safety defaults:
  * DRY RUN unless --live is passed. Dry run logs the order it WOULD send.
  * Credentials come ONLY from environment variables, never from a file or argv:
        TL_USERNAME  TL_PASSWORD  TL_SERVER  TL_ACCOUNT_ID  TL_ACC_NUM
        TL_ENV (default https://demo.tradelocker.com)
  * One position at a time, a hard max lot cap, and the stop is attached to the
    order itself, so a crash or lost connection cannot leave a naked position.

STATUS: the signal logic is the SAME code the backtest uses (xau_strategies) and
is verified offline by check_replay.py. The broker-API glue below has NOT been
exercised against a live TradeLocker session by the author. Run it in dry-run on
a demo account and read the log before trusting it.
"""
import argparse, json, logging, math, os, sys, time
import numpy as np
import pandas as pd

import xau_strategies as S

TF_RES = {"1min": "1m", "5min": "5m", "15min": "15m", "1h": "1H"}
TF_MIN = {"1min": 1, "5min": 5, "15min": 15, "1h": 60}
WARMUP_BARS = 900          # ATR-median(500) + EMA200 need a long runway
CONTRACT_OZ = 100.0        # 1.00 lot of XAUUSD = 100 oz (verify against your broker)
LOT_STEP, MIN_LOT = 0.01, 0.01

log = logging.getLogger("gold-bot")


# --------------------------------------------------------------------------
# Pure logic (no network): this is what check_replay.py verifies
# --------------------------------------------------------------------------
def load_config(path):
    c = json.load(open(path))
    for k in ("fam", "tf", "hold", "tp", "p", "risk_pct"):
        if k not in c:
            raise SystemExit(f"config missing '{k}'")
    c.setdefault("validated", False)
    c.setdefault("symbol", "XAUUSD")
    c.setdefault("max_lots", 1.0)
    return c


def latest_signal(bars, cfg):
    """Signal on the LAST bar of `bars`, which MUST be fully closed.

    Returns (direction, risk_distance) with direction in {1, -1, 0}.
    """
    L, Sh, R = S.STRATEGIES[cfg["fam"]](bars, **cfg["p"])
    risk = float(R[-1]) if np.isfinite(R[-1]) else 0.0
    if risk <= 0:
        return 0, 0.0
    if L[-1] and not Sh[-1]:
        return 1, risk
    if Sh[-1] and not L[-1]:
        return -1, risk
    return 0, 0.0


def size_lots(equity, risk_pct, risk_dist, max_lots):
    """Lots such that hitting the stop loses ~risk_pct % of equity."""
    usd = equity * risk_pct / 100.0
    lots = usd / (risk_dist * CONTRACT_OZ)
    lots = math.floor(lots / LOT_STEP) * LOT_STEP
    return round(min(max(lots, 0.0), max_lots), 2)


def drop_unfinished(bars, tf, now=None):
    """Remove the still-forming bar. A bar labelled T closes at T + tf."""
    now = now or pd.Timestamp.now(tz="UTC")
    return bars[bars.index + pd.Timedelta(minutes=TF_MIN[tf]) <= now]


# --------------------------------------------------------------------------
# Broker glue (UNTESTED against a live session)
# --------------------------------------------------------------------------
def connect():
    from tradelocker import TLAPI
    need = ["TL_USERNAME", "TL_PASSWORD", "TL_SERVER"]
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        raise SystemExit(f"set environment variables: {', '.join(miss)}")
    return TLAPI(environment=os.environ.get("TL_ENV", "https://demo.tradelocker.com"),
                 username=os.environ["TL_USERNAME"], password=os.environ["TL_PASSWORD"],
                 server=os.environ["TL_SERVER"],
                 account_id=int(os.environ.get("TL_ACCOUNT_ID", 0)),
                 acc_num=int(os.environ.get("TL_ACC_NUM", 0)), log_level="warning")


def fetch_bars(api, iid, tf):
    """Recent bars at the signal timeframe as an OHLC DataFrame (UTC index)."""
    step_ms = TF_MIN[tf] * 60_000
    end = int(time.time() * 1000)
    start = end - WARMUP_BARS * step_ms * 2          # x2: weekends have no bars
    df = api.get_price_history(iid, resolution=TF_RES[tf], start_timestamp=start, end_timestamp=end)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close"})
    ts = pd.to_datetime(df["t"], unit="ms", utc=True)
    out = df.set_index(ts)[["open", "high", "low", "close"]].astype(float).sort_index()
    return out[~out.index.duplicated(keep="last")]


def open_positions(api):
    p = api.get_all_positions()
    return p if p is not None else pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--live", action="store_true", help="actually send orders")
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--force-unvalidated", action="store_true",
                    help="allow --live on a config that FAILED validation (not recommended)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(a.config)
    if not cfg["validated"]:
        log.warning("config '%s' FAILED validation: %s", cfg.get("name"), cfg.get("warning", "no demonstrated edge"))
        if a.live and not a.force_unvalidated:
            raise SystemExit("refusing --live on an unvalidated config (override: --force-unvalidated)")
    log.info("mode=%s  strategy=%s tf=%s hold=%smin tp=%sR risk=%.2f%%  %s",
             cfg.get("name", "?"), cfg["fam"], cfg["tf"], cfg["hold"], cfg["tp"],
             cfg["risk_pct"], "LIVE ORDERS" if a.live else "DRY RUN")
    api = connect()
    iid = api.get_instrument_id_from_symbol_name(cfg["symbol"])
    entries = {}                      # position_id -> entry timestamp (this process)
    last_bar = None
    while True:
        try:
            now = pd.Timestamp.now(tz="UTC")
            pos = open_positions(api)
            # ---- time exit ----
            for _, row in pos.iterrows():
                pid = int(row["id"])
                t0 = entries.setdefault(pid, now)
                if (now - t0) >= pd.Timedelta(minutes=cfg["hold"]):
                    log.info("TIME EXIT position %s", pid)
                    if a.live:
                        api.close_position(position_id=pid)
            # ---- new signal, once per closed bar ----
            bars = drop_unfinished(fetch_bars(api, iid, cfg["tf"]), cfg["tf"], now)
            if len(bars) >= WARMUP_BARS - 100 and bars.index[-1] != last_bar:
                last_bar = bars.index[-1]
                d, risk = latest_signal(bars, cfg)
                if d != 0 and len(pos) == 0:
                    px = api.get_latest_asking_price(iid) if d == 1 else api.get_latest_bid_price(iid)
                    sl = px - d * risk
                    tp = px + d * cfg["tp"] * risk if cfg["tp"] > 0 else None
                    eq = float(api.get_account_state().get("balance", 0))
                    lots = size_lots(eq, cfg["risk_pct"], risk, cfg["max_lots"])
                    log.info("SIGNAL %s bar=%s px=%.2f sl=%.2f tp=%s lots=%.2f (equity %.0f)",
                             "BUY" if d == 1 else "SELL", last_bar, px, sl,
                             f"{tp:.2f}" if tp else "-", lots, eq)
                    if lots < MIN_LOT:
                        log.warning("size below minimum lot; skipping")
                    elif a.live:
                        oid = api.create_order(iid, quantity=lots, side="buy" if d == 1 else "sell",
                                               type_="market", stop_loss=round(sl, 2),
                                               stop_loss_type="absolute",
                                               take_profit=round(tp, 2) if tp else None,
                                               take_profit_type="absolute" if tp else None)
                        log.info("order id %s", oid)
                    else:
                        log.info("DRY RUN: order not sent")
        except KeyboardInterrupt:
            raise
        except Exception as e:                       # keep running; the stop is on the order
            log.error("loop error: %s: %s", type(e).__name__, e)
        time.sleep(a.poll)


if __name__ == "__main__":
    main()
