#!/usr/bin/env python3
"""Failure-only end-to-end MarketWiki freshness and integrity watchdog."""
from __future__ import annotations
from automation_paths import configured_text

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

DASHBOARD = configured_text('${ANALYST_DASHBOARD_URL}')
BLOB_ORIGIN = configured_text('${ANALYST_BLOB_ORIGIN}/')
PUBLISHER_STATE = Path(configured_text('${ANALYST_HERMES_HOME}/state/marketwiki_publish_pipeline_state.json'))
MAX_SNAPSHOT_BYTES = 6_000_000
MAX_PUBLISHER_HEARTBEAT_SECONDS = 15 * 60


def fetch(url: str, *, limit: int = MAX_SNAPSHOT_BYTES) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'MarketWikiFreshnessWatchdog/1'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get_content_type()
            declared = response.headers.get('Content-Length')
            if declared and int(declared) > limit:
                raise RuntimeError(f'oversized response: {declared} bytes')
            body = response.read(limit + 1)
            if len(body) > limit:
                raise RuntimeError(f'oversized response: >{limit} bytes')
            return response.status, content_type, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get_content_type(), exc.read(2048)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def verify() -> None:
    status, content_type, raw_manifest = fetch(
        f'{DASHBOARD}/market-data/manifest.json?watchdog={time.time_ns()}', limit=200_000
    )
    if status != 200 or content_type != 'application/json':
        raise RuntimeError(f'manifest unhealthy: status={status} content_type={content_type}')
    manifest = json.loads(raw_manifest)
    snapshot_id = str(manifest.get('snapshotId') or '')
    object_hash = str(manifest.get('objectSha256') or '')
    snapshot_url = str(manifest.get('snapshotUrl') or '')
    if snapshot_id != f'sha256:{object_hash}' or len(object_hash) != 64:
        raise RuntimeError('manifest snapshot/hash contract mismatch')
    if not snapshot_url.startswith(BLOB_ORIGIN):
        raise RuntimeError('snapshot URL is outside the approved Blob origin')

    snapshot_status, snapshot_type, raw_snapshot = fetch(snapshot_url)
    if snapshot_status != 200 or snapshot_type != 'application/json':
        raise RuntimeError(f'snapshot unhealthy: status={snapshot_status} content_type={snapshot_type}')
    if hashlib.sha256(raw_snapshot).hexdigest() != object_hash:
        raise RuntimeError('snapshot SHA-256 mismatch')
    snapshot = json.loads(raw_snapshot)
    health = snapshot.get('sourceHealth') or {}
    if health.get('status') != 'pass':
        raise RuntimeError(f"source health is {health.get('status')}: stale={health.get('staleSections')} missing={health.get('missingSections')}")
    critical = set(health.get('criticalSections') or [])
    stale_critical = sorted(critical.intersection(health.get('staleSections') or []))
    missing_critical = sorted(critical.intersection(health.get('missingSections') or []))
    if stale_critical or missing_critical:
        raise RuntimeError(f'critical sections unhealthy: stale={stale_critical} missing={missing_critical}')

    root_status, _, _ = fetch(DASHBOARD + '/', limit=1_000_000)
    private_status, _, _ = fetch(DASHBOARD + '/strategy-data.json', limit=10_000)
    if root_status != 200:
        raise RuntimeError(f'dashboard root status={root_status}')
    if private_status not in {404, 410}:
        raise RuntimeError(f'private strategy route unexpectedly status={private_status}')

    state = json.loads(PUBLISHER_STATE.read_text(encoding='utf-8'))
    if state.get('status') != 'pass':
        raise RuntimeError(f"publisher state={state.get('status')}")
    heartbeat = parse_utc(str(state.get('lastSuccessAt') or ''))
    age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
    if age < -300 or age > MAX_PUBLISHER_HEARTBEAT_SECONDS:
        raise RuntimeError(f'publisher heartbeat age={round(age)}s')


def main() -> int:
    try:
        verify()
        return 0
    except Exception as exc:
        print(f'MarketWiki freshness watchdog FAIL: {type(exc).__name__}: {str(exc)[:1000]}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
