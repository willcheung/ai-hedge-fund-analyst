from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from trading_execution.config import state_root
from typing import Any

from trading_execution.broker.ibkr_adapter import IBKRSettings
from trading_execution.broker.ibkr_market_data import IBKRMarketDataAdapter
from trading_execution.stream_state import Bar1sBuilder, QuoteState, is_stale
from trading_execution.stream_store import DEFAULT_STREAM_DB, StreamStore

DEFAULT_HEARTBEAT = state_root() / "stream_heartbeat.json"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if numeric != numeric else numeric


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class StreamStatus:
    ok: bool
    latest_quote_age_seconds: float | None
    latest_quote: dict[str, Any] | None
    bars_1s_count: int
    stale_after_seconds: float

    @classmethod
    def from_store(
        cls,
        store: StreamStore | None = None,
        *,
        now: datetime | None = None,
        stale_after_seconds: float = 15.0,
    ) -> "StreamStatus":
        store = store or StreamStore(DEFAULT_STREAM_DB)
        now = now or datetime.now(timezone.utc)
        quote = store.latest_quote("MES")
        bars = store.latest_bars_1s("MES", limit=60)
        if quote is None:
            return cls(False, None, None, len(bars), stale_after_seconds)
        age = now.astimezone(timezone.utc) - quote.received_at_utc.astimezone(timezone.utc)
        return cls(
            ok=not is_stale(quote, now=now, max_age_seconds=stale_after_seconds),
            latest_quote_age_seconds=round(age.total_seconds(), 3),
            latest_quote=quote.as_dict(),
            bars_1s_count=len(bars),
            stale_after_seconds=stale_after_seconds,
        )

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class MESStreamer:
    """Lean always-on MES L1 streamer.

    Reuses the existing IBKR market-data adapter's connection and contract-resolution
    helpers to avoid duplicate broker plumbing.
    """

    def __init__(
        self,
        settings: IBKRSettings | None = None,
        store: StreamStore | None = None,
        *,
        heartbeat_path: str | Path = DEFAULT_HEARTBEAT,
    ) -> None:
        self.settings = settings or IBKRSettings.from_env()
        self.store = store or StreamStore(DEFAULT_STREAM_DB)
        self.heartbeat_path = Path(heartbeat_path)
        self.builder = Bar1sBuilder("MES")

    def record_tick(self, ticker: Any, contract: Any, *, received_at: datetime | None = None) -> QuoteState | None:
        received_at = received_at or datetime.now(timezone.utc)
        last = _float_or_none(getattr(ticker, "last", None))
        bid = _float_or_none(getattr(ticker, "bid", None))
        ask = _float_or_none(getattr(ticker, "ask", None))
        if last is None and bid is None and ask is None:
            return None
        quote = QuoteState(
            symbol="MES",
            contract=str(getattr(contract, "localSymbol", None) or getattr(contract, "symbol", "MES")),
            bid=bid,
            ask=ask,
            last=last,
            bid_size=_float_or_none(getattr(ticker, "bidSize", None)),
            ask_size=_float_or_none(getattr(ticker, "askSize", None)),
            last_size=_float_or_none(getattr(ticker, "lastSize", None)),
            market_data_type=_int_or_none(getattr(ticker, "marketDataType", None)),
            received_at_utc=received_at,
        )
        self.store.upsert_latest_quote(quote)
        completed_bar = self.builder.add(quote)
        if completed_bar is not None:
            self.store.append_bar_1s(completed_bar)
        self._write_heartbeat(quote)
        return quote

    def _write_heartbeat(self, quote: QuoteState) -> None:
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path.write_text(
            json.dumps(
                {
                    "updated_at_utc": quote.as_dict()["received_at_utc"],
                    "symbol": quote.symbol,
                    "contract": quote.contract,
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "last": quote.last,
                },
                sort_keys=True,
            )
        )

    def run(self, *, duration_seconds: float | None = None, sample_interval: float = 0.25) -> None:
        adapter = IBKRMarketDataAdapter(self.settings)
        ib = None
        contract = None
        try:
            ib, Future = adapter._connect()  # reuse existing tested broker plumbing
            contract = adapter._front_future(ib, Future, "MES")
            ib.reqMarketDataType(1)
            ticker = ib.reqMktData(contract, "", False, False)
            start = time.monotonic()
            while duration_seconds is None or time.monotonic() - start < duration_seconds:
                ib.sleep(sample_interval)
                self.record_tick(ticker, contract)
        finally:
            try:
                final_bar = self.builder.flush()
                if final_bar is not None:
                    self.store.append_bar_1s(final_bar)
            except Exception:
                pass
            try:
                if ib is not None and contract is not None:
                    ib.cancelMktData(contract)
            except Exception:
                pass
            try:
                if ib is not None and ib.isConnected():
                    ib.disconnect()
            except Exception:
                pass
