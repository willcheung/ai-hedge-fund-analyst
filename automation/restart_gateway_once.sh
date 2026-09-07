#!/usr/bin/env bash
: "${ANALYST_ENABLE_LEGACY_OPS:?Set explicitly after reviewing and configuring this optional operation}"
set -euo pipefail
/usr/bin/systemctl --user restart hermes-gateway.service
