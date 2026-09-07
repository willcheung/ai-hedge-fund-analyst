#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_EXECUTION_ROOT:?Explicit private path required}"
set -euo pipefail
PASS_FILE=${ANALYST_EXECUTION_ROOT}/state/ibkr_vnc_pass
if [[ ! -s "$PASS_FILE" ]]; then
  echo "VNC password not found. Start mes-ibkr-gui.service first." >&2
  exit 1
fi
if ! curl -fsS -I http://127.0.0.1:6080/vnc.html >/dev/null; then
  echo "local noVNC is not responding on 127.0.0.1:6080. Check mes-ibkr-gui.service." >&2
  exit 1
fi
LOG=${ANALYST_EXECUTION_ROOT}/state/cloudflared-ibkr.log
rm -f "$LOG"
cloudflared tunnel --url http://127.0.0.1:6080 > "$LOG" 2>&1 &
PID=$!
echo "$PID" > "${ANALYST_EXECUTION_ROOT}/state/cloudflared-ibkr.pid"
for i in {1..30}; do
  URL=$(grep -Eo 'https://[-a-zA-Z0-9.]+\.trycloudflare\.com' "$LOG" | tail -1 || true)
  if [[ -n "$URL" ]]; then
    echo "noVNC URL: ${URL}/vnc.html?autoconnect=1&resize=remote"
    echo "VNC password: $(cat "$PASS_FILE")"
    echo "Tunnel PID: $PID (stop with: kill $PID)"
    exit 0
  fi
  sleep 1
done
echo "Timed out waiting for cloudflared URL; log: $LOG" >&2
exit 1
