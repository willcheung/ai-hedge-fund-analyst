#!/usr/bin/env python3
"""Refresh the live shortlist only when inputs changed or its evaluation is old."""
from __future__ import annotations
from automation_paths import configured_text

from pathlib import Path
import subprocess
import time

ROOT = Path(configured_text('${ANALYST_WIKI_ROOT}'))
OUTPUT = ROOT / 'data/automation/current_asymmetric_shortlist_latest.json'
BUILDER = ROOT / '_tools/current_shortlist_builder.py'
MAX_EVALUATION_AGE_SECONDS = 6 * 3600
INPUTS = (
    BUILDER,
    ROOT / 'queries/current_asymmetric_shortlist.md',
    ROOT / 'config/action_freshness_policy.json',
    ROOT / 'tickers',
    ROOT / 'daily/briefs',
    ROOT / 'raw/signals',
    ROOT / 'raw/briefings/source_packs',
    ROOT / 'data/automation',
    ROOT / 'data/private/main_strategy_data.json',
)


def newest_input_mtime() -> float:
    newest = 0.0
    for source in INPUTS:
        candidates = [source] if source.is_file() else source.rglob('*') if source.exists() else []
        for path in candidates:
            if not path.is_file() or path == OUTPUT:
                continue
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    return newest


def refresh_needed(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    try:
        output_mtime = OUTPUT.stat().st_mtime
    except OSError:
        return True
    return now - output_mtime >= MAX_EVALUATION_AGE_SECONDS or newest_input_mtime() > output_mtime


def main() -> int:
    if not refresh_needed():
        return 0
    result = subprocess.run(
        ['python3', str(BUILDER), '--json'], cwd=ROOT, capture_output=True, text=True, timeout=90
    )
    if result.returncode:
        detail = ((result.stderr or '') + '\n' + (result.stdout or '')).strip()[-1200:]
        print('shortlist refresh failed: ' + detail)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
