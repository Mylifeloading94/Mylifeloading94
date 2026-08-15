"""
SMC Sniper — Walk-Forward Validation (spec §20, §22).

Never fits parameters on the full dataset. Splits the available bar range
into rolling train/validation/test folds and, by default, evaluates the
SAME fixed, already-validated config (sniper_smc.py's DISP_MULT/SL_BUF/
OTE_BAND/TP levels) across every fold — the point of walk-forward here is
to prove the edge holds across different time slices, not to re-tune per
fold, per §22 ("do NOT curve-fit ... the goal is robustness, not the
highest possible historical number").

An optional `param_grid` is supported for the rare case a parameter has a
genuine trading rationale to sweep (e.g. testing 2-3 TP multiples) — the
grid is only ever searched on the TRAIN fold, the winner is picked by
VALIDATION performance (never train), and the TEST fold is scored exactly
once with that winner. Reusing test-fold results to pick parameters is
what walk-forward exists to prevent.

Works against any `bt_func(name, lo_i=..., hi_i=..., **params) -> dict`
with at least a "PF" key — i.e. sniper_backtest.sniper_bt.
"""
from __future__ import annotations
from dataclasses import dataclass
from itertools import product
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class Fold:
    train: Tuple[int, int]
    validation: Tuple[int, int]
    test: Tuple[int, int]


def rolling_folds(total_bars: int, n_folds: int = 3, train_frac: float = 0.5, val_frac: float = 0.25) -> List[Fold]:
    """Rolling-origin folds: each fold's test window is unseen by both the
    train and validation windows that precede it. `n_folds` folds are
    spread evenly across the back half of the dataset so early folds still
    have enough warmup history for the underlying indicators."""
    if train_frac + val_frac >= 1.0:
        raise ValueError("train_frac + val_frac must leave room for a test window")
    test_frac = 1.0 - train_frac - val_frac
    folds = []
    # Each fold's test window occupies an equal slice of the final
    # (1 - train_frac) portion of the data, walking forward.
    usable_start = int(total_bars * train_frac * 0.5)  # light warmup guard
    test_span = int(total_bars * test_frac / n_folds) if n_folds else total_bars
    for k in range(n_folds):
        test_end = total_bars - (n_folds - 1 - k) * test_span
        test_start = test_end - test_span
        val_end = test_start
        val_start = val_end - int(total_bars * val_frac)
        train_end = val_start
        train_start = max(0, train_end - int(total_bars * train_frac))
        if train_start < 0 or val_start < train_end:
            continue
        folds.append(Fold(train=(train_start, train_end), validation=(val_start, val_end),
                           test=(test_start, test_end)))
    return folds


def run_walk_forward(
    name: str,
    bt_func: Callable[..., Dict],
    total_bars: int,
    fixed_params: Dict,
    n_folds: int = 3,
    param_grid: Optional[Dict[str, List]] = None,
) -> Dict:
    folds = rolling_folds(total_bars, n_folds)
    results = []
    for i, fold in enumerate(folds):
        chosen_params = dict(fixed_params)
        if param_grid:
            keys = list(param_grid.keys())
            best_val_pf = -1.0
            best_combo = None
            for combo in product(*param_grid.values()):
                trial = dict(fixed_params, **dict(zip(keys, combo)))
                train_r = bt_func(name, lo_i=fold.train[0], hi_i=fold.train[1], **trial)
                if train_r.get("n", 0) < 5:
                    continue  # not enough train signal to trust this combo
                val_r = bt_func(name, lo_i=fold.validation[0], hi_i=fold.validation[1], **trial)
                if val_r.get("PF", 0) > best_val_pf:
                    best_val_pf = val_r.get("PF", 0)
                    best_combo = trial
            chosen_params = best_combo or dict(fixed_params)

        test_r = bt_func(name, lo_i=fold.test[0], hi_i=fold.test[1], **chosen_params)
        results.append({
            "fold": i, "params_used": chosen_params,
            "train_range": fold.train, "validation_range": fold.validation, "test_range": fold.test,
            "test_result": test_r,
        })

    test_pfs = [r["test_result"].get("PF", 0) for r in results if r["test_result"].get("n", 0) > 0]
    test_wrs = [r["test_result"].get("WR", 0) for r in results if r["test_result"].get("n", 0) > 0]
    all_positive = all(pf > 1.0 for pf in test_pfs) if test_pfs else False

    return {
        "symbol": name, "n_folds": len(results), "folds": results,
        "test_pf_by_fold": test_pfs, "test_wr_by_fold": test_wrs,
        "all_folds_positive_pf": all_positive,
        "verdict": ("generalizes: positive PF in every unseen test fold" if all_positive
                    else "does NOT generalize: at least one unseen test fold has PF <= 1.0 — "
                         "treat the strategy as unproven, not just this parameter set"),
    }
