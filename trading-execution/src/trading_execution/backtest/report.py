from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trading_execution.backtest.engine import BacktestReport


def write_backtest_report(report: BacktestReport, output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".md":
        path.write_text(markdown_report(report), encoding="utf-8")
    else:
        path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def markdown_report(report: BacktestReport) -> str:
    m = report.metrics
    lines = [
        f"# Backtest Report — {report.strategy}",
        "",
        f"Verdict: **{report.verdict}**",
        "",
        "## Parameters",
    ]
    for key, value in report.params.items():
        lines.append(f"- {key}: `{value}`")
    lines += [
        "",
        "## Metrics",
        f"- trades: {m.total_trades}",
        f"- wins/losses: {m.wins}/{m.losses}",
        f"- win rate: {m.win_rate}",
        f"- total R: {m.total_r}",
        f"- avg/expectancy R: {m.avg_r}",
        f"- max drawdown R: {m.max_drawdown_r}",
        f"- PnL USD: {m.pnl_usd}",
        f"- profit factor: {m.profit_factor}",
        f"- consecutive losses: {m.consecutive_losses}",
        "",
        "## Top no-trade/block reasons",
    ]
    for reason, count in sorted(report.no_trade_reasons.items(), key=lambda kv: kv[1], reverse=True)[:10]:
        lines.append(f"- {reason}: {count}")
    lines += ["", "## Recent trades"]
    for trade in report.trades[-10:]:
        lines.append(
            f"- {trade.entry_time} {trade.side} entry={trade.entry_fill} exit={trade.exit_fill} "
            f"reason={trade.exit_reason} R={trade.r_multiple} pnl=${trade.pnl_usd}"
        )
    return "\n".join(lines) + "\n"
