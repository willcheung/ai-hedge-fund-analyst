#!/usr/bin/env python3
"""Re-inventory Vercel deployments after bounded privacy cleanup retries."""
from __future__ import annotations
from automation_paths import configured_text
import json
import subprocess

command = [
    'python3', configured_text('${ANALYST_DASHBOARD_ROOT}/scripts/cleanup_historical_deployments.py'),
    '--safe-deployment-url', configured_text('${ANALYST_DASHBOARD_URL}'),
    '--safe-deployment-uid', configured_text('${ANALYST_SAFE_DEPLOYMENT_ID}'),
]
result = subprocess.run(command, cwd=configured_text('${ANALYST_DASHBOARD_ROOT}'), capture_output=True, text=True, timeout=600)
line = (result.stdout or result.stderr).strip().splitlines()[-1]
try:
    summary = json.loads(line)
except Exception:
    print('MarketWiki historical cleanup verification FAIL: inventory command did not return JSON')
    raise SystemExit(1)
remaining = int(summary.get('unsafeCount', -1))
if result.returncode == 0 and remaining == 0:
    print('MarketWiki historical privacy cleanup PASS: all inventoried deployments containing strategy-data.json were removed; production privacy route remains closed.')
    raise SystemExit(0)
print('MarketWiki historical privacy cleanup INCOMPLETE: ' + json.dumps(summary, sort_keys=True))
raise SystemExit(1)
