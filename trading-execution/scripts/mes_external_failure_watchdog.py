#!/usr/bin/env python3
"""External MES trading platform failure watchdog.

Runs outside Hermes cron/gateway under user systemd and sends Slack alerts directly
via Slack Web API. Healthy/recovered state is intentionally silent.

Secrets are read from local env files but never printed.
"""
from __future__ import annotations
from trading_execution.config import configured_text

import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(configured_text("${ANALYST_EXECUTION_ROOT}"))
STATUS_SCRIPT = REPO / "scripts" / "trading_status.py"
PYTHON = Path(configured_text("${ANALYST_HERMES_HOME}/hermes-agent/venv/bin/python"))
HERMES_ENV = Path(configured_text("${ANALYST_HERMES_HOME}/.env"))
PROFILE_ENV = Path(configured_text("${ANALYST_HERMES_HOME}/profiles/tradingexecution/.env"))
STATE_FILE = REPO / "state" / "external_failure_watchdog_state.json"
LOGIN_REQUIRED_FILE = REPO / "state" / "ibkr_login_required.json"
SLACK_CHANNEL = os.environ.get("ANALYST_SLACK_CHANNEL", "")
REMINDER_SECONDS = 60 * 60
LOGIN_REQUIRED_REMINDER_SECONDS = 6 * 60 * 60
AUTO_HEAL_COOLDOWN_SECONDS = 5 * 60


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


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
    python = str(PYTHON if PYTHON.exists() else Path(sys.executable))
    env = os.environ.copy()
    env.update(load_env_file(PROFILE_ENV))
    env["PYTHONPATH"] = str(REPO / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    if PYTHON.exists():
        env["PATH"] = str(PYTHON.parent) + os.pathsep + env.get("PATH", "")
    try:
        proc = subprocess.run(
            [python, str(STATUS_SCRIPT)],
            cwd=str(REPO),
            env=env,
            text=True,
            capture_output=True,
            timeout=75,
        )
    except subprocess.TimeoutExpired:
        return None, "status probe timed out after 75s"
    except Exception as exc:
        return None, f"status probe failed: {exc}"

    # trading_status exits non-zero when monitor-once is unhealthy, but still prints
    # the JSON report we need. Prefer parsing stdout before treating it as a probe failure.
    try:
        if proc.stdout.strip():
            return json.loads(proc.stdout), None
    except Exception:
        pass
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "unknown error").strip()[-500:]
        return None, f"status script exited {proc.returncode}: {msg}"
    return None, "status JSON parse failed"


def port_listening(host: str = "127.0.0.1", port: int = 4001, timeout: float = 1.0) -> bool:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def login_required(status: dict | None, error: str | None) -> bool:
    if error:
        return False
    if LOGIN_REQUIRED_FILE.exists():
        return True
    if not status:
        return False
    broker_error = str(status.get("broker_health_error") or "")
    ibkr_port_raw = status.get("ibkr_port") or 4001
    try:
        ibkr_port = int(ibkr_port_raw)
    except (TypeError, ValueError):
        ibkr_port = 4001
    disconnected = not bool(status.get("broker_health_ok"))
    refused = "ConnectionRefusedError" in broker_error or "Connect call failed" in broker_error or "Errno 111" in broker_error
    return disconnected and (refused or not port_listening(port=ibkr_port))


def health_key(status: dict | None, error: str | None) -> str:
    if error:
        return "probe_error:" + error[:160]
    if login_required(status, error):
        return "ibkr_login_required"
    assert status is not None
    pieces = [
        f"broker={bool(status.get('broker_health_ok'))}",
        f"monitor={bool(status.get('monitor_ok'))}",
        f"orders={bool(status.get('order_placement_enabled'))}",
        f"snapshot={bool(status.get('market_snapshot_connected'))}",
        f"stream={bool(status.get('stream_ok'))}",
        f"quote_quality={bool(status.get('quote_quality_ok'))}:{status.get('quote_quality_reason') or 'unknown'}",
        "alerts=" + ",".join(status.get("monitor_alerts") or []),
    ]
    return "|".join(pieces)


def run_systemctl(*args: str) -> bool:
    proc = subprocess.run(["systemctl", "--user", *args], text=True, capture_output=True, timeout=30)
    if proc.returncode != 0:
        print((proc.stderr or proc.stdout or "systemctl failed").strip()[-500:], file=sys.stderr)
    return proc.returncode == 0


def auto_heal(status: dict | None, error: str | None, *, now: int, prior: dict) -> list[str]:
    if error or not status or login_required(status, error):
        return []
    last_heal = int(prior.get("last_auto_heal", 0) or 0)
    if now - last_heal < AUTO_HEAL_COOLDOWN_SECONDS:
        return []

    reason = str(status.get("quote_quality_reason") or "")
    stream_bad = not bool(status.get("stream_ok"))
    quote_bad = status.get("quote_quality_ok") is False and reason in {
        "invalid_bid_ask",
        "missing_last",
        "not_realtime_market_data",
        "missing_quote",
    }
    actions: list[str] = []
    if stream_bad or quote_bad:
        why = "stream_stale" if stream_bad else reason
        if run_systemctl("restart", "mes-streamer.service"):
            actions.append(f"restart_mes_streamer:{why}")
    return actions


