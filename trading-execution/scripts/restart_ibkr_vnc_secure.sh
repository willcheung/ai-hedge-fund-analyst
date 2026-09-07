#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_EXECUTION_ROOT:?Explicit private path required}"
set -euo pipefail
umask 077
STATE_DIR="${ANALYST_EXECUTION_ROOT}/state"
mkdir -p "$STATE_DIR"
PASS_FILE="$STATE_DIR/ibkr_vnc_pass"
if [ ! -s "$PASS_FILE" ]; then
  openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 12 > "$PASS_FILE"
fi
chmod 600 "$PASS_FILE"
pkill -f 'x11vnc.*5901' 2>/dev/null || true
pkill -f 'websockify.*6080' 2>/dev/null || true
x11vnc -display :1 -forever -shared -passwdfile "$PASS_FILE" -listen 127.0.0.1 -rfbport 5901 > "$STATE_DIR/x11vnc-ibkr.log" 2>&1 &
websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5901 > "$STATE_DIR/websockify-ibkr.log" 2>&1 &
echo "secure vnc restarted"
wait
