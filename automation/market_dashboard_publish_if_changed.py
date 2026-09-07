#!/usr/bin/env python3
"""Publish the configured market dashboard when market-wiki source data has changed.

Silent on success/no-change so Slack delivery becomes failure-only. Non-zero exits surface
through the cron job delivery target. Cron outputs are deliberately not watched: market jobs
write durable wiki traces, and watching publisher output can create a deployment-failure loop.
"""
from __future__ import annotations
from automation_paths import configured_text

import json
import os
import subprocess
import sys
from pathlib import Path
from time import time

DASHBOARD = Path(configured_text('${ANALYST_DASHBOARD_ROOT}'))
WIKI = Path(configured_text('${ANALYST_WIKI_ROOT}'))
STATE_PATH = Path(configured_text('${ANALYST_HERMES_HOME}/state/market_dashboard_publish_state.json'))

# Keep scans bounded to files that affect the dashboard payload.
WIKI_SUFFIXES = {'.md', '.json', '.csv'}



def max_mtime(root: Path, suffixes: set[str], skip_names: set[str] | None = None) -> float:
    if not root.exists():
        return 0.0
    skip_names = skip_names or set()
    latest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_names and not d.startswith('.')]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() not in suffixes:
                continue
            try:
                if path.stat().st_size == 0:
                    continue
                latest = max(latest, path.stat().st_mtime)
            except FileNotFoundError:
                continue
    return latest


def run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
    if proc.returncode != 0:
        sys.stderr.write(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n")
        sys.stderr.write(proc.stdout[-6000:])
        raise SystemExit(proc.returncode)


def main() -> int:
    if not DASHBOARD.exists():
        sys.stderr.write(f"Dashboard path missing: {DASHBOARD}\n")
        return 2

    latest_source = max_mtime(WIKI, WIKI_SUFFIXES, {'node_modules', '.git', 'raw', 'archive'})

    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
        except Exception:
            state = {}

    last_published_source = float(state.get('last_source_mtime') or 0)
    # If nothing changed since the last successful publish, stay silent.
    if latest_source <= last_published_source:
        return 0

    # Use the canonical deploy helper: it loads the Vercel token from the protected Hermes env,
    # builds, deploys, redacts credentials, and verifies the production JSON endpoint.
    run([sys.executable, configured_text('${ANALYST_HERMES_HOME}/scripts/refresh_market_dashboard.py'), '--quiet'], DASHBOARD)

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        'last_source_mtime': latest_source,
        'last_published_at': time(),
    }, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
