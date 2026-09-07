#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
: "${ANALYST_HERMES_HOME:?Explicit private path required}"
set -euo pipefail
ENV_FILE="${HERMES_ENV_FILE:-${ANALYST_HERMES_HOME}/.env}"
KEY="${TAVILY_API_KEY:-}"
if [[ -z "$KEY" && -f "$ENV_FILE" ]]; then
  # Read TAVILY_API_KEY without sourcing arbitrary shell from .env.
  KEY="$(python3 - "$ENV_FILE" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
for line in path.read_text(errors='ignore').splitlines():
    s=line.strip()
    if not s or s.startswith('#') or '=' not in s:
        continue
    k,v=s.split('=',1)
    if k.strip() == 'TAVILY_API_KEY':
        print(v.strip().strip('"').strip("'"))
        break
PY
)"
fi
if [[ -z "$KEY" ]]; then
  echo "TAVILY_API_KEY is not set in environment or $ENV_FILE" >&2
  exit 1
fi
exec npx -y mcp-remote "https://mcp.tavily.com/mcp/?tavilyApiKey=${KEY}"
