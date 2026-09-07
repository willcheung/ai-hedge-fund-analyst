from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from os import environ
from typing import Any, Iterator, Mapping

from trading_execution.instruments import normalize_symbol
from trading_execution.models import TradeIntent


class IBKRSafetyError(RuntimeError):
    """Raised when an IBKR operation would violate the paper-first safety envelope."""


@dataclass(frozen=True)
class IBKRSettings:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 77
    mode: str = "paper"
    account: str | None = None
    connect_timeout: float = 3.0
    trading_enabled: bool = False
    readonly: bool = True
    live_risk_acknowledged: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "IBKRSettings":
        source = env if env is not None else environ
        mode = source.get("IBKR_MODE", source.get("HERMES_TRADING_EXECUTION_MODE", "paper"))
        default_port = 7497 if mode == "paper" else 7496
        return cls(
            host=source.get("IBKR_HOST", "127.0.0.1"),
            port=int(source.get("IBKR_PORT", default_port)),
            client_id=int(source.get("IBKR_CLIENT_ID", "77")),
            mode=mode,
            account=source.get("IBKR_ACCOUNT") or None,
            connect_timeout=float(source.get("IBKR_CONNECT_TIMEOUT", "3.0")),
            trading_enabled=source.get("IBKR_TRADING_ENABLED", "false").lower() == "true",
            readonly=source.get("IBKR_READONLY", "true").lower() != "false",
            live_risk_acknowledged=source.get("IBKR_LIVE_RISK_ACKNOWLEDGED", "false").lower() == "true",
        )


def _ib_insync_import():
    try:
        from ib_insync import IB, Future, LimitOrder, StopOrder  # type: ignore
    except Exception as exc:  # pragma: no cover - environment-dependent
        return None, exc
    return (IB, Future, LimitOrder, StopOrder), None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if numeric != numeric else numeric


def _nonzero_price_or_none(value: Any) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None or numeric == 0:
        return None
    return numeric


def _contract_symbol(contract: Any) -> str:
    return str(
        getattr(contract, "localSymbol", None)
        or getattr(contract, "symbol", None)
        or getattr(contract, "conId", "")
    )


def _contract_root(contract: Any) -> str:
    return normalize_symbol(str(getattr(contract, "symbol", None) or _contract_symbol(contract)))


