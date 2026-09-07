#!/usr/bin/env python3
"""Failure-only MarketWiki generation/validation/publication tick.

A single nonblocking lock covers the whole pipeline. Alerts are deduplicated;
success is silent except for one recovery notification after an alerted failure.
"""
from __future__ import annotations
from automation_paths import configured_text
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from zoneinfo import ZoneInfo

ROOT = Path(configured_text('${ANALYST_DASHBOARD_ROOT}'))
LOCK = Path(configured_text('${ANALYST_HERMES_HOME}/state/marketwiki_publish_pipeline.lock'))
STATE = Path(configured_text('${ANALYST_HERMES_HOME}/state/marketwiki_publish_pipeline_state.json'))
WALL_TIMEOUT_SECONDS = 240
ALERT_REPEAT_SECONDS = 3600
STEPS = [
    ('refresh-shortlist', ['python3', configured_text('${ANALYST_HERMES_HOME}/scripts/refresh_current_shortlist_if_needed.py')]),
    ('build-macro-regime', ['python3', configured_text('${ANALYST_WIKI_ROOT}/_tools/build_macro_regime_snapshot.py')]),
    ('generate', ['python3', 'scripts/generate_wiki_data.py']),
    ('privacy-validate', ['python3', 'scripts/validate_public_assets.py', 'public']),
    ('publish', ['python3', 'scripts/publish_wiki_data.py', 'publish', 'public/wiki-data.json']),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def safe(text: str) -> str:
    text = re.sub(r'(?i)(token|authorization|bearer|secret|password)(\s*[:=]\s*|\s+)[^\s]+', r'\1\2[REDACTED]', text)
    return text[-1200:].strip()


def load_state() -> dict:
    try:
        value = json.loads(STATE.read_text())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_state(value: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=STATE.name + '.', dir=STATE.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, STATE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def failure(message: str, state: dict) -> int:
    now = time.time()
    signature = hashlib.sha256(message.encode()).hexdigest()
    last_alert = float(state.get('lastAlertEpoch') or 0)
    alert_due = state.get('failureSignature') != signature or now - last_alert >= ALERT_REPEAT_SECONDS
    state.update({'status': 'fail', 'failureSignature': signature, 'lastFailureAt': utc_now()})
    if alert_due:
        state['lastAlertEpoch'] = now
        state['lastAlertAt'] = utc_now()
    save_state(state)
    if alert_due:
        print(message)
        return 1
    return 0


def main() -> int:
    force = os.environ.get('MARKETWIKI_FORCE_TICK') == '1'
    if not force and datetime.now(ZoneInfo('America/Los_Angeles')).weekday() >= 5:
        return 0
    started = time.monotonic()
    if not force:
        bucket = int(time.time() // 300)
        jitter = int(hashlib.sha256(str(bucket).encode()).hexdigest()[:4], 16) % 21
        time.sleep(jitter)

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    state = load_state()
    with LOCK.open('a+') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            count = int(state.get('contentionCount') or 0) + 1
            state.update({'contentionCount': count, 'lastContentionAt': utc_now()})
            save_state(state)
            if count == 3 or count % 12 == 0:
                print(f'MarketWiki data publish FAIL [contention]: whole-pipeline lock skipped {count} consecutive ticks')
                return 1
            return 0

        state['contentionCount'] = 0
        for name, command in STEPS:
            remaining = WALL_TIMEOUT_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                return failure(f'MarketWiki data publish FAIL [{name}]: whole-pipeline timeout exceeded {WALL_TIMEOUT_SECONDS}s', state)
            try:
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=remaining)
            except Exception as exc:
                return failure(f'MarketWiki data publish FAIL [{name}]: {type(exc).__name__}: {safe(str(exc))}', state)
            if result.returncode:
                detail = safe((result.stderr or '') + '\n' + (result.stdout or ''))
                return failure(f'MarketWiki data publish FAIL [{name}] exit={result.returncode}: {detail}', state)

        recovered = state.get('status') == 'fail'
        state.update({'status': 'pass', 'lastSuccessAt': utc_now(), 'failureSignature': None})
        save_state(state)
        if recovered:
            print('MarketWiki data publisher RECOVERED: generation, privacy validation, and Blob publication all passed.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
