from __future__ import annotations

from typing import Any

from trading_execution.models import TradeIntent


class SafeStubAdapter:
    """Safe disconnected adapter used when no broker service is available."""

    def health(self) -> dict[str, Any]:
        return {"broker": "stub", "mode": "safe", "connected": False, "reason": "broker_not_connected"}

    def preview_order(self, intent: TradeIntent) -> dict[str, Any]:
        return {
            "preview_only": True,
            "broker": "stub",
            "symbol": intent.symbol,
            "side": intent.side,
            "contracts": intent.contracts,
            "entry_type": intent.entry_type,
            "limit_price": intent.limit_price,
            "stop_price": intent.stop_price,
            "target_price": intent.target_price,
            "order_placement_enabled": False,
        }

    def list_positions(self) -> list[dict[str, Any]]:
        return []

    def list_open_orders(self) -> list[dict[str, Any]]:
        return []
