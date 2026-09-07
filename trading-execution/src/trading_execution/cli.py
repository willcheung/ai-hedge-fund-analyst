from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .backtest.engine import BacktestParams, backtest_or_vwap
from .backtest.report import write_backtest_report
from .broker.ibkr_adapter import IBKRAdapter, IBKRSafetyError, IBKRSettings
from .broker.ibkr_market_data import IBKRMarketDataAdapter
from .config import load_config
from .historical_backfill import MESHistoricalBackfiller
from .journal import append_audit, write_trade_journal
from .levels import calculate_mes_levels
from .models import TradeIntent
from .monitor import monitor_loop, monitor_once
from .paper_shadow import shadow_report_from_signals
from .risk import evaluate_intent
from .schema import load_trade_intent_json, validate_trade_intent_payload
from .signal_journal import append_signal, read_signals
from .streamer import MESStreamer, StreamStatus
from .stream_store import StreamStore
from .strategies.opening_range_vwap import opening_range_vwap_signal


def _load_intent(path: str) -> TradeIntent:
    payload = load_trade_intent_json(path)
    validate_trade_intent_payload(payload)
    return TradeIntent.from_dict(payload)


def _ibkr_settings_from_config(config: dict) -> IBKRSettings:
    ibkr = config.get("ibkr", {})
    return IBKRSettings(
        host=ibkr.get("host", "127.0.0.1"),
        port=int(ibkr.get("port", 7497)),
        client_id=int(ibkr.get("client_id", 77)),
        account=ibkr.get("account"),
        connect_timeout=float(ibkr.get("connect_timeout", 3.0)),
        mode=config.get("mode", "paper"),
        trading_enabled=bool(ibkr.get("trading_enabled", False)),
        readonly=bool(ibkr.get("readonly", True)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="trading-execution")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate-intent")
    v.add_argument("intent_json")
    r = sub.add_parser("risk-check")
    r.add_argument("intent_json")
    j = sub.add_parser("journal")
    j.add_argument("intent_json")
    j.add_argument("--decision", choices=["APPROVED", "REJECTED"], required=True)
    j.add_argument("--reviewer", required=True)
    sub.add_parser("monitor-once")
    ml = sub.add_parser("monitor-loop")
    ml.add_argument("--interval", type=float, default=15.0)
    ml.add_argument("--iterations", type=int, default=1)
    md = sub.add_parser("market-snapshot")
    md.add_argument("--symbol", default="MES")
    sm = sub.add_parser("stream-mes")
    sm.add_argument("--duration", type=float, default=None, help="Optional seconds to run; omit for daemon mode")
    sm.add_argument("--sample-interval", type=float, default=0.25)
    ss = sub.add_parser("stream-status")
    ss.add_argument("--stale-after", type=float, default=15.0)
    bf = sub.add_parser("backfill-rth")
    bf.add_argument("--symbol", default="MES")
    bf.add_argument("--duration", default="1 D")
    bf.add_argument("--bar-size", default="1 min")
    lv = sub.add_parser("levels")
    lv.add_argument("--symbol", default="MES")
    lv.add_argument("--limit", type=int, default=30000, help="Max 1s stream bars to load")
    sig = sub.add_parser("strategy-signal")
    sig.add_argument("--strategy", choices=["or-vwap"], default="or-vwap")
    sig.add_argument("--symbol", default="MES")
    sig.add_argument("--max-spread", type=float, default=0.25)
    sig.add_argument("--position-side", choices=["BUY", "SELL"], default=None)
    sig.add_argument("--stop-price", type=float, default=None)
    sig.add_argument("--target-price", type=float, default=None)
    sj = sub.add_parser("signal-journal-once")
    sj.add_argument("--strategy", choices=["or-vwap"], default="or-vwap")
    sj.add_argument("--symbol", default="MES")
    sj.add_argument("--max-spread", type=float, default=0.25)
    sh = sub.add_parser("shadow-report")
    sh.add_argument("--limit", type=int, default=500)
    sub.add_parser("ibkr-health")
    sub.add_parser("broker-health")
    sub.add_parser("broker-positions")
    sub.add_parser("broker-open-orders")
    bp = sub.add_parser("broker-preview")
    bp.add_argument("intent_json")
    bt = sub.add_parser("backtest-or-vwap")
    bt.add_argument("--symbol", default="MES")
    bt.add_argument("--limit", type=int, default=200000, help="Max 1s stream bars to load")
    bt.add_argument("--contracts", type=int, default=2)
    bt.add_argument("--slippage-ticks", type=int, default=2)
    bt.add_argument("--max-spread", type=float, default=0.25)
    bt.add_argument("--max-trade-loss-usd", type=float, default=100.0)
    bt.add_argument("--output", default=None)

    args = parser.parse_args()
    config = load_config()
    adapter = IBKRAdapter(_ibkr_settings_from_config(config))

    if args.cmd == "validate-intent":
        _load_intent(args.intent_json)
        print(json.dumps({"valid": True}, indent=2))
    elif args.cmd == "risk-check":
        intent = _load_intent(args.intent_json)
        decision = evaluate_intent(intent, config)
        append_audit({"type": "risk_check", "intent_id": intent.intent_id, "decision": asdict(decision)}, config["paths"]["audit_log"])
        print(json.dumps(asdict(decision), indent=2))
    elif args.cmd == "journal":
        intent = _load_intent(args.intent_json)
        decision = evaluate_intent(intent, config)
        out = write_trade_journal(intent, decision, config["paths"]["journal_dir"])
        append_audit({"type": "journal_write", "intent_id": intent.intent_id, "path": str(out), "decision": asdict(decision), "reviewer": args.reviewer}, config["paths"]["audit_log"])
        print(json.dumps({"journal_path": str(out), "risk_approved": decision.approved}, indent=2))
    elif args.cmd == "monitor-once":
        result = monitor_once(adapter=adapter, config=config)
        append_audit({"type": "monitor_once", "result": result}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "monitor-loop":
        snapshots = monitor_loop(adapter=adapter, config=config, interval_seconds=args.interval, iterations=args.iterations)
        append_audit({"type": "monitor_loop", "iterations": len(snapshots), "last": snapshots[-1] if snapshots else None}, config["paths"]["audit_log"])
        print(json.dumps({"iterations": len(snapshots), "last": snapshots[-1] if snapshots else None}, indent=2))
    elif args.cmd == "market-snapshot":
        settings = _ibkr_settings_from_config(config)
        result = IBKRMarketDataAdapter(settings).snapshot(args.symbol)
        append_audit({"type": "market_snapshot", "symbol": args.symbol, "result": result}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "stream-mes":
        settings = _ibkr_settings_from_config(config)
        MESStreamer(settings).run(duration_seconds=args.duration, sample_interval=args.sample_interval)
        result = StreamStatus.from_store().as_dict()
        append_audit({"type": "stream_mes", "duration": args.duration, "result": result}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "stream-status":
        result = StreamStatus.from_store(stale_after_seconds=args.stale_after).as_dict()
        print(json.dumps(result, indent=2))
    elif args.cmd == "backfill-rth":
        result = MESHistoricalBackfiller(_ibkr_settings_from_config(config)).backfill_rth(
            symbol=args.symbol,
            duration=args.duration,
            bar_size=args.bar_size,
        )
        append_audit({"type": "backfill_rth", "symbol": args.symbol, "result": result}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "levels":
        store = StreamStore()
        latest_quote = store.latest_quote(args.symbol)
        bars = store.latest_bars_1s(args.symbol, limit=args.limit)
        result = calculate_mes_levels(bars, latest_quote=latest_quote).as_dict()
        append_audit({"type": "levels", "symbol": args.symbol, "result": result}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "strategy-signal":
        store = StreamStore()
        latest_quote = store.latest_quote(args.symbol)
        bars = store.latest_bars_1s(args.symbol, limit=30000)
        levels = calculate_mes_levels(bars, latest_quote=latest_quote).as_dict()
        stream_status = StreamStatus.from_store().as_dict()
        signal = opening_range_vwap_signal(
            levels,
            stream_ok=bool(stream_status.get("ok")),
            max_spread=args.max_spread,
            position_side=args.position_side,
            stop_price=args.stop_price,
            target_price=args.target_price,
        ).as_dict()
        result = {"signal": signal, "stream": stream_status}
        append_audit({"type": "strategy_signal", "strategy": args.strategy, "symbol": args.symbol, "result": result}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "signal-journal-once":
        store = StreamStore()
        latest_quote = store.latest_quote(args.symbol)
        bars = store.latest_bars_1s(args.symbol, limit=30000)
        levels = calculate_mes_levels(bars, latest_quote=latest_quote).as_dict()
        stream_status = StreamStatus.from_store().as_dict()
        signal = opening_range_vwap_signal(levels, stream_ok=bool(stream_status.get("ok")), max_spread=args.max_spread)
        record = append_signal(signal, stream_ok=bool(stream_status.get("ok")))
        append_audit({"type": "signal_journal_once", "strategy": args.strategy, "symbol": args.symbol, "record": record}, config["paths"]["audit_log"])
        print(json.dumps(record, indent=2))
    elif args.cmd == "shadow-report":
        records = read_signals(limit=args.limit)
        result = shadow_report_from_signals(records)
        append_audit({"type": "shadow_report", "limit": args.limit, "result": {k: v for k, v in result.items() if k != "closed_trades"}}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd in {"ibkr-health", "broker-health"}:
        result = adapter.health()
        append_audit({"type": "broker_health", "result": result}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "broker-positions":
        result = adapter.list_positions()
        append_audit({"type": "broker_positions", "count": len(result)}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "broker-open-orders":
        result = adapter.list_open_orders()
        append_audit({"type": "broker_open_orders", "count": len(result)}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "backtest-or-vwap":
        store = StreamStore()
        bars = store.latest_bars_1s(args.symbol, limit=args.limit)
        params = BacktestParams(
            symbol=args.symbol,
            contracts=args.contracts,
            slippage_ticks=args.slippage_ticks,
            max_spread=args.max_spread,
            max_trade_loss_usd=args.max_trade_loss_usd,
        )
        report = backtest_or_vwap(bars, params)
        result = report.as_dict()
        if args.output:
            out = write_backtest_report(report, args.output)
            result["output"] = str(out)
        append_audit({"type": "backtest_or_vwap", "result": {"metrics": result["metrics"], "verdict": result["verdict"]}}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))
    elif args.cmd == "broker-preview":
        intent = _load_intent(args.intent_json)
        decision = evaluate_intent(intent, config)
        if not decision.approved:
            result = {"preview_only": True, "risk_approved": False, "risk_decision": asdict(decision)}
        else:
            try:
                preview = adapter.preview_order(intent)
                result = {"risk_approved": True, "risk_decision": asdict(decision), "preview": preview}
            except IBKRSafetyError as exc:
                result = {"preview_only": True, "risk_approved": True, "error": str(exc)}
        append_audit({"type": "broker_preview", "intent_id": intent.intent_id, "result": result}, config["paths"]["audit_log"])
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
