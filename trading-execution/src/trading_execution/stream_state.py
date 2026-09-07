from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _utc_second(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).replace(microsecond=0)


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if numeric != numeric else numeric


def _positive_float_or_none(value: Any) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None or numeric <= 0:
        return None
    return numeric


@dataclass(frozen=True)
class QuoteState:
    symbol: str
    contract: str
    bid: float | None
    ask: float | None
    last: float | None
    received_at_utc: datetime
    bid_size: float | None = None
    ask_size: float | None = None
    last_size: float | None = None
    market_data_type: int | None = None

    @property
    def spread(self) -> float | None:
        bid = _positive_float_or_none(self.bid)
        ask = _positive_float_or_none(self.ask)
        if bid is None or ask is None or ask < bid:
            return None
        return round(float(ask) - float(bid), 6)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "contract": self.contract,
            "bid": _positive_float_or_none(self.bid),
            "ask": _positive_float_or_none(self.ask),
            "last": _float_or_none(self.last),
            "spread": self.spread,
            "bid_size": _float_or_none(self.bid_size),
            "ask_size": _float_or_none(self.ask_size),
            "last_size": _float_or_none(self.last_size),
            "market_data_type": self.market_data_type,
            "received_at_utc": _iso(self.received_at_utc),
        }


@dataclass(frozen=True)
class Bar1s:
    symbol: str
    ts_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume_proxy: float
    bid: float | None
    ask: float | None
    spread: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ts_utc": _iso(self.ts_utc),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume_proxy": self.volume_proxy,
            "bid": _float_or_none(self.bid),
            "ask": _float_or_none(self.ask),
            "spread": self.spread,
        }


class Bar1sBuilder:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._bucket: datetime | None = None
        self._open: float | None = None
        self._high: float | None = None
        self._low: float | None = None
        self._close: float | None = None
        self._volume_proxy: float = 0.0
        self._bid: float | None = None
        self._ask: float | None = None
        self._spread: float | None = None

    def add(self, quote: QuoteState) -> Bar1s | None:
        price = _float_or_none(quote.last)
        if price is None:
            return None
        bucket = _utc_second(quote.received_at_utc)
        if self._bucket is None:
            self._start_bucket(bucket, quote, price)
            return None
        if bucket != self._bucket:
            completed = self.flush()
            self._start_bucket(bucket, quote, price)
            return completed
        self._high = max(self._high if self._high is not None else price, price)
        self._low = min(self._low if self._low is not None else price, price)
        self._close = price
        self._volume_proxy += _float_or_none(quote.last_size) or 0.0
        self._bid = _float_or_none(quote.bid)
        self._ask = _float_or_none(quote.ask)
        self._spread = quote.spread
        return None

    def _start_bucket(self, bucket: datetime, quote: QuoteState, price: float) -> None:
        self._bucket = bucket
        self._open = price
        self._high = price
        self._low = price
        self._close = price
        self._volume_proxy = _float_or_none(quote.last_size) or 0.0
        self._bid = _float_or_none(quote.bid)
        self._ask = _float_or_none(quote.ask)
        self._spread = quote.spread

    def flush(self) -> Bar1s | None:
        if self._bucket is None or self._open is None or self._high is None or self._low is None or self._close is None:
            return None
        return Bar1s(
            symbol=self.symbol,
            ts_utc=self._bucket,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume_proxy=self._volume_proxy,
            bid=self._bid,
            ask=self._ask,
            spread=self._spread,
        )


def is_stale(quote: QuoteState | None, *, now: datetime, max_age_seconds: float) -> bool:
    if quote is None:
        return True
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = now.astimezone(timezone.utc) - quote.received_at_utc.astimezone(timezone.utc)
    return age.total_seconds() > max_age_seconds
