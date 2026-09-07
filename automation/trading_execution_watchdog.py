#!/usr/bin/env python3
"""Trading execution watchdog for Hermes cron.

Runs the trading-execution status probe and prints a Slack-ready alert only when:
- the health state changes, or
- the system remains unhealthy and the reminder interval has elapsed.

Empty stdout means SILENT when used with cron no_agent=True.
Never prints secrets.
"""
from __future__ import annotations
from automation_paths import configured_text

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(configured_text("${ANALYST_EXECUTION_ROOT}"))
STATUS_SCRIPT = REPO / "scripts" / "trading_status.py"
STATE_FILE = REPO / "state" / "watchdog_state.json"
REMINDER_SECONDS = 60 * 60


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True))
    tmp.replace(STATE_FILE)


def run_status() -> tuple[dict | None, str | None]:
    if not STATUS_SCRIPT.exists():
        return None, f"missing status script: {STATUS_SCRIPT}"

    env = os.environ.copy()
    env["TRADING_EXECUTION_PROFILE_ENV"] = configured_text("${ANALYST_HERMES_HOME}/profiles/tradingexecution/.env")

    try:
        proc = subprocess.run(
            [sys.executable, str(STATUS_SCRIPT)],
            cwd=str(REPO),
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return None, "status probe timed out after 60s"
    except Exception as exc:
        return None, f"status probe failed: {exc}"

    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "unknown error").strip()[-500:]
        return None, f"status script exited {proc.returncode}: {msg}"

    try:
        return json.loads(proc.stdout), None
    except Exception as exc:
        return None, f"status JSON parse failed: {exc}"


def health_key(status: dict | None, error: str | None) -> str:
    if error:
        return "probe_error"
    assert status is not None
    pieces = [
        f"broker={bool(status.get('broker_health_ok'))}",
        f"monitor={bool(status.get('monitor_ok'))}",
        f"orders={bool(status.get('order_placement_enabled'))}",
        f"snapshot={bool(status.get('market_snapshot_connected'))}",
        f"stream={bool(status.get('stream_ok'))}",
        "alerts=" + ",".join(status.get("monitor_alerts") or []),
    ]
    return "|".join(pieces)


def format_message(status: dict | None, error: str | None, changed: bool) -> str:
    if error:
        return (
            "🚨 IBKR MES trading watchdog\n"
            f"Status probe failed: {error}\n"
            "Order placement should be treated as disabled until this is fixed."
        )

    assert status is not None
    broker_ok = bool(status.get("broker_health_ok"))
    monitor_ok = bool(status.get("monitor_ok"))
    quote_ok = bool(status.get("market_snapshot_connected"))
    stream_ok = bool(status.get("stream_ok"))
    order_enabled = bool(status.get("order_placement_enabled"))
    alerts = status.get("monitor_alerts") or []
    broker_error = status.get("broker_health_error")

    healthy = broker_ok and monitor_ok and quote_ok and stream_ok and not alerts
    icon = "🟢" if healthy else "🚨"
    label = "recovered" if healthy and changed else "status changed" if changed else "still unhealthy"

    lines = [
        f"{icon} IBKR MES trading {label}",
        f"Broker health: {'ok' if broker_ok else 'FAIL'}",
        f"Market data: {'ok' if quote_ok else 'not connected'}",
        f"Stream: {'ok' if stream_ok else 'stale/missing'} age={status.get('stream_latest_quote_age_seconds')}",
        f"Monitor: {'ok' if monitor_ok else 'FAIL'}",
        f"Order placement: {'enabled' if order_enabled else 'disabled'}",
        f"Mode: {status.get('execution_mode', 'unknown')}",
        f"Symbol: {status.get('primary_symbol', 'MES')}",
    ]
    if alerts:
        lines.append("Alerts: " + ", ".join(alerts))
    if broker_error:
        lines.append("Broker error: " + str(broker_error)[:300])
    if not order_enabled:
        lines.append("Safety: no unguarded live order placement.")
    return "\n".join(lines)


def main() -> int:
    status, error = run_status()
    key = health_key(status, error)
    now = int(time.time())
    prior = load_state()
    previous_key = prior.get("key")
    last_sent = int(prior.get("last_sent", 0) or 0)

    changed = key != previous_key
    unhealthy = bool(error) or not (
        status
        and status.get("broker_health_ok")
        and status.get("monitor_ok")
        and status.get("market_snapshot_connected")
        and status.get("stream_ok")
        and not (status.get("monitor_alerts") or [])
    )

    should_send = changed or (unhealthy and now - last_sent >= REMINDER_SECONDS)

    state = {"key": key, "last_check": now, "last_sent": last_sent}
    if should_send:
        print(format_message(status, error, changed))
        state["last_sent"] = now
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
