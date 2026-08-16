"""
SMC Sniper — Trade Journal (spec §24, §26 module 16).

Every field the spec requires, one row per trade, append-only CSV (plus a
JSON-lines mirror for programmatic consumers like monte_carlo.py and
backtest_report.py). Two calls: `journal_entry(...)` at trade open,
`journal_exit(...)` to fill in the exit fields once the trade closes.
"""
from __future__ import annotations
import csv
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, Path]

DEFAULT_CSV_PATH = Path("smc_sniper_journal.csv")
DEFAULT_JSONL_PATH = Path("smc_sniper_journal.jsonl")

FIELDS = [
    "trade_id", "datetime_utc", "symbol", "direction",
    "entry", "stop_loss", "take_profit", "position_size_lots",
    "account_equity", "dollar_risk", "risk_pct", "planned_rr",
    "setup_score", "htf_bias", "liquidity_swept", "structure_event",
    "order_block", "fvg", "premium_discount", "session", "news_status",
    "reason_for_entry",
    # filled on exit:
    "exit_datetime_utc", "exit_price", "result", "r_multiple", "reason_for_exit",
]


@dataclass
class JournalEntry:
    trade_id: str
    datetime_utc: str
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    position_size_lots: float
    account_equity: float
    dollar_risk: float
    risk_pct: float
    planned_rr: float
    setup_score: int
    htf_bias: str
    liquidity_swept: str
    structure_event: str
    order_block: str
    fvg: str
    premium_discount: str
    session: str
    news_status: str
    reason_for_entry: str
    exit_datetime_utc: Optional[str] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None          # "win" | "loss" | "breakeven"
    r_multiple: Optional[float] = None
    reason_for_exit: Optional[str] = None


def _ensure_header(path: Path) -> None:
    if not path.exists():
        with path.open("w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def _rewrite_row(csv_path: Path, entry: JournalEntry) -> None:
    """CSV has no in-place row update, so on exit we rewrite the file with
    the matching trade_id row replaced. Journals are small (a handful of
    trades/day per the sniper model), so this is cheap and simple."""
    rows = []
    if csv_path.exists():
        with csv_path.open() as f:
            rows = list(csv.DictReader(f))
    row = {k: v for k, v in asdict(entry).items()}
    replaced = False
    for i, r in enumerate(rows):
        if r["trade_id"] == entry.trade_id:
            rows[i] = row
            replaced = True
            break
    if not replaced:
        rows.append(row)
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _append_jsonl(path: Path, entry: JournalEntry) -> None:
    with path.open("a") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def log_entry(
    trade_id: str,
    symbol: str,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    position_size_lots: float,
    account_equity: float,
    dollar_risk: float,
    risk_pct: float,
    setup_score: int,
    htf_bias: str,
    liquidity_swept: str,
    structure_event: str,
    order_block: str,
    fvg: str,
    premium_discount: str,
    session: str,
    news_status: str,
    reason_for_entry: str,
    csv_path: PathLike = DEFAULT_CSV_PATH,
    jsonl_path: PathLike = DEFAULT_JSONL_PATH,
    now: Optional[datetime] = None,
) -> JournalEntry:
    csv_path, jsonl_path = Path(csv_path), Path(jsonl_path)
    now = now or datetime.now(timezone.utc)
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    je = JournalEntry(
        trade_id=trade_id, datetime_utc=now.isoformat(), symbol=symbol, direction=direction,
        entry=entry, stop_loss=stop_loss, take_profit=take_profit,
        position_size_lots=position_size_lots, account_equity=account_equity,
        dollar_risk=round(dollar_risk, 2), risk_pct=round(risk_pct, 4), planned_rr=rr,
        setup_score=setup_score, htf_bias=htf_bias, liquidity_swept=liquidity_swept,
        structure_event=structure_event, order_block=order_block, fvg=fvg,
        premium_discount=premium_discount, session=session, news_status=news_status,
        reason_for_entry=reason_for_entry,
    )
    _ensure_header(csv_path)
    _rewrite_row(csv_path, je)
    _append_jsonl(jsonl_path, je)
    return je


def log_exit(
    trade_id: str,
    exit_price: float,
    r_multiple: float,
    reason_for_exit: str,
    csv_path: PathLike = DEFAULT_CSV_PATH,
    jsonl_path: PathLike = DEFAULT_JSONL_PATH,
    now: Optional[datetime] = None,
) -> None:
    csv_path, jsonl_path = Path(csv_path), Path(jsonl_path)
    now = now or datetime.now(timezone.utc)
    if not csv_path.exists():
        raise FileNotFoundError(f"No journal at {csv_path} — log_entry must run before log_exit.")
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["trade_id"] == trade_id:
            r["exit_datetime_utc"] = now.isoformat()
            r["exit_price"] = exit_price
            r["result"] = "win" if r_multiple > 0.05 else ("loss" if r_multiple < -0.05 else "breakeven")
            r["r_multiple"] = r_multiple
            r["reason_for_exit"] = reason_for_exit
            break
    else:
        raise KeyError(f"trade_id {trade_id} not found in journal {csv_path}")
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    # append a lightweight exit event to the jsonl mirror too
    with jsonl_path.open("a") as f:
        f.write(json.dumps({"trade_id": trade_id, "exit_datetime_utc": now.isoformat(),
                             "exit_price": exit_price, "r_multiple": r_multiple,
                             "reason_for_exit": reason_for_exit, "event": "exit"}) + "\n")
