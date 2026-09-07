#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_EXECUTION_ROOT:?Explicit private path required}"
: "${ANALYST_HERMES_HOME:?Explicit private path required}"
set -euo pipefail
cd "${ANALYST_EXECUTION_ROOT}"
export PYTHONPATH=${ANALYST_EXECUTION_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}
LOG=${ANALYST_EXECUTION_ROOT}/state/mes_signal_e2e_15s_loop.log
mkdir -p "${ANALYST_EXECUTION_ROOT}/state"
printf '%s started 15s MES signal E2E loop\n' "$(date -Is)" >> "$LOG"
while true; do
  started=$(date +%s)
  rc=0
  output="$("${ANALYST_HERMES_HOME}/hermes-agent/venv/bin/python" "${ANALYST_HERMES_HOME}/profiles/tradingexecution/scripts/mes_signal_e2e_tester.py" 2>&1)" || rc=$?
  if [[ -n "$output" || "$rc" -ne 0 ]]; then
    printf '%s rc=%s\n%s\n' "$(date -Is)" "$rc" "$output" | tee -a "$LOG"
  else
    printf '%s ok silent\n' "$(date -Is)" >> "$LOG"
  fi
  elapsed=$(( $(date +%s) - started ))
  sleep_for=$(( 15 - elapsed ))
  if (( sleep_for < 1 )); then
    sleep_for=1
  fi
  sleep "$sleep_for"
done
