#!/usr/bin/env python3
"""Build and deploy a deliberate Market Dashboard application release.

Routine Wiki data changes must use the independent Blob publisher instead. This
helper is only for UI, schema, routing, or other application-code changes. It
builds the Vite app, deploys to Vercel, and verifies the decoupled data plane.

Use --quiet for cron: no stdout on success, non-zero/error output on failure.
"""
from __future__ import annotations
from automation_paths import configured_text

import json
import hashlib
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = Path(configured_text('${ANALYST_DASHBOARD_ROOT}'))
ENV_PATH = Path(configured_text('${ANALYST_HERMES_HOME}/.env'))
PROD_URL = configured_text('${ANALYST_DASHBOARD_URL}')
MANIFEST_URL = f'{PROD_URL}/market-data/manifest.json'
PRIVATE_URL = f'{PROD_URL}/strategy-data.json'


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def redact(text: str) -> str:
    token = os.environ.get('VERCEL_TOKEN', '')
    if token:
        text = text.replace(token, '[REDACTED_VERCEL_TOKEN]')
    return text


def run(cmd: list[str], timeout: int = 600) -> str:
    proc = subprocess.run(
        cmd,
        cwd=PROJECT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    output = redact(proc.stdout)
    if proc.returncode != 0:
        tail = '\n'.join(output.splitlines()[-80:])
        safe_cmd = ['[REDACTED_VERCEL_TOKEN]' if x == os.environ.get('VERCEL_TOKEN') else x for x in cmd]
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(safe_cmd)}\n{tail}")
    return output


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f'{url} returned HTTP {resp.status}')
        return json.loads(resp.read().decode('utf-8'))


def fetch_bytes(url: str) -> bytes:
    """Fetch decoded representation bytes; Vercel may force Brotli on rewrites."""
    proc = subprocess.run(
        ['curl', '--compressed', '--silent', '--show-error', '--fail', url],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'{url} fetch failed: {proc.stderr.decode(errors="replace").strip()}')
    return proc.stdout


def status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    quiet = '--quiet' in sys.argv
    load_env_file(ENV_PATH)
    if not PROJECT.exists():
        raise RuntimeError(f'Missing project directory: {PROJECT}')
    token = os.environ.get('VERCEL_TOKEN')
    if not token:
        raise RuntimeError(configured_text('VERCEL_TOKEN is not set in environment or ${ANALYST_HERMES_HOME}/.env'))

    run(['npm', 'run', 'build'])
    deploy_out = run(['npx', 'vercel', '--prod', '--yes', '--token', token], timeout=600)
    manifest = fetch_json(MANIFEST_URL)
    snapshot_path = manifest.get('snapshotPath', '')
    if not snapshot_path.startswith('marketwiki/'):
        raise RuntimeError('production manifest snapshotPath is outside the MarketWiki prefix')
    snapshot = fetch_bytes(f"{PROD_URL}/market-data/{snapshot_path.removeprefix('marketwiki/')}")
    actual_hash = hashlib.sha256(snapshot).hexdigest()
    if actual_hash != manifest.get('objectSha256'):
        raise RuntimeError('same-origin production snapshot hash does not match manifest')
    if len(snapshot) != manifest.get('byteLength'):
        raise RuntimeError('same-origin production snapshot length does not match manifest')
    private_status = status(PRIVATE_URL)
    if private_status not in {404, 410}:
        raise RuntimeError(f'legacy private route returned HTTP {private_status}')

    deploy_line = next((line.strip() for line in deploy_out.splitlines() if 'https://' in line and 'vercel.app' in line), PROD_URL)

    if not quiet:
        print(
            '✅ Market dashboard application deployed\n'
            f'URL: {PROD_URL}\n'
            f'Deploy: {deploy_line}\n'
            f"Snapshot: {manifest.get('snapshotId')} | bytes: {len(snapshot)} | "
            f'private route: HTTP {private_status}'
        )
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'❌ Market dashboard refresh failed: {redact(str(exc))}', file=sys.stderr)
        raise
