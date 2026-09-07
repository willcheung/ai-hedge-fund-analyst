#!/usr/bin/env python3
"""Retry a bounded batch of rate-limited MarketWiki historical deployment deletions."""
from __future__ import annotations
from automation_paths import configured_text
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.error
import urllib.request

DASHBOARD = configured_text('${ANALYST_DASHBOARD_URL}')
SAFE_UID = configured_text('${ANALYST_SAFE_DEPLOYMENT_ID}')
INVENTORY = Path(configured_text('${ANALYST_HERMES_HOME}/state/market-dashboard-privacy-deployment-inventory.json'))
sys.path.insert(0, configured_text('${ANALYST_DASHBOARD_ROOT}/scripts'))
import cleanup_historical_deployments as cleanup  # noqa: E402


def status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            response.read(1)
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    data = json.loads(INVENTORY.read_text())
    if status(DASHBOARD + '/') != 200 or status(DASHBOARD + '/strategy-data.json') not in {404, 410}:
        print('MarketWiki historical cleanup FAIL: safe production checks no longer pass')
        return 1
    token = cleanup.env_value('VERCEL_TOKEN')
    project = json.loads(cleanup.PROJECT.read_text())
    safe_files = cleanup.deployment_file_paths(token, project, SAFE_UID)
    if any(path.endswith('/strategy-data.json') or path == 'strategy-data.json' for path in safe_files):
        print('MarketWiki historical cleanup FAIL: safe deployment inventory contains denied asset')
        return 1

    deleted = set(data.get('deleted', []))
    pending = [row for row in data.get('unsafe', []) if row.get('uid') and row['uid'] not in deleted]
    batch = pending[:180]
    errors = []
    for row in batch:
        uid = row['uid']
        endpoint = f'https://api.vercel.com/v13/deployments/{uid}?' + urllib.parse.urlencode({'teamId': project['orgId']})
        code, payload = cleanup.api_json(endpoint, token, method='DELETE')
        if code in {200, 204, 404}:
            deleted.add(uid)
        else:
            errors.append({'uid': uid, 'status': code, 'response': payload})
            if code == 429:
                break

    data['deleted'] = sorted(deleted)
    data['errors'] = errors
    data['remainingCount'] = sum(1 for row in data.get('unsafe', []) if row.get('uid') not in deleted)
    INVENTORY.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    if errors:
        print(json.dumps({'status': 'retry_needed', 'deletedTotal': len(deleted), 'remaining': data['remainingCount'], 'errorStatus': errors[0]['status']}, sort_keys=True))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
