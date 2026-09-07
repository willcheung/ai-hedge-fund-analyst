from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from trading_execution.stream_state import Bar1s, QuoteState
from trading_execution.strategies.opening_range_vwap import opening_range_vwap_signal

ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class BacktestParams:
    symbol: str = "MES"
    contracts: int = 2
    dollars_per_point: float = 5.0
    tick_size: float = 0.25
    slippage_ticks: int = 2
    max_spread: float = 0.25
    rth_only: bool = True
    max_trade_loss_usd: float | None = 100.0


@dataclass(frozen=True)
class BacktestTrade:
    side: str
    entry_time: str
    exit_time: str
    signal_entry: float
    entry_fill: float
    stop_price: float
    target_price: float | None
    exit_fill: float
    exit_reason: str
    pnl_points: float
    pnl_usd: float
    r_multiple: float

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class BacktestMetrics:
    total_trades: int
    wins: int
    losses: int
    win_rate: float | None
    total_r: float
    avg_r: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float
    pnl_usd: float
    worst_r: float | None
    consecutive_losses: int

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class BacktestReport:
    strategy: str
    params: dict[str, Any]
    metrics: BacktestMetrics
    trades: list[BacktestTrade] = field(default_factory=list)
    no_trade_reasons: dict[str, int] = field(default_factory=dict)
    verdict: str = "ABANDON"

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "params": self.params,
            "metrics": self.metrics.as_dict(),
            "trades": [trade.as_dict() for trade in self.trades],
            "no_trade_reasons": dict(self.no_trade_reasons),
            "verdict": self.verdict,
        }


def _in_rth(ts: datetime) -> bool:
    et = ts.astimezone(ET)
    return time(9, 30) <= et.time() <= time(16, 0)


def _quote_from_bar(bar: Bar1s) -> QuoteState:
    return QuoteState(
        symbol=bar.symbol,
        contract="BACKTEST",
        bid=bar.bid,
        ask=bar.ask,
        last=bar.close,
        received_at_utc=bar.ts_utc,
    )


def _levels_from_running_state(bar: Bar1s, state: dict[str, Any]) -> dict[str, Any]:
    et = bar.ts_utc.astimezone(ET)
    session_date = et.date()
    if state.get("date") != session_date:
        state.clear()
        state.update(
            {
                "date": session_date,
                "rth_open": datetime.combine(session_date, time(9, 30), tzinfo=ET),
                "pv": 0.0,
                "vol": 0.0,
                "bars_used": 0,
                "or5_high": None,
                "or5_low": None,
                "or15_high": None,
                "or15_low": None,
                "or30_high": None,
                "or30_low": None,
                "overnight_high": None,
                "overnight_low": None,
            }
        )
    rth_open = state["rth_open"]
    state["bars_used"] += 1
    if et < rth_open:
        state["overnight_high"] = bar.high if state["overnight_high"] is None else max(state["overnight_high"], bar.high)
        state["overnight_low"] = bar.low if state["overnight_low"] is None else min(state["overnight_low"], bar.low)
    else:
        vol = max(float(bar.volume_proxy or 0.0), 0.0) or 1.0
        state["pv"] += bar.close * vol
        state["vol"] += vol
        minutes = (et - rth_open).total_seconds() / 60.0
        for window in (5, 15, 30):
            if 0 <= minutes < window:
                hi_key = f"or{window}_high"
                lo_key = f"or{window}_low"
                state[hi_key] = bar.high if state[hi_key] is None else max(state[hi_key], bar.high)
                state[lo_key] = bar.low if state[lo_key] is None else min(state[lo_key], bar.low)
    vwap = state["pv"] / state["vol"] if state.get("vol") else None
    quote = _quote_from_bar(bar).as_dict()
    return {
        "symbol": bar.symbol,
        "calculated_at_utc": bar.ts_utc.isoformat(),
        "bars_used": state["bars_used"],
        "latest_quote": quote,
        "vwap": None if vwap is None else round(vwap, 6),
        "last_vs_vwap": None if vwap is None else round(bar.close - vwap, 6),
        "or5_high": state.get("or5_high"),
        "or5_low": state.get("or5_low"),
        "or15_high": state.get("or15_high"),
        "or15_low": state.get("or15_low"),
        "or30_high": state.get("or30_high"),
        "or30_low": state.get("or30_low"),
        "overnight_high": state.get("overnight_high"),
        "overnight_low": state.get("overnight_low"),
    }


def _entry_fill(side: str, entry: float, params: BacktestParams) -> float:
    slip = params.slippage_ticks * params.tick_size
    return round(entry + slip if side == "BUY" else entry - slip, 6)


def _exit_fill(side: str, exit_price: float, params: BacktestParams) -> float:
    slip = params.slippage_ticks * params.tick_size
    # Closing a long sells; closing a short buys. Pessimistic slippage moves against us.
    return round(exit_price - slip if side == "BUY" else exit_price + slip, 6)


