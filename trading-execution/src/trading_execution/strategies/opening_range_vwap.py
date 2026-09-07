from __future__ import annotations

from typing import Any, Literal

from trading_execution.strategy import StrategySignal

PositionSide = Literal["BUY", "SELL"]
TICK = 0.25


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if numeric != numeric else numeric


def _valid_book(bid: float | None, ask: float | None) -> bool:
    return bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid


def _round_tick(value: float | None) -> float | None:
    if value is None:
        return None
    return round(round(value / TICK) * TICK, 2)


def _signal(
    *,
    state: str,
    side: str | None,
    reason: str,
    levels: dict[str, Any],
    entry_price: float | None = None,
    stop_price: float | None = None,
    target_price: float | None = None,
    invalidation: str | None = None,
    exit_reason: str | None = None,
) -> StrategySignal:
    risk = None
    reward = None
    if entry_price is not None and stop_price is not None:
        risk = abs(entry_price - stop_price)
    if entry_price is not None and target_price is not None:
        reward = abs(target_price - entry_price)
    return StrategySignal(
        strategy="or-vwap",
        symbol=levels.get("symbol", "MES"),
        state=state,  # type: ignore[arg-type]
        side=side,  # type: ignore[arg-type]
        reason=reason,
        entry_price=_round_tick(entry_price),
        stop_price=_round_tick(stop_price),
        target_price=_round_tick(target_price),
        invalidation=invalidation,
        risk_points=_round_tick(risk),
        reward_points=_round_tick(reward),
        exit_reason=exit_reason,
        levels=levels,
        quote=levels.get("latest_quote"),
    )


def _position_exit(
    levels: dict[str, Any],
    *,
    position_side: PositionSide,
    stop_price: float,
    target_price: float | None,
) -> StrategySignal | None:
    quote = levels.get("latest_quote") or {}
    last = _num(quote.get("last"))
    if last is None:
        return _signal(state="NO_TRADE", side=None, reason="missing_last_price", levels=levels)
    if position_side == "BUY":
        if last <= stop_price:
            return _signal(state="EXIT_NOW", side="SELL", reason="protective_exit", levels=levels, exit_reason="stop_hit")
        if target_price is not None and last >= target_price:
            return _signal(state="EXIT_NOW", side="SELL", reason="profit_exit", levels=levels, exit_reason="target_hit")
    if position_side == "SELL":
        if last >= stop_price:
            return _signal(state="EXIT_NOW", side="BUY", reason="protective_exit", levels=levels, exit_reason="stop_hit")
        if target_price is not None and last <= target_price:
            return _signal(state="EXIT_NOW", side="BUY", reason="profit_exit", levels=levels, exit_reason="target_hit")
    return _signal(state="WAIT", side=None, reason="position_open_no_exit", levels=levels)


def opening_range_vwap_signal(
    levels: dict[str, Any],
    *,
    stream_ok: bool = True,
    max_spread: float = 0.25,
    position_side: PositionSide | None = None,
    stop_price: float | None = None,
    target_price: float | None = None,
) -> StrategySignal:
    """Signal-only OR15/VWAP strategy.

    This deliberately emits intent-quality signals only. It does not size contracts,
    create TradeIntent JSON, or place orders.
    """

    if not stream_ok:
        return _signal(state="NO_TRADE", side=None, reason="stream_stale_or_missing", levels=levels)

    quote = levels.get("latest_quote") or {}
    spread = _num(quote.get("spread"))
    last = _num(quote.get("last"))
    bid = _num(quote.get("bid"))
    ask = _num(quote.get("ask"))
    vwap = _num(levels.get("vwap"))
    or15_high = _num(levels.get("or15_high"))
    or15_low = _num(levels.get("or15_low"))

    if position_side is not None:
        if stop_price is None:
            return _signal(state="NO_TRADE", side=None, reason="position_stop_missing", levels=levels)
        return _position_exit(levels, position_side=position_side, stop_price=stop_price, target_price=target_price)

    if last is None:
        return _signal(state="NO_TRADE", side=None, reason="missing_last_price", levels=levels)
    if not _valid_book(bid, ask):
        return _signal(state="NO_TRADE", side=None, reason="invalid_bid_ask", levels=levels)
    if spread is None or spread < 0 or spread > max_spread:
        return _signal(state="NO_TRADE", side=None, reason="spread_too_wide", levels=levels)
    if vwap is None or or15_high is None or or15_low is None:
        return _signal(state="SETUP_FORMING", side=None, reason="waiting_for_or15_and_vwap", levels=levels)

    if last > or15_high and last > vwap:
        stop = min(vwap, or15_high)
        risk = last - stop
        if risk <= 0:
            return _signal(state="NO_TRADE", side=None, reason="invalid_long_risk", levels=levels)
        target = last + 1.5 * risk
        return _signal(
            state="ENTRY_READY",
            side="BUY",
            reason="breakout_above_or15_and_vwap",
            levels=levels,
            entry_price=last,
            stop_price=stop,
            target_price=target,
            invalidation="last_price_back_below_vwap_or_or15_high",
        )

    if last < or15_low and last < vwap:
        stop = max(vwap, or15_low)
        risk = stop - last
        if risk <= 0:
            return _signal(state="NO_TRADE", side=None, reason="invalid_short_risk", levels=levels)
        target = last - 1.5 * risk
        return _signal(
            state="ENTRY_READY",
            side="SELL",
            reason="breakdown_below_or15_and_vwap",
            levels=levels,
            entry_price=last,
            stop_price=stop,
            target_price=target,
            invalidation="last_price_back_above_vwap_or_or15_low",
        )

    return _signal(state="WAIT", side=None, reason="inside_or15_or_not_aligned_with_vwap", levels=levels)
