from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from .ibkr_adapter import IBKRSettings, _ib_insync_import
from trading_execution.instruments import normalize_symbol


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    connected: bool
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    close: float | None = None
    spread: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    last_size: float | None = None
    market_data_type: int | None = None
    contract: str | None = None
    con_id: int | None = None
    delayed_or_unknown: bool = True
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class IBKRMarketDataAdapter:
    """Read-only IBKR market-data adapter for MES-first execution."""

    def __init__(self, settings: IBKRSettings | None = None) -> None:
        self.settings = settings or IBKRSettings.from_env()

    def _connect(self):
        imported, import_error = _ib_insync_import()
        if imported is None:
            raise RuntimeError(f"ib_insync_unavailable: {import_error}")
        IB, Future = imported[0], imported[1]
        ib = IB()
        ib.connect(
            self.settings.host,
            self.settings.port,
            clientId=self.settings.client_id + 10,
            timeout=self.settings.connect_timeout,
            readonly=True,
        )
        return ib, Future

    def _front_future(self, ib: Any, Future: Any, symbol: str):
        details = ib.reqContractDetails(Future(symbol, exchange="CME", currency="USD")) or []
        dated = []
        for detail in details:
            contract = detail.contract
            expiry = str(getattr(contract, "lastTradeDateOrContractMonth", "") or "")
            if expiry:
                dated.append((expiry, contract))
        if not dated:
            raise RuntimeError(f"No IBKR futures contracts resolved for {symbol}")

        today_key = date.today().strftime("%Y%m%d")
        now_month_key = time.strftime("%Y%m")
        sorted_dated = sorted(dated)
        chosen = next(
            (contract for expiry, contract in sorted_dated if (len(expiry) >= 8 and expiry > today_key) or (len(expiry) < 8 and expiry >= now_month_key)),
            sorted_dated[-1][1],
        )
        qualified = ib.qualifyContracts(chosen)
        return qualified[0] if qualified else chosen

    def snapshot(self, symbol: str = "MES", wait_seconds: float = 2.0) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        ib = None
        contract = None
        try:
            ib, Future = self._connect()
            contract = self._front_future(ib, Future, normalized)
            ib.reqMarketDataType(1)
            ticker = ib.reqMktData(contract, "", False, False)
            deadline = time.time() + wait_seconds
            while time.time() < deadline:
                ib.sleep(0.25)
                if any(_float_or_none(getattr(ticker, field, None)) is not None for field in ("bid", "ask", "last", "close")):
                    break

            bid = _float_or_none(getattr(ticker, "bid", None))
            ask = _float_or_none(getattr(ticker, "ask", None))
            last = _float_or_none(getattr(ticker, "last", None))
            close = _float_or_none(getattr(ticker, "close", None))
            market_data_type = _int_or_none(getattr(ticker, "marketDataType", None))
            spread = round(ask - bid, 6) if bid is not None and ask is not None else None
            return MarketSnapshot(
                symbol=normalized,
                connected=bool(ib.isConnected()),
                bid=bid,
                ask=ask,
                last=last,
                close=close,
                spread=spread,
                bid_size=_float_or_none(getattr(ticker, "bidSize", None)),
                ask_size=_float_or_none(getattr(ticker, "askSize", None)),
                last_size=_float_or_none(getattr(ticker, "lastSize", None)),
                market_data_type=market_data_type,
                contract=str(getattr(contract, "localSymbol", None) or getattr(contract, "symbol", "")),
                con_id=getattr(contract, "conId", None),
                delayed_or_unknown=market_data_type != 1,
            ).as_dict()
        except Exception as exc:
            return MarketSnapshot(symbol=normalized, connected=False, error=str(exc)).as_dict()
        finally:
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
