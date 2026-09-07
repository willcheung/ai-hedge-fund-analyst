from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ShadowPosition:
    strategy: str
    symbol: str
    side: str
    entry_price: float
    stop_price: float
    target_price: float | None
    opened_at: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if numeric != numeric else numeric


def _close_trade(position: ShadowPosition, *, exit_price: float, exit_reason: str, closed_at: str) -> dict[str, Any]:
    risk = abs(position.entry_price - position.stop_price)
    if position.side == "BUY":
        pnl_points = exit_price - position.entry_price
    else:
        pnl_points = position.entry_price - exit_price
    r_multiple = None if risk <= 0 else round(pnl_points / risk, 6)
    return {
        **position.as_dict(),
        "closed_at": closed_at,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_points": round(pnl_points, 6),
        "r_multiple": r_multiple,
    }


def _exit_from_quote(position: ShadowPosition, last: float) -> tuple[float, str] | None:
    if position.side == "BUY":
        if last <= position.stop_price:
            return position.stop_price, "stop_hit"
        if position.target_price is not None and last >= position.target_price:
            return position.target_price, "target_hit"
    if position.side == "SELL":
        if last >= position.stop_price:
            return position.stop_price, "stop_hit"
        if position.target_price is not None and last <= position.target_price:
            return position.target_price, "target_hit"
    return None


def shadow_report_from_signals(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay signal journal records into a simple one-position shadow report.

    This is deliberately conservative and minimal: max one shadow position, exits
    only at recorded stop/target prices, and no broker orders.
    """
    closed: list[dict[str, Any]] = []
    position: ShadowPosition | None = None
    ignored_entries = 0

    for record in records:
        signal = record.get("signal") or {}
        state = signal.get("state")
        side = signal.get("side")
        quote = signal.get("quote") or {}
        last = _num(quote.get("last"))
        recorded_at = str(record.get("recorded_at") or "")

        if position is not None and last is not None:
            exit_event = _exit_from_quote(position, last)
            if exit_event is not None:
                exit_price, exit_reason = exit_event
                closed.append(_close_trade(position, exit_price=exit_price, exit_reason=exit_reason, closed_at=recorded_at))
                position = None
                continue

        if state == "EXIT_NOW" and position is not None and last is not None:
            closed.append(
                _close_trade(
                    position,
                    exit_price=last,
                    exit_reason=str(signal.get("exit_reason") or "signal_exit"),
                    closed_at=recorded_at,
                )
            )
            position = None
            continue

        if state == "ENTRY_READY":
            if position is not None:
                ignored_entries += 1
                continue
            entry = _num(signal.get("entry_price"))
            stop = _num(signal.get("stop_price"))
            target = _num(signal.get("target_price"))
            if side in {"BUY", "SELL"} and entry is not None and stop is not None:
                position = ShadowPosition(
                    strategy=str(signal.get("strategy") or record.get("strategy") or "unknown"),
                    symbol=str(signal.get("symbol") or record.get("symbol") or "unknown"),
                    side=side,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    opened_at=recorded_at,
                )

    r_values = [trade["r_multiple"] for trade in closed if trade.get("r_multiple") is not None]
    return {
        "closed_trades_count": len(closed),
        "closed_trades": closed,
        "open_position": position.as_dict() if position else None,
        "ignored_entries_while_open": ignored_entries,
        "total_r": round(sum(r_values), 6),
        "avg_r": round(sum(r_values) / len(r_values), 6) if r_values else None,
        "wins": sum(1 for value in r_values if value > 0),
        "losses": sum(1 for value in r_values if value < 0),
    }
