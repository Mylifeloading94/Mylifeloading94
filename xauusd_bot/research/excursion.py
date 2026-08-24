"""
Forward-excursion study.

For every raw signal we capture the actual M1 price path that followed it,
relative to the fill price and signed by trade direction. From that one pass we
can evaluate ANY stop/target combination exactly - including which one was
touched first - without re-running the backtester per combination.

This is what lets us search exit models honestly: the entry set is fixed, so
differences between exit rules are not confounded by a different trade sample.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from xauusd_bot.backtesting.simulator import spread_series
from xauusd_bot.config import Config


@dataclass
class Excursions:
    meta: pd.DataFrame        # one row per signal
    fav: np.ndarray           # [n_signals, horizon] favourable excursion, price units
    adv: np.ndarray           # [n_signals, horizon] adverse excursion, price units
    horizon: int

    def __len__(self) -> int:
        return len(self.meta)


def collect(F: pd.DataFrame, R: pd.DataFrame, sig: pd.DataFrame, cfg: Config,
            horizon: int = 240, cooldown: int = 20,
            news_mask: pd.Series | None = None) -> Excursions:
    """Deduplicate clustered signals, then record the forward path of each."""
    d = sig["dir"].values
    sl = sig["sl"].values.astype(float)
    o = F["open"].values.astype(float)
    h = F["high"].values.astype(float)
    lo = F["low"].values.astype(float)
    atr5 = F["M5_atr"].ffill().values.astype(float)
    sp = spread_series(F, cfg).values.astype(float)
    n = len(F)
    nw = news_mask.values if news_mask is not None else np.zeros(n, dtype=bool)

    from xauusd_bot.strategy.base import tradeable_time
    ok_time = tradeable_time(F, cfg)

    rows, idxs = [], []
    last = -10 ** 9
    for i in range(n - horizon - 2):
        if d[i] == 0 or not np.isfinite(sl[i]):
            continue
        if i - last < cooldown:
            continue
        j = i + 1                                   # fill on the NEXT bar's open
        if not ok_time[j] or nw[j] or sp[j] > cfg.costs.max_spread:
            continue
        direction = int(d[i])
        entry = o[j] + direction * (sp[j] / 2 + cfg.costs.entry_slippage)
        struct_dist = abs(entry - sl[i])
        if struct_dist <= 0 or not np.isfinite(struct_dist):
            continue
        rows.append({
            "i": i, "j": j, "ts": F.index[j], "dir": direction, "entry": entry,
            "struct_sl_dist": struct_dist, "atr": atr5[j], "spread": sp[j],
            "strategy": sig["strategy"].values[i], "regime": R["regime"].values[i],
            "regime_conf": R["regime_conf"].values[i],
            "session": F["session"].values[j], "hour": int(F["hour"].values[j]),
            "dow": int(F["dow"].values[j]), "tday": F["tday"].values[j],
            "c_h1": bool(sig["c_h1"].values[i]), "c_m15": bool(sig["c_m15"].values[i]),
            "c_m5mom": bool(sig["c_m5mom"].values[i]), "c_vwap": bool(sig["c_vwap"].values[i]),
            "c_liq": bool(sig["c_liq"].values[i]), "c_ltf": bool(sig["c_ltf"].values[i]),
            "c_retest": bool(sig["c_retest"].values[i]),
            "adx15": F["M15_adx"].values[i], "atr_rank": F["M15_atr_rank"].values[i],
            "vwap_dist": F["M15_vwap_dist_atr"].values[i],
            "ext_atr": (F["close"].values[i] - F["M15_ema_f"].values[i]) / max(atr5[i], 1e-9),
        })
        idxs.append(j)
        last = i

    if not rows:
        return Excursions(pd.DataFrame(), np.zeros((0, horizon)), np.zeros((0, horizon)), horizon)

    meta = pd.DataFrame(rows)
    k = len(meta)
    fav = np.empty((k, horizon), dtype=np.float32)
    adv = np.empty((k, horizon), dtype=np.float32)
    dirs = meta["dir"].values
    entries = meta["entry"].values
    for r, (j, dd, e) in enumerate(zip(idxs, dirs, entries)):
        hh = h[j:j + horizon]; ll = lo[j:j + horizon]
        if dd > 0:
            fav[r] = np.maximum.accumulate(hh - e)
            adv[r] = np.maximum.accumulate(e - ll)
        else:
            fav[r] = np.maximum.accumulate(e - ll)
            adv[r] = np.maximum.accumulate(hh - e)
    fav = np.maximum(fav, 0.0)
    adv = np.maximum(adv, 0.0)
    return Excursions(meta, fav, adv, horizon)


def first_touch(arr: np.ndarray, level: np.ndarray) -> np.ndarray:
    """First column index where the running excursion reaches `level`
    (one level per row), or `horizon` if never."""
    hit = arr >= level[:, None]
    idx = np.where(hit.any(axis=1), hit.argmax(axis=1), arr.shape[1])
    return idx


def evaluate(ex: Excursions, stop_mult: float, target_r: float,
             cfg: Config, be_at_r: float | None = None,
             max_hold: int | None = None, mask: np.ndarray | None = None) -> dict:
    """Exact outcome of 'stop at stop_mult x structural distance, target at
    target_r x that stop' over the recorded paths.

    Ties (stop and target both reached in the same MINUTE) resolve to the STOP -
    the same pessimistic rule the backtester uses.
    """
    if len(ex) == 0:
        return {"n": 0}
    m = np.ones(len(ex), dtype=bool) if mask is None else mask
    stop_dist = ex.meta["struct_sl_dist"].values * stop_mult
    tgt_dist = stop_dist * target_r
    horizon = ex.horizon if max_hold is None else min(max_hold, ex.horizon)
    fav = ex.fav[:, :horizon]; adv = ex.adv[:, :horizon]

    t_stop = first_touch(adv, stop_dist)
    t_tgt = first_touch(fav, tgt_dist)

    if be_at_r is not None:
        # once price reaches be_at_r, the stop moves to entry: a later pullback
        # to entry closes the trade flat instead of at -1R
        t_be = first_touch(fav, stop_dist * be_at_r)
        # after t_be, an adverse move back to ~0 stops us out at breakeven
        r_out = np.zeros(len(ex)); won = np.zeros(len(ex), dtype=bool)
        for k in range(len(ex)):
            if t_tgt[k] < t_stop[k]:
                r_out[k] = target_r; won[k] = True
            elif t_stop[k] < horizon:
                r_out[k] = -1.0
            elif t_be[k] < horizon:
                r_out[k] = 0.0
            else:
                r_out[k] = fav[k, -1] / stop_dist[k] * 0.0  # time exit, flat-ish
                r_out[k] = (fav[k, horizon - 1] - adv[k, horizon - 1]) / stop_dist[k]
                r_out[k] = np.clip(r_out[k], -1.0, target_r)
    else:
        won = t_tgt < t_stop
        r_out = np.where(won, target_r, np.where(t_stop < horizon, -1.0, 0.0))
        timeout = (t_tgt >= horizon) & (t_stop >= horizon)
        # a trade still open at the horizon is closed at market
        r_out = np.where(timeout,
                         np.clip((fav[:, horizon - 1] - adv[:, horizon - 1]) / stop_dist,
                                 -1.0, target_r), r_out)

    # every exit pays the spread again on the way out
    exit_cost_r = (ex.meta["spread"].values / 2 + cfg.costs.entry_slippage) / stop_dist
    r_out = r_out - exit_cost_r

    r = r_out[m]
    if len(r) == 0:
        return {"n": 0}
    wins, losses = r[r > 0], r[r < 0]
    gl = -losses.sum()
    return {
        "n": int(len(r)),
        "win_rate": float(100 * (r > 0).mean()),
        "profit_factor": float(wins.sum() / gl) if gl > 0 else float("inf"),
        "expectancy_r": float(r.mean()),
        "avg_win_r": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_r": float(losses.mean()) if len(losses) else 0.0,
        "payoff": float(wins.mean() / -losses.mean()) if len(losses) and len(wins) else 0.0,
        "total_r": float(r.sum()),
        "r": r,
    }
