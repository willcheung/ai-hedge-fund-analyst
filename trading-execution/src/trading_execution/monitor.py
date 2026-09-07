from __future__ import annotations

import time
from typing import Any, Protocol

from .broker.stub import SafeStubAdapter


class BrokerMonitorAdapter(Protocol):
    def health(self) -> dict[str, Any]: ...

    def list_positions(self) -> list[dict[str, Any]]: ...

    def list_open_orders(self) -> list[dict[str, Any]]: ...


def _field(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def _symbol_prefix(symbol: str | None) -> str:
    if not symbol:
        return ""
    upper = str(symbol).upper()
    for prefix in ("MES", "MNQ", "MGC", "ES", "NQ", "GC"):
        if upper.startswith(prefix):
            return prefix
    return upper[:3]


def _is_nonzero_position(position: dict[str, Any]) -> bool:
    raw_qty = _field(position, "quantity", "qty", "position", "net_position", "netQty", "net_qty")
    if raw_qty is None:
        return True
    try:
        return abs(float(raw_qty)) > 0
    except (TypeError, ValueError):
        return True


def _order_symbol(order: dict[str, Any]) -> str:
    return str(_field(order, "symbol", "ticker", "contract", "instrument") or "")


def _position_symbol(position: dict[str, Any]) -> str:
    return str(_field(position, "symbol", "ticker", "contract", "instrument") or "")


def _looks_protective_order(order: dict[str, Any]) -> bool:
    order_type = str(_field(order, "order_type", "type", "orderType") or "").upper()
    side = str(_field(order, "side", "action") or "").upper()
    return any(token in order_type for token in ("STOP", "TRAIL")) or side in {"SELL", "BUY_TO_COVER"}


def evaluate_monitor_state(
    *,
    health: dict[str, Any],
    positions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[str]:
    """Return deterministic alerts for the always-on supervisor."""
    alerts: list[str] = []
    connected = health.get("connected")
    if connected is False:
        alerts.append("broker_disconnected")
    if config.get("kill_switch"):
        alerts.append("kill_switch_enabled")

    active_positions = [p for p in positions if _is_nonzero_position(p)]
    if active_positions:
        alerts.append("position_present")

    max_open = int(config.get("risk_limits", {}).get("max_open_positions", 0))
    if max_open and len(active_positions) > max_open:
        alerts.append("max_open_positions_exceeded")

    allowed = set(config.get("allowed_symbols", {}).keys()) or {"MES"}
    order_symbols = {_symbol_prefix(_order_symbol(order)) for order in orders}
    has_protective_order = any(_looks_protective_order(order) for order in orders)

    for position in active_positions:
        prefix = _symbol_prefix(_position_symbol(position))
        if prefix not in allowed:
            alerts.append("non_whitelisted_position")
        if prefix and prefix not in order_symbols and not has_protective_order:
            alerts.append("position_without_open_protective_order")

    if orders:
        alerts.append("open_orders_present")

    return list(dict.fromkeys(alerts))


def monitor_once(
    *,
    adapter: BrokerMonitorAdapter | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adapter = adapter or SafeStubAdapter()
    config = config or {"risk_limits": {"max_open_positions": 1}, "allowed_symbols": {"MES": {}}}
    health = adapter.health()
    positions = adapter.list_positions()
    orders = adapter.list_open_orders()
    alerts = evaluate_monitor_state(health=health, positions=positions, orders=orders, config=config)
    return {"health": health, "positions": positions, "open_orders": orders, "alerts": alerts}


def monitor_loop(
    *,
    adapter: BrokerMonitorAdapter | None = None,
    config: dict[str, Any] | None = None,
    interval_seconds: float = 15.0,
    iterations: int | None = None,
) -> list[dict[str, Any]]:
    """Run the deterministic supervisor loop."""
    snapshots: list[dict[str, Any]] = []
    count = 0
    while iterations is None or count < iterations:
        snapshots.append(monitor_once(adapter=adapter, config=config))
        count += 1
        if iterations is None or count < iterations:
            time.sleep(interval_seconds)
    return snapshots
