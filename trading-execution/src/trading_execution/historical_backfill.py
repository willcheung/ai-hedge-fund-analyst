from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from trading_execution.broker.ibkr_adapter import IBKRSettings
from trading_execution.broker.ibkr_market_data import IBKRMarketDataAdapter
from trading_execution.stream_state import Bar1s, QuoteState
from trading_execution.stream_store import DEFAULT_STREAM_DB, StreamStore


def _bar_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"unsupported_bar_date={value!r}")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _float_attr(obj: Any, name: str, default: float = 0.0) -> float:
    value = getattr(obj, name, default)
    if value is None:
        return default
    return float(value)


def ibkr_bar_to_bar1s(raw_bar: Any, *, symbol: str) -> Bar1s:
    return Bar1s(
        symbol=symbol,
        ts_utc=_bar_datetime(getattr(raw_bar, "date")),
        open=_float_attr(raw_bar, "open"),
        high=_float_attr(raw_bar, "high"),
        low=_float_attr(raw_bar, "low"),
        close=_float_attr(raw_bar, "close"),
        volume_proxy=_float_attr(raw_bar, "volume"),
        bid=None,
        ask=None,
        spread=None,
    )


def store_historical_bars(
    store: StreamStore,
    raw_bars: Iterable[Any],
    *,
    symbol: str = "MES",
    contract: str = "MES",
    update_latest_quote: bool = True,
) -> dict[str, Any]:
    bars = [ibkr_bar_to_bar1s(raw, symbol=symbol) for raw in raw_bars]
    bars.sort(key=lambda bar: bar.ts_utc)
    for bar in bars:
        store.append_bar_1s(bar)

    if update_latest_quote and bars:
        latest = bars[-1]
        store.upsert_latest_quote(
            QuoteState(
                symbol=symbol,
                contract=contract,
                bid=None,
                ask=None,
                last=latest.close,
                last_size=latest.volume_proxy,
                market_data_type=1,
                received_at_utc=latest.ts_utc,
            )
        )

    return {
        "symbol": symbol,
        "contract": contract,
        "stored_bars": len(bars),
        "first_bar_utc": bars[0].ts_utc.isoformat() if bars else None,
        "last_bar_utc": bars[-1].ts_utc.isoformat() if bars else None,
    }


class MESHistoricalBackfiller:
    def __init__(self, settings: IBKRSettings | None = None, store: StreamStore | None = None) -> None:
        self.settings = settings or IBKRSettings.from_env()
        self.store = store or StreamStore(DEFAULT_STREAM_DB)

    def backfill_rth(self, *, symbol: str = "MES", duration: str = "1 D", bar_size: str = "1 min") -> dict[str, Any]:
        # Use a separate client id from the always-on streamer/quote probes.
        adapter = IBKRMarketDataAdapter(replace(self.settings, client_id=self.settings.client_id + 30))
        ib = None
        contract = None
        try:
            ib, Future = adapter._connect()
            contract = adapter._front_future(ib, Future, symbol)
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True,
                formatDate=2,
                keepUpToDate=False,
            )
            local_symbol = str(getattr(contract, "localSymbol", None) or getattr(contract, "symbol", symbol))
            result = store_historical_bars(self.store, bars or [], symbol=symbol, contract=local_symbol, update_latest_quote=False)
            result.update({"connected": bool(ib.isConnected()), "bar_size": bar_size, "duration": duration})
            return result
        finally:
            try:
                if ib is not None and ib.isConnected():
                    ib.disconnect()
            except Exception:
                pass