def is_unhealthy(status: dict | None, error: str | None) -> bool:
    return bool(error) or not (
        status
        and status.get("broker_health_ok")
        and status.get("monitor_ok")
        and status.get("market_snapshot_connected")
        and status.get("stream_ok")
        and status.get("quote_quality_ok") is not False
        and not (status.get("monitor_alerts") or [])
    )


def format_message(status: dict | None, error: str | None, changed: bool) -> str:
    if error:
        return (
            "🚨 IBKR MES trading watchdog\n"
            f"Status probe failed: {error}\n"
            "Hermes gateway is bypassed; this alert came directly from systemd → Slack."
        )

    assert status is not None
    if login_required(status, error):
        port = status.get("ibkr_port", 4001)
        broker_error = str(status.get("broker_health_error") or "")[:220]
        return "\n".join(
            [
                "🔐 IBKR Gateway login required",
                f"API port {port} is not ready, so MES market-data streaming is paused/backing off instead of restart-spamming.",
                "Action: log into IBKR Gateway through noVNC/Cloudflare; the streamer will resume automatically once the API is live.",
                "Safety: no broker orders can route while IBKR API is disconnected.",
                "Delivery: direct systemd → Slack, independent of Hermes gateway/cron.",
                f"Broker error: {broker_error}" if broker_error else "",
            ]
        ).strip()

    alerts = status.get("monitor_alerts") or []
    lines = [
        f"🚨 IBKR MES trading {'status changed' if changed else 'still unhealthy'}",
        f"Broker health: {'ok' if status.get('broker_health_ok') else 'FAIL'}",
        f"Market data: {'ok' if status.get('market_snapshot_connected') else 'not connected'}",
        f"Quote quality: {'ok' if status.get('quote_quality_ok') else status.get('quote_quality_reason', 'unknown')}",
        f"Stream: {'ok' if status.get('stream_ok') else 'stale/missing'} age={status.get('stream_latest_quote_age_seconds')}",
        f"Monitor: {'ok' if status.get('monitor_ok') else 'FAIL'}",
        f"Order placement: {'enabled' if status.get('order_placement_enabled') else 'disabled'}",
        f"Mode: {status.get('execution_mode', 'unknown')}",
        "Delivery: direct systemd → Slack, independent of Hermes gateway/cron.",
    ]
    if alerts:
        lines.append("Alerts: " + ", ".join(map(str, alerts)))
    broker_error = status.get("broker_health_error")
    if broker_error:
        lines.append("Broker error: " + str(broker_error)[:300])
    if not status.get("order_placement_enabled"):
        lines.append("Safety: no unguarded live order placement.")
    return "\n".join(lines)


def slack_post(message: str, dry_run: bool = False) -> None:
    if dry_run:
        print("DRY_RUN would send Slack alert to", SLACK_CHANNEL)
        print(message)
        return
    if not SLACK_CHANNEL.strip():
        raise ValueError("ANALYST_SLACK_CHANNEL is required")
    token = load_env_file(HERMES_ENV).get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN not found in local env")
    data = urllib.parse.urlencode({"channel": SLACK_CHANNEL, "text": message}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError("Slack post failed: " + str(payload.get("error", "unknown_error")))


def main() -> int:
    status, error = run_status()
    now = int(time.time())
    prior = load_state()
    heal_actions = auto_heal(status, error, now=now, prior=prior)
    if heal_actions:
        prior["last_auto_heal"] = now
        # Give restarted services a short chance to refresh, then re-check before alerting.
        time.sleep(20)
        status, error = run_status()

    unhealthy = is_unhealthy(status, error)
    key = health_key(status, error)
    previous_key = prior.get("key")
    last_sent = int(prior.get("last_sent", 0) or 0)
    changed = key != previous_key
    should_send = unhealthy and (
        changed
        or now - last_sent >= (LOGIN_REQUIRED_REMINDER_SECONDS if login_required(status, error) else REMINDER_SECONDS)
    )

    state = {"key": key, "last_check": now, "last_sent": last_sent, "healthy": not unhealthy}
    if heal_actions:
        state["last_auto_heal"] = now
        state["auto_heal_actions"] = heal_actions
    elif prior.get("last_auto_heal"):
        state["last_auto_heal"] = prior.get("last_auto_heal")
    try:
        if should_send:
            slack_post(format_message(status, error, changed), dry_run=os.environ.get("SLACK_DRY_RUN") == "1")
            state["last_sent"] = now
        save_state(state)
        return 0
    except Exception as exc:
        # Let systemd journal capture delivery failures without printing secrets.
        print(f"external watchdog delivery failed: {exc}", file=sys.stderr)
        save_state(state)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
