#!/usr/bin/env python3
"""Cron wrapper for CNBC Fast Money transcript pipeline.

Runs only when a new Fast Money episode exists. Prints nothing when there is
nothing new so no_agent cron jobs stay silent instead of spamming cached output.
"""
from automation_paths import configured_text
import importlib.util
import os
import pathlib
import subprocess
import sys
import time

SCRIPT = pathlib.Path(configured_text('${ANALYST_HERMES_HOME}/scripts/fast_money_transcript.py'))
TRANSCRIPTS = pathlib.Path(configured_text('${ANALYST_WIKI_ROOT}/raw/transcripts'))
AUDIO_DIR = pathlib.Path(configured_text('${ANALYST_HERMES_HOME}/podcast_data/audio'))

# Failed runs intentionally retain their download for a retry, but once an
# episode is stale it is no longer useful to the latest-episode cron path.
# Bound those retry artifacts so a string of degraded runs cannot fill disk.
cutoff = time.time() - 3 * 86400
if AUDIO_DIR.exists():
    for audio_file in AUDIO_DIR.glob('fast_money_*.mp3'):
        try:
            if audio_file.stat().st_mtime < cutoff:
                audio_file.unlink()
        except FileNotFoundError:
            pass

spec = importlib.util.spec_from_file_location('fast_money_transcript', SCRIPT)
fm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fm)

episode = fm.get_latest_episode()
if episode is None:
    sys.exit(0)

date_str = episode.findtext('pubDate', '')
try:
    pub_date = fm.parsedate_to_datetime(date_str).replace(tzinfo=None)
    episode_date = pub_date.strftime('%Y-%m-%d')
except Exception:
    # If date parsing breaks, fail loudly instead of writing a bogus today-dated transcript.
    print(f'ERROR: Could not parse Fast Money pubDate: {date_str!r}', file=sys.stderr)
    sys.exit(1)

transcript_path = TRANSCRIPTS / f'fast_money_{episode_date}.txt'
insights_path = TRANSCRIPTS / f'fast_money_{episode_date}_insights.json'
wiki_note_path = pathlib.Path(configured_text('${ANALYST_WIKI_ROOT}/daily/fastmoney')) / f'fastmoney_{episode_date}.md'

regime_path = pathlib.Path(configured_text('${ANALYST_WIKI_ROOT}/themes/market_regime_risk_on_off.md'))
regime_has_trace = False
if regime_path.exists():
    try:
        regime_has_trace = f'CNBC Fast Money {episode_date}' in regime_path.read_text()
    except OSError:
        regime_has_trace = False

if transcript_path.exists() and insights_path.exists() and wiki_note_path.exists() and regime_has_trace:
    # Silent duplicate.
    sys.exit(0)

cmd = [sys.executable, '-u', str(SCRIPT), '--date', episode_date]
env = os.environ.copy()
env['PYTHONUNBUFFERED'] = '1'

# Test-only hook for validating degradation handling without running the heavy
# local Whisper transcription path.
simulated_returncode = os.environ.get('FAST_MONEY_SIMULATE_TRANSCRIBE_FAIL')
if simulated_returncode:
    proc = subprocess.CompletedProcess(cmd, int(simulated_returncode), stdout='', stderr='simulated transcription failure\n')
else:
    try:
        # One-vCPU hosts can take 20–45 minutes to transcribe a full CNBC
        # episode even with the tiny/int8 model. Keep a bounded one-hour cap;
        # the job runs off-hours and remains lower-cost than a hosted STT call.
        timeout = int(os.environ.get('FAST_MONEY_TRANSCRIBE_TIMEOUT', '3600'))
        proc = subprocess.run(cmd, text=True, capture_output=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc = subprocess.CompletedProcess(
            cmd,
            124,
            stdout=exc.stdout or '',
            stderr=(exc.stderr or '') + f'\nFast Money transcription timed out after {timeout}s\n',
        )
if proc.returncode != 0:
    # 247/137/-9 are commonly observed when the local transcriber is killed in a
    # low-memory cron environment; 124 is our explicit timeout. Treat Fast Money
    # as optional/degraded rather than failing the market pipeline every weekday.
    if proc.returncode in {124, 137, 247, -9}:
        note_dir = pathlib.Path(configured_text('${ANALYST_WIKI_ROOT}/daily/fastmoney'))
        note_dir.mkdir(parents=True, exist_ok=True)
        note = note_dir / f'fastmoney_{episode_date}.md'
        note.write_text(
            '\n'.join([
                '---',
                f'title: CNBC Fast Money {episode_date} — degraded transcript',
                f'created: {episode_date}',
                'type: daily',
                'tags: [daily, transcript, macro]',
                'confidence: low',
                '---',
                '',
                f'# CNBC Fast Money — {episode_date} degraded transcript',
                '',
                'The Fast Money ingestion found a new episode but local transcription was killed or timed out in the cron environment before completion.',
                '',
                'Portfolio translation: treat this source as degraded/no-signal for today. Do not change macro posture, ticker priority, or add-size decisions from Fast Money.',
                '',
                'Next action: rely on source packs, X scans, earnings/filings, and TraderMonty macro artifacts until the transcription backend is replaced or repaired.',
                '',
                'Related: [[themes/market_regime_risk_on_off.md|Market Regime / Risk-On Risk-Off Map]], [[portfolio/macro_risk_dashboard.md|Macro Risk Dashboard]].',
                '',
            ]),
            encoding='utf-8',
        )
        log_path = pathlib.Path(configured_text('${ANALYST_WIKI_ROOT}/log.md'))
        try:
            existing = log_path.read_text(encoding='utf-8')
            entry = f"## [{episode_date}] fastmoney | Degraded transcript source\nFast Money episode was detected, but local transcription was killed before completion. Wrote [[daily/fastmoney/fastmoney_{episode_date}|degraded trace]]. No macro/ticker posture change; source remains optional until transcription backend is repaired.\n\n"
            if f'fastmoney_{episode_date}|degraded trace' not in existing:
                log_path.write_text(existing.replace('# Market Wiki Log\n\n', '# Market Wiki Log\n\n' + entry, 1), encoding='utf-8')
        except OSError:
            pass
        sys.exit(0)
    if proc.stdout:
        print(proc.stdout, end='')
    if proc.stderr:
        print(proc.stderr, end='', file=sys.stderr)
    sys.exit(proc.returncode)

for check_cmd in ([sys.executable, '_tools/build_index.py'], [sys.executable, '_tools/wiki_lint.py']):
    check = subprocess.run(check_cmd, cwd=configured_text('${ANALYST_WIKI_ROOT}'), text=True, capture_output=True, env=env, timeout=300)
    if check.returncode != 0:
        if proc.stdout:
            print(proc.stdout, end='')
        if proc.stderr:
            print(proc.stderr, end='', file=sys.stderr)
        if check.stdout:
            print(check.stdout, end='')
        if check.stderr:
            print(check.stderr, end='', file=sys.stderr)
        sys.exit(check.returncode)

# Success is intentionally silent: the cron job is ingestion-only. It writes raw
# transcript/insights plus a structured wiki signal note, but sends no Slack
# transcript summary. Non-zero exits above still surface stderr/stdout for alerts.
