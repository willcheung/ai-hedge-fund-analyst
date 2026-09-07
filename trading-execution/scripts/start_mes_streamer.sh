#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_EXECUTION_ROOT:?Explicit private path required}"
: "${ANALYST_HERMES_HOME:?Explicit private path required}"
set -euo pipefail
cd "${ANALYST_EXECUTION_ROOT}"
export PYTHONPATH=${ANALYST_EXECUTION_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}
export TRADING_EXECUTION_PROFILE_ENV=${ANALYST_HERMES_HOME}/profiles/tradingexecution/.env
if [[ -f "$TRADING_EXECUTION_PROFILE_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$TRADING_EXECUTION_PROFILE_ENV"
  set +a
fi

PYTHON=${ANALYST_HERMES_HOME}/hermes-agent/venv/bin/python
STATE_DIR=${ANALYST_EXECUTION_ROOT}/state
LOGIN_STATE="$STATE_DIR/ibkr_login_required.json"
HOST=${IBKR_HOST:-127.0.0.1}
PORT=${IBKR_PORT:-4001}
CHECK_INTERVAL=${IBKR_LOGIN_CHECK_INTERVAL_SECONDS:-60}
STREAM_RESTART_DELAY=${MES_STREAM_RESTART_DELAY_SECONDS:-15}
mkdir -p "$STATE_DIR"

port_open() {
  "$PYTHON" - "$HOST" "$PORT" <<'PY'
import socket
import sys
host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket()
sock.settimeout(2.0)
try:
    sock.connect((host, port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

write_login_required() {
  local now
  now=$(date -Is)
  cat > "$LOGIN_STATE.tmp" <<JSON
{"state":"login_required","checked_at":"$now","host":"$HOST","port":$PORT,"message":"IBKR Gateway is not authenticated/API-ready; log in through noVNC, then this streamer will resume automatically."}
JSON
  mv "$LOGIN_STATE.tmp" "$LOGIN_STATE"
}

clear_login_required() {
  rm -f "$LOGIN_STATE"
}

last_notice=0
while true; do
  while ! port_open; do
    write_login_required
    now_epoch=$(date +%s)
    if (( now_epoch - last_notice >= CHECK_INTERVAL )); then
      echo "$(date -Is) IBKR_LOGIN_REQUIRED host=$HOST port=$PORT not listening; streamer waiting instead of restart-spamming"
      last_notice=$now_epoch
    fi
    sleep "$CHECK_INTERVAL"
  done

  clear_login_required
  echo "$(date -Is) IBKR_API_READY host=$HOST port=$PORT; backfilling current MES front contract before stream"
  "$PYTHON" -m trading_execution.cli backfill-rth --symbol MES >/tmp/mes_streamer_backfill.log 2>&1 || cat /tmp/mes_streamer_backfill.log
  echo "$(date -Is) IBKR_API_READY host=$HOST port=$PORT; starting MES stream"
  set +e
  "$PYTHON" -m trading_execution.cli stream-mes
  rc=$?
  set -e
  echo "$(date -Is) MES_STREAM_EXITED rc=$rc; rechecking IBKR API before restart"
  sleep "$STREAM_RESTART_DELAY"
done
