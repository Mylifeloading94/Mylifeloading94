"""Module 13 - small, pre-declared optimisation grid + walk-forward validation.

Only 4 parameters x 2-3 values (24 configs) are searched, selection uses the TRAINING slice only
(first 4/6 of the window, i.e. 60 of 90 days), the next 1/6 is VALIDATION and the last 1/6 is a
true OUT-OF-SAMPLE slice that never influences any choice."""
import itertools
from .config import cfg as make_cfg, INSTRUMENTS
from .backtest import run, select_pair, window
from .report import metrics

GRID = dict(min_score=[7, 8, 9], bb_dev=[2.0, 2.2], sl_buf_atr=[0.15, 0.30], min_rr=[1.5, 2.0])


def splits(t0, t1):
    a = t0 + (t1 - t0) * 4 / 6; b = t0 + (t1 - t0) * 5 / 6
    return (t0, int(a)), (int(a), int(b)), (int(b), t1)


def pooled(tf, c, ta, tb, syms=INSTRUMENTS):
    tr = []
    for s in syms: tr += select_pair(run(s, tf, c)[0], c, ta, tb)
    return tr


def walk_forward(tf, base=None, min_n=20):
    base = base or make_cfg(); t0, t1 = window(tf, base)
    tr_w, va_w, oo_w = splits(t0, t1); rows = []
    for vals in itertools.product(*GRID.values()):
        c = dict(base, **dict(zip(GRID, vals)))
        m = metrics(pooled(tf, c, *tr_w), *tr_w)
        rows.append((dict(zip(GRID, vals)), m, c))
    ok = [r for r in rows if r[1].get("n", 0) >= min_n]
    pick = max(ok, key=lambda r: (r[1]["avg_r"], r[1]["pf"])) if ok else max(rows, key=lambda r: r[1].get("n", 0))
    params, mtr, c = pick
    return dict(tf=tf, windows=dict(train=tr_w, val=va_w, oos=oo_w), params=params, sufficient=bool(ok),
                train=mtr, val=metrics(pooled(tf, c, *va_w), *va_w), oos=metrics(pooled(tf, c, *oo_w), *oo_w),
                default=dict(train=metrics(pooled(tf, base, *tr_w), *tr_w), val=metrics(pooled(tf, base, *va_w), *va_w),
                             oos=metrics(pooled(tf, base, *oo_w), *oo_w)),
                grid=[(p, {k: m.get(k) for k in ("n", "wr", "pf", "avg_r")}) for p, m, _ in rows])
