#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_EXECUTION_ROOT:?Explicit private path required}"
# Deterministic IBKR login handoff for the MES VPS stack.
# This prepares a fresh paper/IB API Gateway login screen, opens a temporary
# Cloudflare noVNC URL, and prints only the URL/password the operator needs.
set -euo pipefail
umask 077

ROOT=${ANALYST_EXECUTION_ROOT}
STATE_DIR="$ROOT/state"
PASS_FILE="$STATE_DIR/ibkr_vnc_pass"
HANDOFF_JSON="$STATE_DIR/ibkr_login_handoff.json"
TUNNEL_LOG="$STATE_DIR/cloudflared-ibkr.log"
TUNNEL_PID_FILE="$STATE_DIR/cloudflared-ibkr.pid"
DISPLAY_NUM=:1
NOVNC_LOCAL_URL=http://127.0.0.1:6080/vnc.html
PUBLIC_URL=""
RESTART_GATEWAY=auto
OPEN_TUNNEL=1
STOP_STREAMER=1
DRY_RUN=0
TIMEOUT_SECONDS=75

usage() {
  cat <<'EOF'
Usage: scripts/prepare_ibkr_login_handoff.sh [options]

Options:
  --force-restart       Always restart the IBKR GUI stack and rotate VNC password.
  --no-restart          Do not restart Gateway; reuse the current GUI/noVNC stack.
  --no-tunnel           Do not start Cloudflare; print local readiness only.
  --keep-streamer       Do not stop mes-streamer/mes-15s-evaluator first.
  --dry-run             Check dependencies and current state without changing anything.
  -h, --help            Show this help.

Default behavior:
  - stops dependent MES services to avoid API reconnect loops
  - restarts Gateway only if API is not already connected or --force-restart is used
  - rotates the VNC password when restarting Gateway
  - forces login toggles to IB API + Paper Trading on the 1280x900 login screen
  - starts a Cloudflare quick tunnel and records its PID for finish/cleanup
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force-restart) RESTART_GATEWAY=force ;;
    --no-restart) RESTART_GATEWAY=never ;;
    --no-tunnel) OPEN_TUNNEL=0 ;;
    --keep-streamer) STOP_STREAMER=0 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing required command: $1" >&2; exit 1; }
}

for cmd in systemctl curl openssl ss pgrep pkill python3; do need "$cmd"; done
if [[ "$OPEN_TUNNEL" == "1" ]]; then need cloudflared; fi
need import
need tesseract
need xdotool

cd "$ROOT"

api_connected() {
  ss -ltnp 2>/dev/null | grep -qE ':4001\b.*java'
}

kill_existing_tunnel() {
  if [[ -s "$TUNNEL_PID_FILE" ]]; then
    local old_pid
    old_pid=$(cat "$TUNNEL_PID_FILE" 2>/dev/null || true)
    if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$TUNNEL_PID_FILE"
  fi
  pkill -f 'cloudflared tunnel --url http://127\.0\.0\.1:6080' 2>/dev/null || true
}

rotate_password() {
  umask 077
  openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 14 > "$PASS_FILE"
  chmod 600 "$PASS_FILE"
}

wait_for_local_novnc() {
  for _ in $(seq 1 "$TIMEOUT_SECONDS"); do
    if curl -fsS -I "$NOVNC_LOCAL_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "local noVNC did not become ready at $NOVNC_LOCAL_URL" >&2
  return 1
}

capture_ocr() {
  DISPLAY="$DISPLAY_NUM" import -window root "$STATE_DIR/ibkr_screen.png" >/dev/null 2>&1 || true
  tesseract "$STATE_DIR/ibkr_screen.png" stdout 2>/dev/null || true
}

wait_for_login_screen() {
  local text
  for _ in $(seq 1 "$TIMEOUT_SECONDS"); do
    text=$(capture_ocr)
    if printf '%s' "$text" | grep -Eiq 'IB Gateway|Username|Password|Trading Mode|Paper Trading'; then
      printf '%s\n' "$text" > "$STATE_DIR/ibkr_login_screen.ocr.txt"
      return 0
    fi
    sleep 1
  done
  echo "IBKR login screen was not detected; see $STATE_DIR/ibkr_screen.png" >&2
  return 1
}

force_paper_ibapi_toggles() {
  # Coordinates are stable because mes-ibkr-gui.service starts Xvfb at 1280x900.
  # IB API center ~= (766,338), Paper Trading center ~= (766,381).
  DISPLAY="$DISPLAY_NUM" xdotool mousemove 766 338 click 1 >/dev/null 2>&1 || true
  sleep 0.2
  DISPLAY="$DISPLAY_NUM" xdotool mousemove 766 381 click 1 >/dev/null 2>&1 || true
  sleep 0.5
  capture_ocr > "$STATE_DIR/ibkr_login_screen.ocr.txt" || true
}

