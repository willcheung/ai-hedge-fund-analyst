#!/usr/bin/env python3
"""Validate the opt-in durable Market Brief contract; never rewrite source text."""
import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import re

import yaml

LANE_JOBS = {
    'conviction_list': 'synthetic-job-0a',
    'deep_dive': 'synthetic-job-05',
    'thematic_watchlist': 'synthetic-job-07',
    'friday_take': 'synthetic-job-0e',
    'material_earnings': 'synthetic-job-09',
    'macro_shift': 'synthetic-job-02',
}
SYMBOL = r'[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*'


def prose_only(text: str) -> str:
    # Preserve link labels for validation, but never alter/validate destinations.
    text = re.sub(r'\[\[([^]|]+)(?:\|([^]]+))?\]\]', lambda m: m[2] or '', text)
    text = re.sub(r'\[([^]\n]+)\]\([^\n)]*\)', r'\1', text)
    text = re.sub(r'^\s*\[[^]]+\]:\s*\S+.*$', '', text, flags=re.M)
    text = re.sub(r'https?://[^\s<>]+', '', text)
    text = re.sub(r'(?<!\w)(?:/?[\w.-]+/)+[\w./-]+', '', text)
    text = re.sub(r'\b[\w.-]+\.(?:md|json|csv|yaml|yml|txt)\b', '', text)
    return text


def timestamp(value: object) -> str:
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def validate_note(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding='utf-8')
    match = re.match(r'\A---\s*\n(.*?)\n---\s*\n(.*)\Z', text, re.S)
    if not match:
        raise ValueError(f'{path}: YAML frontmatter required')
    try:
        fm = yaml.safe_load(match[1])
    except yaml.YAMLError as exc:
        raise ValueError(f'{path}: invalid YAML: {exc}') from exc
    if not isinstance(fm, dict):
        raise ValueError(f'{path}: frontmatter must be a mapping')
    body = match[2].strip()
    errors = []
    lane = fm.get('market_brief_lane')
    if not isinstance(lane, str) or lane not in LANE_JOBS:
        errors.append('unknown market_brief_lane')
    elif str(fm.get('job_id')) != LANE_JOBS[lane]:
        errors.append('job_id does not match market_brief_lane')
    filename = re.fullmatch(r'market_brief_(.+)_(\d{4}-\d{2}-\d{2})\.md', path.name)
    if not filename or filename[1] != lane:
        errors.append('filename must be market_brief_{lane}_YYYY-MM-DD.md')
    else:
        try:
            date.fromisoformat(filename[2])
        except ValueError:
            errors.append('invalid filename date')
    for field in ('created', 'updated'):
        try:
            timestamp(fm.get(field))
        except (ValueError, TypeError):
            errors.append(f'{field} must be an ISO date or timestamp')
    if not errors and timestamp(fm['updated']) < timestamp(fm['created']):
        errors.append('updated precedes created')
    if fm.get('type') != 'daily' or not isinstance(fm.get('tags'), list) or 'daily' not in fm['tags']:
        errors.append('type: daily and tags containing daily required')
    if not isinstance(fm.get('sources'), list) or not fm['sources'] or not all(isinstance(s, str) and s.strip() for s in fm['sources']):
        errors.append('sources must be a nonempty string list')
    title = fm.get('title')
    if not isinstance(title, str) or not title.strip() or not body.startswith(f'# {title}\n'):
        errors.append('title and matching # title required')
    if not re.search(r'^## Key points\s*\n\s*[-*] .+', body, re.M):
        errors.append('## Key points with bullets required')
    if not re.search(r'^## Source trace\s*\n\s*\S+', body, re.M):
        errors.append('nonempty ## Source trace required')
    intro = body.split('##', 1)[0].split('\n', 1)
    if len(intro) < 2 or not intro[1].strip():
        errors.append('introductory paragraph required')
    tickers = fm.get('tickers')
    if not isinstance(tickers, list) or not all(isinstance(s, str) and re.fullmatch(SYMBOL, s) for s in tickers):
        errors.append('tickers must be explicit unprefixed uppercase symbol list (empty allowed)')
    else:
        prose = prose_only(f'{title}\n{body}')
        if len(set(tickers)) != len(tickers):
            errors.append('duplicate tickers')
        for symbol in tickers:
            if re.search(rf'(?<![\w$]){re.escape(symbol)}(?!\w|[.-][A-Z0-9])', prose):
                errors.append(f'bare ticker {symbol}; use ${symbol} in prose')
        for symbol in re.findall(rf'\$({SYMBOL})(?!\w)', prose):
            if symbol not in tickers:
                errors.append(f'cashtag ${symbol} missing from tickers')
        if re.search(r'\$\$[A-Z]', prose):
            errors.append('double-prefixed cashtag')
    if errors:
        raise ValueError(f'{path}: ' + '; '.join(errors))
    return fm, body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('note', type=Path)
    args = parser.parse_args()
    try:
        validate_note(args.note)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')
    print(f'PASS {args.note}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
