#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_HERMES_HOME:?Explicit private path required}"
set -euo pipefail
"${ANALYST_HERMES_HOME}/scripts/meetkevin_youtube_ingest.py" --hours 30 --limit 8