class IBKRAdapter:
    """Paper-first IBKR Gateway/TWS adapter.

    Read-only broker truth is available now: health, account visibility, positions,
    and open orders. Order placement remains disabled unless explicit paper/live
    gates are added and tested against IBKR paper.
    """

    def __init__(self, settings: IBKRSettings | None = None) -> None:
        self.settings = settings or IBKRSettings.from_env()

    def _safe_base(self) -> dict[str, Any]:
        return {
            "broker": "ibkr",
            "mode": self.settings.mode,
            "host": self.settings.host,
            "port": self.settings.port,
            "client_id": self.settings.client_id,
            "account_configured": bool(self.settings.account),
            "order_placement_enabled": self.settings.trading_enabled and not self.settings.readonly and self.settings.live_risk_acknowledged,
            "readonly": self.settings.readonly,
            "live_risk_acknowledged": self.settings.live_risk_acknowledged,
        }

    @contextmanager
    def _connected_ib(self, *, client_id_offset: int = 0, readonly: bool = True) -> Iterator[Any]:
        imported, import_error = _ib_insync_import()
        if imported is None:
            raise RuntimeError(f"ib_insync_unavailable: {import_error}")
        IB = imported[0]
        ib = IB()
        try:
            ib.connect(
                self.settings.host,
                self.settings.port,
                clientId=self.settings.client_id + client_id_offset,
                timeout=self.settings.connect_timeout,
                readonly=readonly,
            )
            yield ib
        finally:
            try:
                if ib.isConnected():
                    ib.disconnect()
            except Exception:
                pass

    def health(self) -> dict[str, Any]:
        base = self._safe_base()
        try:
            with self._connected_ib(client_id_offset=100) as ib:
                accounts = list(ib.managedAccounts() or [])
                return {
                    **base,
                    "connected": bool(ib.isConnected()),
                    "server_time": str(ib.reqCurrentTime()),
                    "managed_accounts_count": len(accounts),
                    "managed_accounts": accounts,
                }
        except Exception as exc:  # pragma: no cover - requires live gateway to exercise fully
            return {**base, "connected": False, "error": str(exc)}

    def preview_order(self, intent: TradeIntent) -> dict[str, Any]:
        if intent.broker != "ibkr":
            raise IBKRSafetyError("IBKRAdapter only accepts ibkr trade intents")
        if intent.mode != "paper" or self.settings.mode != "paper":
            raise IBKRSafetyError("IBKR MVP is paper-only")
        if intent.limit_price is None:
            raise IBKRSafetyError("IBKR preview requires a limit price")
        if intent.stop_price is None:
            raise IBKRSafetyError("IBKR preview requires a stop price")
        return {
            **self._safe_base(),
            "preview_only": True,
            "bracket_required": True,
            "symbol": intent.symbol,
            "side": intent.side,
            "contracts": intent.contracts,
            "entry_type": intent.entry_type,
            "limit_price": intent.limit_price,
            "stop_price": intent.stop_price,
            "target_price": intent.target_price,
            "message": "IBKR bracket-order preview only; no order was placed.",
        }

    def _front_future(self, ib: Any, Future: Any, symbol: str):
        details = ib.reqContractDetails(Future(symbol, exchange="CME", currency="USD")) or []
        dated = []
        for detail in details:
            contract = detail.contract
            expiry = str(getattr(contract, "lastTradeDateOrContractMonth", "") or "")
            dated.append((expiry, contract))
        if not dated:
            raise RuntimeError(f"No IBKR futures contracts resolved for {symbol}")
        today_key = date.today().strftime("%Y%m%d")
        now_month_key = today_key[:6]
        sorted_dated = sorted(dated)
        chosen = next(
            (contract for expiry, contract in sorted_dated if (len(expiry) >= 8 and expiry > today_key) or (len(expiry) < 8 and expiry >= now_month_key)),
            sorted_dated[-1][1],
        )
        qualified = ib.qualifyContracts(chosen)
        return qualified[0] if qualified else chosen

    def _order_summary(self, role: str, order: Any) -> dict[str, Any]:
        return {
            "role": role,
            "side": str(getattr(order, "action", "") or ""),
            "order_type": str(getattr(order, "orderType", "") or ""),
            "quantity": _float_or_none(getattr(order, "totalQuantity", None)),
            "limit_price": _nonzero_price_or_none(getattr(order, "lmtPrice", None)),
            "stop_price": _nonzero_price_or_none(getattr(order, "auxPrice", None)),
            "transmit": bool(getattr(order, "transmit", False)),
        }

    def place_bracket_order(self, intent: TradeIntent) -> dict[str, Any]:
        """Place a three-leg IBKR bracket order only when explicitly armed.

        This method is deliberately unavailable in the default paper/readonly config.
        Callers must run schema + risk gates before invoking it.
        """
        if intent.broker != "ibkr":
            raise IBKRSafetyError("IBKRAdapter only accepts ibkr trade intents")
        if not self.settings.trading_enabled or self.settings.readonly:
            raise IBKRSafetyError("order placement disabled")
        if not self.settings.live_risk_acknowledged:
            raise IBKRSafetyError("live risk acknowledgement required before IBKR order placement")
        if intent.mode != self.settings.mode:
            raise IBKRSafetyError("intent mode must match IBKR settings mode")
        if not self.settings.account:
            raise IBKRSafetyError("IBKR account must be configured before order placement")
        if intent.limit_price is None:
            raise IBKRSafetyError("bracket entry requires limit_price")
        if intent.stop_price is None:
            raise IBKRSafetyError("bracket requires stop_price")
        if intent.target_price is None:
            raise IBKRSafetyError("bracket requires target_price")

        imported, import_error = _ib_insync_import()
        if imported is None:
            raise RuntimeError(f"ib_insync_unavailable: {import_error}")
        _, Future, LimitOrder, StopOrder = imported
        exit_side = "SELL" if intent.side == "BUY" else "BUY"

        with self._connected_ib(client_id_offset=200, readonly=False) as ib:
            ib_errors: list[str] = []

            def _capture_error(req_id: Any, code: Any, message: Any, contract: Any = None) -> None:
                ib_errors.append(f"{code}: {message}")

            try:
                ib.errorEvent += _capture_error
            except Exception:
                pass
            accounts = list(ib.managedAccounts() or [])
            if self.settings.account not in accounts:
                raise IBKRSafetyError("configured IBKR account not visible to gateway")
            contract = self._front_future(ib, Future, intent.symbol)
            entry = LimitOrder(intent.side, intent.contracts, intent.limit_price)
            stop = StopOrder(exit_side, intent.contracts, intent.stop_price)
            target = LimitOrder(exit_side, intent.contracts, intent.target_price)

            # Build the full bracket before any order leaves this process. The prior
            # implementation learned the parent id after submitting the parent, which
            # is too fragile for live-money futures: a child can be accepted without
            # a correctly attached parent if IBKR rejects/mutates the parent.
            parent_id = int(ib.client.getReqId())
            entry.orderId = parent_id
            stop.orderId = int(ib.client.getReqId())
            target.orderId = int(ib.client.getReqId())
            stop.parentId = parent_id
            target.parentId = parent_id

            for order in (entry, stop, target):
                # Be explicit so IBKR Gateway does not apply/order-reject preset defaults.
                order.account = self.settings.account
                order.tif = "DAY"

            entry.transmit = False
            stop.transmit = False
            target.transmit = True

            placed_trades: list[Any] = []
            try:
                entry_trade = ib.placeOrder(contract, entry)
                placed_trades.append(entry_trade)
                stop_trade = ib.placeOrder(contract, stop)
                placed_trades.append(stop_trade)
                target_trade = ib.placeOrder(contract, target)
                placed_trades.append(target_trade)
                try:
                    ib.sleep(1.0)
                except Exception:
                    pass
                statuses = [str(getattr(getattr(trade, "orderStatus", None), "status", "") or "") for trade in (entry_trade, stop_trade, target_trade)]
                rejected = [status for status in statuses if status.lower() in {"inactive", "apicancelled", "cancelled", "rejected"}]
                if ib_errors:
                    raise RuntimeError("IBKR order placement error: " + "; ".join(ib_errors[-5:]))
                if rejected:
                    raise RuntimeError("IBKR order placement not accepted: statuses=" + ",".join(statuses))
            except Exception:
                for trade in placed_trades:
                    try:
                        ib.cancelOrder(getattr(trade, "order", trade))
                    except Exception:
                        pass
                try:
                    ib.sleep(1.0)
                except Exception:
                    pass
                raise

        return {
            **self._safe_base(),
            "placed": True,
            "symbol": intent.symbol,
            "contract": _contract_symbol(contract),
            "orders": [
                self._order_summary("entry", getattr(entry_trade, "order", entry)),
                self._order_summary("stop", getattr(stop_trade, "order", stop)),
                self._order_summary("target", getattr(target_trade, "order", target)),
            ],
        }

    def list_positions(self) -> list[dict[str, Any]]:
        try:
            with self._connected_ib(client_id_offset=101) as ib:
                positions: list[dict[str, Any]] = []
                for item in ib.portfolio() or []:
                    contract = getattr(item, "contract", None)
                    positions.append(
                        {
                            "symbol": _contract_symbol(contract),
                            "root_symbol": _contract_root(contract),
                            "sec_type": str(getattr(contract, "secType", "") or ""),
                            "exchange": str(getattr(contract, "exchange", "") or ""),
                            "currency": str(getattr(contract, "currency", "") or ""),
                            "quantity": _float_or_none(getattr(item, "position", None)),
                            "market_price": _float_or_none(getattr(item, "marketPrice", None)),
                            "market_value": _float_or_none(getattr(item, "marketValue", None)),
                            "average_cost": _float_or_none(getattr(item, "averageCost", None)),
                            "unrealized_pnl": _float_or_none(getattr(item, "unrealizedPNL", None)),
                            "realized_pnl": _float_or_none(getattr(item, "realizedPNL", None)),
                        }
                    )
                return positions
        except Exception:
            return []

    def list_open_orders(self) -> list[dict[str, Any]]:
        try:
            with self._connected_ib(client_id_offset=102) as ib:
                orders: list[dict[str, Any]] = []
                for trade in ib.openTrades() or []:
                    contract = getattr(trade, "contract", None)
                    order = getattr(trade, "order", None)
                    status = getattr(trade, "orderStatus", None)
                    orders.append(
                        {
                            "symbol": _contract_symbol(contract),
                            "root_symbol": _contract_root(contract),
                            "sec_type": str(getattr(contract, "secType", "") or ""),
                            "exchange": str(getattr(contract, "exchange", "") or ""),
                            "order_id": getattr(order, "orderId", None),
                            "side": str(getattr(order, "action", "") or ""),
                            "order_type": str(getattr(order, "orderType", "") or ""),
                            "quantity": _float_or_none(getattr(order, "totalQuantity", None)),
                            "status": str(getattr(status, "status", "") or ""),
                            "filled": _float_or_none(getattr(status, "filled", None)),
                            "remaining": _float_or_none(getattr(status, "remaining", None)),
                            "stop_price": _nonzero_price_or_none(getattr(order, "auxPrice", None)),
                            "limit_price": _nonzero_price_or_none(getattr(order, "lmtPrice", None)),
                        }
                    )
                return orders
        except Exception:
            return []
