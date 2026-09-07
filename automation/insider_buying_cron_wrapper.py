#!/usr/bin/env python3
"""Silent cron wrapper for SEC insider buying scanner.

Runs deterministic SEC Form 4 scan and writes raw artifacts every run.
Stdout stays empty when there are no material purchases so no_agent cron stays quiet.
Non-empty stdout is reserved for material insider-buying signals.
"""
from __future__ import annotations
from automation_paths import configured_text

import contextlib
import importlib.util
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(configured_text('${ANALYST_HERMES_HOME}/scripts/insider_buying_scanner.py'))
WIKI = Path(configured_text('${ANALYST_WIKI_ROOT}'))
RAW_SIGNALS = WIKI / 'raw' / 'signals'
SOURCE_PACKS = WIKI / 'raw' / 'briefings' / 'source_packs'
BRIEFINGS = WIKI / 'raw' / 'briefings' / 'tradermonty'
LOG = WIKI / 'log.md'
DAYS = 7


def load_scanner():
    spec = importlib.util.spec_from_file_location('insider_buying_scanner', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def money(v: float) -> str:
    return f"${v:,.0f}"


def write_log_once(entry: str, marker: str) -> None:
    try:
        existing = LOG.read_text(encoding='utf-8') if LOG.exists() else '# Market Wiki Log\n\n'
        if marker in existing:
            return
        if existing.startswith('# Market Wiki Log\n\n'):
            LOG.write_text(existing.replace('# Market Wiki Log\n\n', '# Market Wiki Log\n\n' + entry, 1), encoding='utf-8')
        else:
            LOG.write_text(entry + existing, encoding='utf-8')
    except OSError as exc:
        print(f'WARNING: could not update log.md: {exc}', file=sys.stderr)


def main() -> int:
    now = datetime.now(timezone.utc)
    stamp = now.strftime('%Y-%m-%d_%H%M')
    date = now.strftime('%Y-%m-%d')
    RAW_SIGNALS.mkdir(parents=True, exist_ok=True)
    SOURCE_PACKS.mkdir(parents=True, exist_ok=True)

    scanner = load_scanner()

    progress = io.StringIO()
    try:
        # yfinance and the underlying scanner can be noisy even on success. Capture
        # stdout/stderr so no_agent cron emits only material signals or real errors.
        with contextlib.redirect_stdout(progress), contextlib.redirect_stderr(progress):
            tickers = scanner.get_sub_2b_tickers()
            results = scanner.scan_all_tickers(tickers, DAYS)
    except Exception as exc:
        print(f'ERROR: insider scanner failed: {exc}', file=sys.stderr)
        return 1

    artifact = {
        'generated_at_utc': now.isoformat(),
        'days_back': DAYS,
        'tickers_scanned': tickers,
        'result_count': len(results),
        'results': results,
        'scanner_progress_tail': progress.getvalue().splitlines()[-80:],
    }
    raw_path = RAW_SIGNALS / f'insider_buying_scan_{stamp}.json'
    raw_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding='utf-8')

    source_pack_path = SOURCE_PACKS / f'insider_buying_source_pack_{stamp}.json'
    source_pack_path.write_text(json.dumps({
        'generated_at_utc': now.isoformat(),
        'source': 'SEC EDGAR Form 4 submissions API via insider_buying_scanner.py',
        'raw_artifact': str(raw_path.relative_to(WIKI)),
        'days_back': DAYS,
        'tickers_scanned_count': len(tickers),
        'result_count': len(results),
    }, indent=2, sort_keys=True), encoding='utf-8')

    if not results:
        # Silent success; raw trace exists for audit/dashboard if needed.
        return 0

    results = sorted(results, key=lambda r: r.get('total_value') or 0, reverse=True)
    brief_dir = BRIEFINGS / f'{date}_insider_buying'
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief_path = brief_dir / f'insider_buying_summary_{date}.md'
    lines = [
        '---',
        f'title: SEC Insider Buying Scanner — {date}',
        f'created: {date}',
        'type: signals',
        'tags: [insiders, sec, form-4, market]',
        f'sources: [{raw_path.relative_to(WIKI)}, {source_pack_path.relative_to(WIKI)}]',
        '---',
        '',
        f'# SEC Insider Buying Scanner — {date}',
        '',
        f'- Scanned **{len(tickers)}** sub-$2B wiki tickers for Form 4 open-market purchases in the last **{DAYS}** days.',
        f'- Material purchases found: **{len(results)}**.',
        '',
        '| Ticker | Insider / role | Date | Shares | Price | Value | Filing |',
        '|---|---|---:|---:|---:|---:|---|',
    ]
    for r in results:
        ticker = r.get('ticker', '')
        role = r.get('title') or 'Insider'
        filing = r.get('url') or ''
        lines.append(
            f"| [[tickers/{ticker}|${ticker}]] | {r.get('reporter','Unknown')} / {role} | {r.get('date','?')} | {r.get('shares',0):,.0f} | ${r.get('price',0):,.2f} | {money(r.get('total_value') or 0)} | [SEC]({filing}) |"
        )
    lines += [
        '',
        '## Use',
        '- Insider buying is a lead, not proof. Promote only when it overlaps with fundamentals, valuation reset, catalyst path, and price/action zones.',
        '',
    ]
    brief_path.write_text('\n'.join(lines), encoding='utf-8')

    entry = (
        f"## [{date}] insider_buying | Material Form 4 purchases detected\n"
        f"- Found {len(results)} material insider-buying signal(s). Summary: `{brief_path.relative_to(WIKI)}`. Raw: `{raw_path.relative_to(WIKI)}`.\n\n"
    )
    write_log_once(entry, str(raw_path.relative_to(WIKI)))

    print(f"SEC insider buying: {len(results)} material Form 4 purchase(s) detected")
    for r in results[:10]:
        print(f"- ${r.get('ticker')}: {r.get('reporter')} ({r.get('title') or 'Insider'}) bought {r.get('shares',0):,.0f} shares @ ${r.get('price',0):.2f} = {money(r.get('total_value') or 0)} on {r.get('date')}")
    print(f"Summary: {brief_path}")
    print(f"Raw: {raw_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
