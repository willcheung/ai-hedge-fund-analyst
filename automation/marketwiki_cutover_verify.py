#!/usr/bin/env python3
"""One-shot post-cutover verification after a weekday MarketWiki producer cycle."""
from __future__ import annotations
from automation_paths import configured_text
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

DASHBOARD = configured_text('${ANALYST_DASHBOARD_URL}')
STATE = Path(configured_text('${ANALYST_HERMES_HOME}/state/marketwiki-cutover-baseline.json'))
sys.path.insert(0, configured_text('${ANALYST_DASHBOARD_ROOT}/scripts'))
import cleanup_historical_deployments as cleanup  # noqa: E402


def curl_json(url: str) -> tuple[dict, bytes]:
    result = subprocess.run(['curl', '-fsS', '--compressed', url], capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f'GET failed for {url}')
    return json.loads(result.stdout), result.stdout


def status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            response.read(1)
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def current() -> dict:
    manifest, _ = curl_json(DASHBOARD + '/market-data/manifest.json')
    path = str(manifest['snapshotPath']).removeprefix('marketwiki/')
    snapshot = subprocess.run(
        ['curl', '-fsS', '--compressed', DASHBOARD + '/market-data/' + path],
        capture_output=True, timeout=90, check=True,
    ).stdout
    token = cleanup.env_value('VERCEL_TOKEN')
    project = json.loads(cleanup.PROJECT.read_text())
    latest = cleanup.deployments(token, project)[0]
    return {
        'deploymentUid': latest['uid'],
        'sourceMaxAsOf': manifest['sourceMaxAsOf'],
        'snapshotId': manifest['snapshotId'],
        'hashMatch': hashlib.sha256(snapshot).hexdigest() == manifest['objectSha256'],
        'strategyStatus': status(DASHBOARD + '/strategy-data.json'),
        'rootStatus': status(DASHBOARD + '/'),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--write-baseline', action='store_true')
    args = parser.parse_args()
    now = current()
    if args.write_baseline:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(now, indent=2, sort_keys=True) + '\n')
        print(json.dumps({'baselineWritten': str(STATE), **now}, sort_keys=True))
        return 0
    baseline = json.loads(STATE.read_text())
    checks = {
        'dataAdvanced': now['sourceMaxAsOf'] > baseline['sourceMaxAsOf'],
        'deploymentUnchanged': now['deploymentUid'] == baseline['deploymentUid'],
        'snapshotVerified': now['hashMatch'],
        'privacyRouteClosed': now['strategyStatus'] in {404, 410},
        'dashboardHealthy': now['rootStatus'] == 200,
    }
    passed = all(checks.values())
    print('MarketWiki cutover ' + ('PASS' if passed else 'FAIL') + ': ' + json.dumps({
        'checks': checks,
        'beforeSnapshotId': baseline['snapshotId'],
        'afterSnapshotId': now['snapshotId'],
        'beforeSourceMaxAsOf': baseline['sourceMaxAsOf'],
        'afterSourceMaxAsOf': now['sourceMaxAsOf'],
        'deploymentUid': now['deploymentUid'],
    }, sort_keys=True))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
