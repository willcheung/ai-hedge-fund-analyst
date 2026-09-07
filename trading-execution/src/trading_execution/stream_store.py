from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from trading_execution.config import state_root
from typing import Iterable

from trading_execution.stream_state import Bar1s, QuoteState

DEFAULT_STREAM_DB = state_root() / "market_stream.sqlite3"


class StreamStore:
    def __init__(self, path: str | Path = DEFAULT_STREAM_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS latest_quote (
                  symbol TEXT PRIMARY KEY,
                  contract TEXT NOT NULL,
                  bid REAL,
                  ask REAL,
                  last REAL,
                  spread REAL,
                  bid_size REAL,
                  ask_size REAL,
                  last_size REAL,
                  market_data_type INTEGER,
                  received_at_utc TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bars_1s (
                  symbol TEXT NOT NULL,
                  ts_utc TEXT NOT NULL,
                  open REAL NOT NULL,
                  high REAL NOT NULL,
                  low REAL NOT NULL,
                  close REAL NOT NULL,
                  volume_proxy REAL,
                  bid REAL,
                  ask REAL,
                  spread REAL,
                  PRIMARY KEY(symbol, ts_utc)
                )
                """
            )

    def upsert_latest_quote(self, quote: QuoteState) -> None:
        data = quote.as_dict()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO latest_quote (
                    symbol, contract, bid, ask, last, spread, bid_size, ask_size,
                    last_size, market_data_type, received_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    contract=excluded.contract,
                    bid=excluded.bid,
                    ask=excluded.ask,
                    last=excluded.last,
                    spread=excluded.spread,
                    bid_size=excluded.bid_size,
                    ask_size=excluded.ask_size,
                    last_size=excluded.last_size,
                    market_data_type=excluded.market_data_type,
                    received_at_utc=excluded.received_at_utc
                """,
                (
                    data["symbol"],
                    data["contract"],
                    data["bid"],
                    data["ask"],
                    data["last"],
                    data["spread"],
                    data["bid_size"],
                    data["ask_size"],
                    data["last_size"],
                    data["market_data_type"],
                    data["received_at_utc"],
                ),
            )

    def append_bar_1s(self, bar: Bar1s) -> None:
        data = bar.as_dict()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO bars_1s (
                    symbol, ts_utc, open, high, low, close, volume_proxy, bid, ask, spread
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["symbol"],
                    data["ts_utc"],
                    data["open"],
                    data["high"],
                    data["low"],
                    data["close"],
                    data["volume_proxy"],
                    data["bid"],
                    data["ask"],
                    data["spread"],
                ),
            )

    def latest_quote(self, symbol: str = "MES") -> QuoteState | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM latest_quote WHERE symbol = ?", (symbol,)).fetchone()
        if row is None:
            return None
        return QuoteState(
            symbol=row["symbol"],
            contract=row["contract"],
            bid=row["bid"],
            ask=row["ask"],
            last=row["last"],
            bid_size=row["bid_size"],
            ask_size=row["ask_size"],
            last_size=row["last_size"],
            market_data_type=row["market_data_type"],
            received_at_utc=datetime.fromisoformat(row["received_at_utc"]),
        )

    def latest_bars_1s(self, symbol: str = "MES", *, limit: int = 60) -> list[Bar1s]:
        with self._connect() as conn:
            rows: Iterable[sqlite3.Row] = conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM bars_1s WHERE symbol = ? ORDER BY ts_utc DESC LIMIT ?
                ) ORDER BY ts_utc ASC
                """,
                (symbol, limit),
            ).fetchall()
        return [
            Bar1s(
                symbol=row["symbol"],
                ts_utc=datetime.fromisoformat(row["ts_utc"]),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume_proxy=row["volume_proxy"],
                bid=row["bid"],
                ask=row["ask"],
                spread=row["spread"],
            )
            for row in rows
        ]
