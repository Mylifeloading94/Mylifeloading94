"""SQLite trade journal with CSV export (spec section 39)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_open TEXT, ts_close TEXT, symbol TEXT, direction TEXT,
    strategy TEXT, regime TEXT, regime_conf REAL,
    setup_score REAL, grade TEXT, session TEXT,
    entry REAL, stop REAL, tp1 REAL, tp2 REAL,
    exit REAL, exit_reason TEXT, entry_reason TEXT,
    lots REAL, risk_money REAL, risk_percent REAL, r_distance REAL,
    pnl REAL, r_multiple REAL, mfe_r REAL, mae_r REAL,
    bars_held INTEGER, spread REAL, atr REAL,
    entry_slippage REAL, exit_slippage REAL, commission REAL,
    news_status TEXT, equity_after REAL, mode TEXT
);
CREATE INDEX IF NOT EXISTS ix_trades_open ON trades(ts_open);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, regime TEXT, regime_conf REAL, strategy TEXT, direction INTEGER,
    setup_score REAL, spread REAL, decision TEXT, reject_reason TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, kind TEXT, detail TEXT
);
"""


class TradeJournal:
    def __init__(self, path: str | Path = "xauusd_bot/logs/journal.sqlite"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def record_trade(self, trade: dict, mode: str = "backtest") -> None:
        cols = [c[1] for c in self.conn.execute("PRAGMA table_info(trades)")][1:]
        row = {c: trade.get(c) for c in cols}
        row["mode"] = mode
        for k in ("ts_open", "ts_close"):
            if row.get(k) is not None:
                row[k] = str(row[k])
        q = f"INSERT INTO trades ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        self.conn.execute(q, [row[c] for c in cols])
        self.conn.commit()

    def record_trades(self, df: pd.DataFrame, mode: str = "backtest") -> int:
        for _, r in df.iterrows():
            self.record_trade(r.to_dict(), mode)
        return len(df)

    def record_signal(self, **kw) -> None:
        cols = ["ts", "regime", "regime_conf", "strategy", "direction",
                "setup_score", "spread", "decision", "reject_reason"]
        self.conn.execute(
            f"INSERT INTO signals ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [str(kw.get(c)) if c == "ts" else kw.get(c) for c in cols])
        self.conn.commit()

    def record_event(self, kind: str, detail: str, ts=None) -> None:
        self.conn.execute("INSERT INTO events (ts, kind, detail) VALUES (?,?,?)",
                          (str(ts or pd.Timestamp.utcnow()), kind, detail))
        self.conn.commit()

    def to_df(self, mode: str | None = None) -> pd.DataFrame:
        q = "SELECT * FROM trades" + (" WHERE mode=?" if mode else "")
        return pd.read_sql_query(q, self.conn, params=(mode,) if mode else None)

    def export_csv(self, path: str, mode: str | None = None) -> str:
        df = self.to_df(mode)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        return path

    def close(self) -> None:
        self.conn.close()
