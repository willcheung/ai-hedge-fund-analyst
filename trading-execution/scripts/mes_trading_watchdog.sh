#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_EXECUTION_ROOT:?Explicit private path required}"
: "${ANALYST_HERMES_HOME:?Explicit private path required}"
set -euo pipefail
cd "${ANALYST_EXECUTION_ROOT}"
export PYTHONPATH=${ANALYST_EXECUTION_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}
STATE=${ANALYST_EXECUTION_ROOT}/state/watchdog_state.json
TMP=${STATE}.tmp
mkdir -p "${ANALYST_EXECUTION_ROOT}/state"
now=$(date -Is)
stream_json=$("${ANALYST_HERMES_HOME}/hermes-agent/venv/bin/python" -m trading_execution.cli stream-status 2>/dev/null || true)
health_json=$("${ANALYST_HERMES_HOME}/hermes-agent/venv/bin/python" -m trading_execution.cli ibkr-health 2>/dev/null || true)
stream_ok=$("${ANALYST_HERMES_HOME}/hermes-agent/venv/bin/python" - "$stream_json" <<'PY'
import json, sys
try:
    print(str(bool(json.loads(sys.argv[1]).get('ok'))).lower())
except Exception:
    print('false')
PY
)
broker_connected=$("${ANALYST_HERMES_HOME}/hermes-agent/venv/bin/python" - "$health_json" <<'PY'
import json, sys
try:
    print(str(bool(json.loads(sys.argv[1]).get('connected'))).lower())
except Exception:
    print('false')
PY
)
cat > "$TMP" <<JSON
{"checked_at_utc":"$now","stream_ok":$stream_ok,"broker_connected":$broker_connected}
JSON
mv "$TMP" "$STATE"
if [[ "$broker_connected" != "true" ]]; then
  echo "$now IBKR_LOGIN_OR_API_NEEDED broker_connected=false"
elif [[ "$stream_ok" != "true" ]]; then
  echo "$now STREAM_STALE_OR_STARTING stream_ok=false"
else
  echo "$now OK broker_connected=true stream_ok=true"
fi
