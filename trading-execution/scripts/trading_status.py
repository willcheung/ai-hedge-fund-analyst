#!/usr/bin/env python3
from __future__ import annotations
from trading_execution.config import configured_text

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(configured_text('${ANALYST_EXECUTION_ROOT}'))
PROFILE_ENV = Path(configured_text('${ANALYST_HERMES_HOME}/profiles/tradingexecution/.env'))
AUDIT = ROOT / 'state/audit.jsonl'

REQUIRED = [
    'IBKR_HOST',
    'IBKR_PORT',
    'IBKR_CLIENT_ID',
    'IBKR_MODE',
]


def load_env_file(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    if not path.exists():
        return env
    for line in path.read_text(errors='ignore').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def run_cmd(args: list[str], timeout: int = 20) -> dict[str, object]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(ROOT),
            env=load_env_file(PROFILE_ENV),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        out = (proc.stdout or '').strip()
        parsed = None
        if out.startswith('{') or out.startswith('['):
            try:
                parsed = json.loads(out)
            except json.JSONDecodeError:
                parsed = None
        return {'ok': proc.returncode == 0, 'exit_code': proc.returncode, 'json': parsed, 'stdout_tail': out[-500:]}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'exit_code': 'timeout', 'json': None, 'stdout_tail': ''}
    except Exception as exc:
        return {'ok': False, 'exit_code': 'error', 'json': None, 'stdout_tail': str(exc)}


def last_audit_line() -> dict[str, object] | None:
    if not AUDIT.exists():
        return None
    try:
        lines = [ln for ln in AUDIT.read_text(errors='ignore').splitlines() if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return {'unparseable': True}


def _positive_number(value: object) -> float | None:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if numeric != numeric or numeric <= 0:
        return None
    return numeric


def quote_quality(quote: dict[str, object] | None) -> tuple[bool, str]:
    if not quote:
        return False, 'missing_quote'
    if quote.get('market_data_type') != 1:
        return False, 'not_realtime_market_data'
    bid = _positive_number(quote.get('bid'))
    ask = _positive_number(quote.get('ask'))
    last = _positive_number(quote.get('last'))
    if last is None:
        return False, 'missing_last'
    if bid is None or ask is None or ask < bid:
        return False, 'invalid_bid_ask'
    return True, 'ok'


def main() -> int:
    env = load_env_file(PROFILE_ENV)
    # Defaults in config are sufficient for local paper-readiness; env presence is not a secret check.
    missing = [key for key in REQUIRED if not env.get(key)]
    now = datetime.now(timezone.utc).isoformat()

    monitor = run_cmd(['python', '-m', 'trading_execution.cli', 'monitor-once'], timeout=15)
    broker = run_cmd(['python', '-m', 'trading_execution.cli', 'ibkr-health'], timeout=30)
    snapshot = run_cmd(['python', '-m', 'trading_execution.cli', 'market-snapshot', '--symbol', 'MES'], timeout=30)
    stream = run_cmd(['python', '-m', 'trading_execution.cli', 'stream-status'], timeout=15)

    broker_json = broker.get('json') if isinstance(broker.get('json'), dict) else {}
    monitor_json = monitor.get('json') if isinstance(monitor.get('json'), dict) else {}
    snapshot_json = snapshot.get('json') if isinstance(snapshot.get('json'), dict) else {}
    stream_json = stream.get('json') if isinstance(stream.get('json'), dict) else {}
    alerts = monitor_json.get('alerts', []) if isinstance(monitor_json, dict) else []
    stream_latest_quote = stream_json.get('latest_quote') if isinstance(stream_json.get('latest_quote'), dict) else {}
    snapshot_quote = {
        'contract': snapshot_json.get('contract'),
        'bid': snapshot_json.get('bid'),
        'ask': snapshot_json.get('ask'),
        'last': snapshot_json.get('last'),
        'spread': snapshot_json.get('spread'),
        'market_data_type': snapshot_json.get('market_data_type'),
    }
    quote_source = stream_latest_quote or snapshot_quote
    quote_quality_ok, quote_quality_reason = quote_quality(quote_source)

    report = {
        'checked_at_utc': now,
        'profile_env_present': PROFILE_ENV.exists(),
        'configured_for': 'IBKR MES paper-first execution',
        'env_overrides_present': not missing,
        'missing_optional_env_keys': missing,
        'execution_mode': env.get('IBKR_MODE', env.get('HERMES_TRADING_EXECUTION_MODE', 'paper(default)')),
        'ibkr_host_configured': bool(env.get('IBKR_HOST')),
        'ibkr_port': broker_json.get('port') or env.get('IBKR_PORT', 'config/default'),
        'primary_symbol': 'MES',
        'mes_quote': snapshot_quote,
        'quote_quality_ok': quote_quality_ok,
        'quote_quality_reason': quote_quality_reason,
        'stream_ok': bool(stream_json.get('ok')),
        'stream_latest_quote_age_seconds': stream_json.get('latest_quote_age_seconds'),
        'stream_bars_1s_count': stream_json.get('bars_1s_count'),
        'stream_latest_quote': stream_json.get('latest_quote'),
        'monitor_ok': monitor['ok'],
        'monitor_alerts': alerts,
        'broker_health_ok': bool(broker_json.get('connected')),
        'broker_health_error': broker_json.get('error') or (None if broker['ok'] else broker.get('stdout_tail')),
        'market_snapshot_connected': bool(snapshot_json.get('connected')) or bool(stream_json.get('ok')),
        'market_snapshot_error': None if stream_json.get('ok') else (snapshot_json.get('error') if isinstance(snapshot_json, dict) else None),
        'order_placement_enabled': bool(broker_json.get('order_placement_enabled')),
        'last_audit': last_audit_line(),
    }

    print(json.dumps(report, indent=2))
    return 0 if report['monitor_ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
