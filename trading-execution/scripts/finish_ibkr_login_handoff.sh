#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_EXECUTION_ROOT:?Explicit private path required}"
: "${ANALYST_HERMES_HOME:?Explicit private path required}"
# Finish a deterministic IBKR login handoff: verify broker/API truth, restart
# MES streamer if needed, refresh levels/signal, then close the public tunnel.
set -euo pipefail

ROOT=${ANALYST_EXECUTION_ROOT}
STATE_DIR="$ROOT/state"
TUNNEL_PID_FILE="$STATE_DIR/cloudflared-ibkr.pid"
PY=${ANALYST_HERMES_HOME}/hermes-agent/venv/bin/python
STOP_TUNNEL=1
RESTART_STREAMER=auto
WAIT_SECONDS=90

usage() {
  cat <<'EOF'
Usage: scripts/finish_ibkr_login_handoff.sh [options]

Options:
  --keep-tunnel         Leave the Cloudflare tunnel running.
  --no-streamer         Do not start/restart mes-streamer.service.
  --force-streamer      Restart mes-streamer.service even if stream-status is already ok.
  -h, --help            Show this help.

Default behavior verifies API/broker truth, starts/restarts streamer only if stale,
checks MES levels/signal, checks watchdog status, and closes the public tunnel.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-tunnel) STOP_TUNNEL=0 ;;
    --no-streamer) RESTART_STREAMER=never ;;
    --force-streamer) RESTART_STREAMER=force ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT"

stream_ok() {
  "$PY" -m trading_execution.cli stream-status 2>/dev/null | grep -q '"ok": true'
}

stop_tunnel() {
  if [[ -s "$TUNNEL_PID_FILE" ]]; then
    local pid
    pid=$(cat "$TUNNEL_PID_FILE" 2>/dev/null || true)
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$TUNNEL_PID_FILE"
  fi
  pkill -f 'cloudflared tunnel --url http://127\.0\.0\.1:6080' 2>/dev/null || true
}

wait_stream_ok() {
  for _ in $(seq 1 "$WAIT_SECONDS"); do
    if stream_ok; then return 0; fi
    sleep 1
  done
  return 1
}

printf '== ibkr health ==\n'
"$PY" -m trading_execution.cli ibkr-health
printf '\n== broker positions ==\n'
"$PY" -m trading_execution.cli broker-positions
printf '\n== broker open orders ==\n'
"$PY" -m trading_execution.cli broker-open-orders

case "$RESTART_STREAMER" in
  never) ;;
  force)
    systemctl --user restart mes-streamer.service
    wait_stream_ok || true
    ;;
  auto)
    if ! stream_ok; then
      systemctl --user restart mes-streamer.service
      wait_stream_ok || true
    fi
    ;;
  *) echo "invalid streamer mode: $RESTART_STREAMER" >&2; exit 2 ;;
esac

printf '\n== stream status ==\n'
"$PY" -m trading_execution.cli stream-status || true
printf '\n== levels ==\n'
"$PY" -m trading_execution.cli levels --symbol MES || true
printf '\n== signal ==\n'
"$PY" -m trading_execution.cli signal-journal-once --symbol MES || true
printf '\n== watchdog ==\n'
systemctl --user --no-pager --plain status mes-trading-watchdog.service mes-trading-watchdog.timer | sed -n '1,90p' || true

if [[ "$STOP_TUNNEL" == "1" ]]; then
  stop_tunnel
fi

printf '\n== public tunnel ==\n'
if pgrep -xaf 'cloudflared.*tunnel' >/dev/null 2>&1; then
  pgrep -xaf 'cloudflared.*tunnel'
else
  echo 'closed'
fi
