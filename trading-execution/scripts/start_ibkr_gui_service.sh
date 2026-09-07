#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_EXECUTION_ROOT:?Explicit private path required}"
set -euo pipefail

STATE_DIR=${ANALYST_EXECUTION_ROOT}/state
LOG_DIR=${ANALYST_EXECUTION_ROOT}/state
DISPLAY_NUM=:1
PASS_FILE="$STATE_DIR/ibkr_vnc_pass"
NOVNC_HOST=127.0.0.1
NOVNC_PORT=6080
VNC_HOST=127.0.0.1
VNC_PORT=5901

mkdir -p "$STATE_DIR"
if [[ ! -s "$PASS_FILE" ]]; then
  umask 077
  openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 14 > "$PASS_FILE"
fi
chmod 600 "$PASS_FILE"

cleanup() {
  pkill -f 'Xvfb :1' 2>/dev/null || true
  pkill -f 'fluxbox -display :1' 2>/dev/null || true
  pkill -f 'x11vnc.*5901' 2>/dev/null || true
  pkill -f 'websockify.*6080' 2>/dev/null || true
  pkill -f '/opt/ibgateway/ibgateway|/usr/local/bin/ibgateway' 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cleanup
rm -f /tmp/.X1-lock

Xvfb "$DISPLAY_NUM" -screen 0 1280x900x24 -ac > "$LOG_DIR/xvfb-ibkr.log" 2>&1 &
XVFB_PID=$!
sleep 1
fluxbox -display "$DISPLAY_NUM" > "$LOG_DIR/fluxbox-ibkr.log" 2>&1 &
FLUX_PID=$!
x11vnc -display "$DISPLAY_NUM" -forever -shared -passwdfile "$PASS_FILE" -localhost -rfbport "$VNC_PORT" > "$LOG_DIR/x11vnc-ibkr.log" 2>&1 &
VNC_PID=$!
if [[ -d /usr/share/novnc ]]; then
  websockify --web=/usr/share/novnc "$NOVNC_HOST:$NOVNC_PORT" "$VNC_HOST:$VNC_PORT" > "$LOG_DIR/websockify-ibkr.log" 2>&1 &
else
  websockify "$NOVNC_HOST:$NOVNC_PORT" "$VNC_HOST:$VNC_PORT" > "$LOG_DIR/websockify-ibkr.log" 2>&1 &
fi
WS_PID=$!
sleep 2
DISPLAY="$DISPLAY_NUM" /opt/ibgateway/ibgateway > "$LOG_DIR/ibgateway.log" 2>&1 &
IB_PID=$!

echo "IBKR GUI stack started: DISPLAY=$DISPLAY_NUM, noVNC=http://$NOVNC_HOST:$NOVNC_PORT/vnc.html, VNC password file=$PASS_FILE"

while true; do
  for pid in "$XVFB_PID" "$VNC_PID" "$WS_PID" "$IB_PID"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "critical child $pid exited; restarting stack"
      exit 1
    fi
  done
  sleep 10
done