start_tunnel() {
  rm -f "$TUNNEL_LOG" "$TUNNEL_PID_FILE"
  cloudflared tunnel --url http://127.0.0.1:6080 > "$TUNNEL_LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$TUNNEL_PID_FILE"
  for _ in $(seq 1 45); do
    PUBLIC_URL=$(grep -Eo 'https://[-a-zA-Z0-9.]+\.trycloudflare\.com' "$TUNNEL_LOG" | tail -1 || true)
    if [[ -n "$PUBLIC_URL" ]]; then
      if curl -fsS -I "${PUBLIC_URL}/vnc.html?autoconnect=1&resize=remote" >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 1
  done
  echo "Timed out waiting for Cloudflare URL; log: $TUNNEL_LOG" >&2
  return 1
}

if [[ "$DRY_RUN" == "1" ]]; then
  echo "dry_run: ok"
  echo "api_connected: $(api_connected && echo yes || echo no)"
  echo "gui_service: $(systemctl --user is-active mes-ibkr-gui.service 2>/dev/null || true)"
  echo "streamer_service: $(systemctl --user is-active mes-streamer.service 2>/dev/null || true)"
  echo "cloudflared: $(pgrep -xaf 'cloudflared.*tunnel' || true)"
  exit 0
fi

mkdir -p "$STATE_DIR"
kill_existing_tunnel

should_restart=0
case "$RESTART_GATEWAY" in
  force) should_restart=1 ;;
  never) should_restart=0 ;;
  auto)
    if ! systemctl --user is-active --quiet mes-ibkr-gui.service; then
      should_restart=1
    elif ! curl -fsS -I "$NOVNC_LOCAL_URL" >/dev/null 2>&1; then
      should_restart=1
    elif ! api_connected; then
      # Usually the daily-login-needed state. Restarting gives a clean login screen.
      should_restart=1
    fi
    ;;
  *) echo "invalid restart mode: $RESTART_GATEWAY" >&2; exit 2 ;;
esac

if api_connected && [[ "$RESTART_GATEWAY" != "force" ]]; then
  echo "IBKR Gateway already appears logged in on API port 4001; no login handoff opened."
  echo "Use --force-restart only if you intentionally want to kick the current Gateway session back to the login screen."
  exit 0
fi

if [[ "$STOP_STREAMER" == "1" ]]; then
  systemctl --user stop mes-15s-evaluator.service 2>/dev/null || true
  systemctl --user stop mes-streamer.service 2>/dev/null || true
fi

if [[ "$should_restart" == "1" ]]; then
  rotate_password
  systemctl --user restart mes-ibkr-gui.service
fi

wait_for_local_novnc
wait_for_login_screen || true
force_paper_ibapi_toggles

if [[ "$OPEN_TUNNEL" == "1" ]]; then
  start_tunnel
else
  PUBLIC_URL=""
fi

PUBLIC_URL_VALUE="$PUBLIC_URL" python3 - "$TUNNEL_PID_FILE" "$HANDOFF_JSON" "$NOVNC_LOCAL_URL" <<'PY'
import json, os, sys
from datetime import datetime, timedelta, timezone
public_url = os.environ.get("PUBLIC_URL_VALUE", "")
state = {
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "expires_at_utc": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    "public_url": public_url,
    "novnc_url": (public_url + "/vnc.html?autoconnect=1&resize=remote") if public_url else "",
    "tunnel_pid": open(sys.argv[1]).read().strip() if os.path.exists(sys.argv[1]) else None,
    "local_novnc_url": sys.argv[3],
    "mode": "paper",
    "api_type": "IB API",
    "notes": "Browser/VNC login handoff only; no broker credentials are stored.",
}
open(sys.argv[2], "w").write(json.dumps(state, indent=2) + "\n")
PY

if [[ -n "$PUBLIC_URL" ]]; then
  echo "IBKR login handoff ready"
  echo "noVNC URL: ${PUBLIC_URL}/vnc.html?autoconnect=1&resize=remote"
else
  echo "IBKR login handoff ready (local noVNC only)"
  echo "local noVNC URL: $NOVNC_LOCAL_URL"
fi
echo "VNC password: $(cat "$PASS_FILE")"
echo "Expected screen: API Type = IB API; Trading Mode = Paper Trading / SIMULATED TRADING"
echo "After login run: scripts/finish_ibkr_login_handoff.sh"