def _check_exit(position: dict[str, Any], bar: Bar1s, params: BacktestParams) -> tuple[float, str] | None:
    side = position["side"]
    stop = float(position["stop_price"])
    target = position.get("target_price")
    target = None if target is None else float(target)

    if side == "BUY":
        stop_hit = bar.low <= stop
        target_hit = target is not None and bar.high >= target
        if stop_hit:  # pessimistic: stop wins same-bar ambiguity
            return _exit_fill(side, stop, params), "stop_hit"
        if target_hit:
            return _exit_fill(side, target, params), "target_hit"
    else:
        stop_hit = bar.high >= stop
        target_hit = target is not None and bar.low <= target
        if stop_hit:
            return _exit_fill(side, stop, params), "stop_hit"
        if target_hit:
            return _exit_fill(side, target, params), "target_hit"
    return None


def _metrics(trades: list[BacktestTrade]) -> BacktestMetrics:
    rs = [trade.r_multiple for trade in trades]
    wins = sum(1 for r in rs if r > 0)
    losses = sum(1 for r in rs if r < 0)
    gains = sum(r for r in rs if r > 0)
    loss_abs = abs(sum(r for r in rs if r < 0))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    streak = 0
    max_streak = 0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return BacktestMetrics(
        total_trades=len(trades),
        wins=wins,
        losses=losses,
        win_rate=round(wins / len(trades), 6) if trades else None,
        total_r=round(sum(rs), 6),
        avg_r=round(sum(rs) / len(rs), 6) if rs else None,
        expectancy_r=round(sum(rs) / len(rs), 6) if rs else None,
        profit_factor=round(gains / loss_abs, 6) if loss_abs else (None if gains == 0 else float("inf")),
        max_drawdown_r=round(max_dd, 6),
        pnl_usd=round(sum(trade.pnl_usd for trade in trades), 2),
        worst_r=round(min(rs), 6) if rs else None,
        consecutive_losses=max_streak,
    )


def _verdict(metrics: BacktestMetrics) -> str:
    if metrics.total_trades < 5:
        return "REFINE" if metrics.total_trades else "ABANDON"
    if (metrics.expectancy_r or 0) > 0 and metrics.max_drawdown_r <= max(3.0, metrics.total_trades * 0.35):
        return "PAPER_FORWARD_TEST"
    if metrics.total_trades and (metrics.expectancy_r or 0) > -0.2:
        return "REFINE"
    return "ABANDON"


def backtest_or_vwap(bars: list[Bar1s], params: BacktestParams | None = None) -> BacktestReport:
    params = params or BacktestParams()
    bars = sorted([bar for bar in bars if bar.symbol == params.symbol], key=lambda b: b.ts_utc)
    trades: list[BacktestTrade] = []
    no_trade_reasons: Counter[str] = Counter()
    position: dict[str, Any] | None = None
    running_state: dict[str, Any] = {}

    for bar in bars:
        if params.rth_only and not _in_rth(bar.ts_utc):
            _levels_from_running_state(bar, running_state)
            continue

        if position is not None:
            exit_event = _check_exit(position, bar, params)
            if exit_event is not None:
                exit_fill, reason = exit_event
                side = position["side"]
                entry_fill = float(position["entry_fill"])
                if side == "BUY":
                    pnl_points = exit_fill - entry_fill
                else:
                    pnl_points = entry_fill - exit_fill
                risk_points = abs(entry_fill - float(position["stop_price"]))
                r_multiple = pnl_points / risk_points if risk_points else 0.0
                trades.append(
                    BacktestTrade(
                        side=side,
                        entry_time=position["entry_time"],
                        exit_time=bar.ts_utc.isoformat(),
                        signal_entry=float(position["signal_entry"]),
                        entry_fill=entry_fill,
                        stop_price=float(position["stop_price"]),
                        target_price=position.get("target_price"),
                        exit_fill=exit_fill,
                        exit_reason=reason,
                        pnl_points=round(pnl_points, 6),
                        pnl_usd=round(pnl_points * params.dollars_per_point * params.contracts, 2),
                        r_multiple=round(r_multiple, 6),
                    )
                )
                position = None
            _levels_from_running_state(bar, running_state)
            continue

        levels = _levels_from_running_state(bar, running_state)
        signal = opening_range_vwap_signal(levels, stream_ok=True, max_spread=params.max_spread)
        if signal.state != "ENTRY_READY":
            no_trade_reasons[str(signal.reason or signal.state)] += 1
            continue

        if signal.entry_price is None or signal.stop_price is None:
            no_trade_reasons["missing_entry_or_stop"] += 1
            continue
        entry_fill = _entry_fill(str(signal.side), float(signal.entry_price), params)
        risk_usd = abs(entry_fill - float(signal.stop_price)) * params.dollars_per_point * params.contracts
        if params.max_trade_loss_usd is not None and risk_usd > params.max_trade_loss_usd:
            no_trade_reasons["risk_exceeds_trade_limit"] += 1
            continue
        position = {
            "side": signal.side,
            "entry_time": bar.ts_utc.isoformat(),
            "signal_entry": signal.entry_price,
            "entry_fill": entry_fill,
            "stop_price": signal.stop_price,
            "target_price": signal.target_price,
        }

    metrics = _metrics(trades)
    return BacktestReport(
        strategy="or-vwap",
        params=params.__dict__.copy(),
        metrics=metrics,
        trades=trades,
        no_trade_reasons=dict(no_trade_reasons),
        verdict=_verdict(metrics),
    )
