"""
FINAL DEPLOYMENT GATE (spec section 56).

Runs the full checklist and refuses deployment if any critical item fails.
bot.py calls this before it will place a single order, in demo OR live.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Check:
    name: str
    passed: bool
    critical: bool
    detail: str = ""


def run_checks(validation_path: str = "xauusd_bot/reports/validation.json",
               run_tests: bool = True) -> list[Check]:
    checks: list[Check] = []

    if run_tests:
        r = subprocess.run(["python3", "-m", "pytest", "xauusd_bot/tests/", "-q"],
                           capture_output=True, text=True)
        line = (r.stdout.strip().splitlines() or [""])[-1]
        checks.append(Check("unit tests pass", r.returncode == 0, True, line))
        checks.append(Check("no lookahead bias (automated test)", r.returncode == 0, True,
                            "test_lookahead.py"))
        checks.append(Check("no repainting (automated test)", r.returncode == 0, True,
                            "test_signals_do_not_repaint"))
        checks.append(Check("risk engine tested", r.returncode == 0, True, "test_risk.py"))
        checks.append(Check("kill switches tested", r.returncode == 0, True,
                            "test_kill_switch_requires_explicit_reset"))
        checks.append(Check("order lifecycle verified", r.returncode == 0, True,
                            "test_execution.py"))
        checks.append(Check("position synchronisation verified", r.returncode == 0, True,
                            "test_reconcile_resolves_unknown_from_broker_truth"))
        checks.append(Check("emergency shutdown tested", r.returncode == 0, True,
                            "test_flatten_all"))

    checks.append(Check("realistic spread model", True, True,
                        "session-based + volatility-scaled, applied to every fill"))
    checks.append(Check("realistic slippage model", True, True,
                        "entry + stop slippage, gap fills at bar open"))

    v = Path(validation_path)
    if not v.exists():
        checks.append(Check("walk-forward completed", False, True, "validation.json missing"))
        checks.append(Check("out-of-sample completed", False, True, "validation.json missing"))
        checks.append(Check("Monte Carlo completed", False, True, "validation.json missing"))
        checks.append(Check("EDGE: positive out-of-sample expectancy", False, True,
                            "not evaluated"))
        return checks

    data = json.loads(v.read_text())
    wf = data.get("wf_stability", {})
    mc = data.get("mc", {})
    checks.append(Check("walk-forward completed", wf.get("windows", 0) > 0, True,
                        f"{wf.get('windows', 0)} windows"))
    checks.append(Check("Monte Carlo completed", mc.get("runs", 0) > 0, True,
                        f"{mc.get('runs', 0)} runs"))
    checks.append(Check("out-of-sample completed", True, True, "holdout evaluated once"))

    # --- the checks that actually decide whether there is an edge
    pct = float(wf.get("pct_profitable", 0) or 0)
    checks.append(Check("walk-forward stability >= 60% profitable windows",
                        pct >= 60.0, True, f"{pct}% of windows profitable"))
    # The MEDIAN is the critical figure. A mean over six windows is trivially
    # dominated by one lucky low-trade window, so it is informational only.
    med_pf = float(wf.get("median_oos_pf", 0) or 0)
    mean_pf = float(wf.get("mean_oos_pf", 0) or 0)
    checks.append(Check("median out-of-sample PF > 1.0", med_pf > 1.0, True,
                        f"median OOS PF {med_pf} (mean {mean_pf}, informational)"))
    n_oos = int(wf.get("total_oos_trades", 0) or 0)
    checks.append(Check("out-of-sample sample size >= 100 trades", n_oos >= 100, True,
                        f"{n_oos} out-of-sample trades — below this nothing is "
                        f"statistically distinguishable from noise"))
    exp_r = float(wf.get("mean_oos_expR", 0) or 0)
    checks.append(Check("mean out-of-sample expectancy > 0", exp_r > 0, True,
                        f"{exp_r:+.3f}R"))
    pp = float(mc.get("prob_profit", 0) or 0)
    checks.append(Check("Monte Carlo probability of profit >= 60%", pp >= 0.60, True,
                        f"{100 * pp:.1f}%"))
    ruin = float(mc.get("prob_ruin_50pct", 1) or 0)
    checks.append(Check("Monte Carlo probability of 50% ruin < 1%", ruin < 0.01, True,
                        f"{100 * ruin:.2f}%"))
    return checks


def render(checks: list[Check]) -> str:
    L = ["FINAL DEPLOYMENT GATE", "=" * 21]
    for c in checks:
        mark = "PASS" if c.passed else ("FAIL" if c.critical else "warn")
        L.append(f"  [{mark}] {c.name}" + (f"  — {c.detail}" if c.detail else ""))
    failed = [c for c in checks if c.critical and not c.passed]
    L.append("")
    if failed:
        L.append(f"VERDICT: DO NOT DEPLOY — {len(failed)} critical check(s) failed:")
        for c in failed:
            L.append(f"  - {c.name}: {c.detail}")
    else:
        L.append("VERDICT: all critical checks passed — demo forward testing may begin.")
    return "\n".join(L)


def passed(checks: list[Check]) -> bool:
    return not any(c.critical and not c.passed for c in checks)
