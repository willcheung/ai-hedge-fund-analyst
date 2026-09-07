#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_EXECUTION_ROOT:?Explicit private path required}"
set -euo pipefail
# Share the authenticated, loopback-only GUI implementation.
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/start_ibkr_gui_service.sh" "$@"
