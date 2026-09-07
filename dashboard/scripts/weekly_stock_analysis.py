"""Presentation of source-authored weekly selection; no financial inference."""
import re

WEEKLY_JOB_IDS = {'synthetic-job-08', 'synthetic-job-0c'}
# Empty by default. Callers may supply reviewed historical lineage explicitly.
HISTORICAL_REPORTS = {}


def is_weekly_analysis(job_id, job_name=''):
    return job_id in WEEKLY_JOB_IDS or job_name in {'Weekly Stock Analysis', 'Weekly Hybrid Stock Deep Dive'}


def selection_section(markdown):
    match = re.search(r'^##\s+(?:Why selected this week|Candidate Selection)\s*\n(.*?)(?=^##?\s|\Z)', markdown, re.M | re.S | re.I)
    return match[1].strip() if match else ''


def weekly_selection(job_id, run_id, response, wiki):
    """Prefer this run's explicit section; bounded historical report is fallback."""
    from public_content import clean_narrative
    selected = selection_section(response)
    if not selected:
        lineage = HISTORICAL_REPORTS.get((job_id, run_id))
        if lineage:
            symbol, relative = lineage
            # Match only the leading authored title, never incidental body mentions.
            if re.match(r'^#{1,2}\s+\$?' + re.escape(symbol) + r'\s+[—–-]\s', response.strip()):
                path = wiki / relative
                if path.is_file():
                    source = path.read_text()
                    if re.search(r'(?im)^privacy[_ -]?class:\s*(?!public(?:_ok)?\s*$)\S+', source):
                        return ''
                    if re.search(r'^#\s+' + re.escape(symbol) + r'\s+[—–-]', source, re.M):
                        selected = selection_section(source)
    # Source selection-policy bookkeeping is not the investment rationale.
    selected = re.sub(r'Selection ignores all embedded legacy account commentary\.?', '', selected)
    return clean_narrative(selected)


def retain_verified_weekly_history(rows, previous_rows, wiki):
    """Keep a previously published historical run after its cron was retired.

    This is a retained-record adapter, not a reconstructed cron response. Exact
    published identity, original timestamp, and independently matching canonical
    report title are all required. Never invent a run or refresh its evidence.
    """
    from copy import deepcopy
    from datetime import datetime
    result = list(rows)
    seen = {row.get('id') for row in rows}
    for previous in previous_rows:
        if not isinstance(previous, dict):
            continue
        job_id = previous.get('jobId')
        for (historical_job, run_id), (symbol, _) in HISTORICAL_REPORTS.items():
            identity = historical_job + '-' + run_id
            if job_id != historical_job or previous.get('id') != identity or identity in seen:
                continue
            expected_time = datetime.strptime(run_id, '%Y-%m-%d_%H-%M-%S').strftime('%Y-%m-%d %H:%M:%S')
            if previous.get('runTime') != expected_time:
                continue
            title = previous.get('jobName')
            if not isinstance(title, str) or not re.match(r'^\$?' + re.escape(symbol) + r'\s+[—–-]\s', title):
                continue
            rationale = weekly_selection(job_id, run_id, '# ' + title, wiki)
            if not rationale:
                continue
            row = deepcopy(previous)
            row['category'] = 'Weekly Stock Analysis'
            row['articleBody'] = '## Why selected this week\n\n' + rationale
            result.append(row)
            seen.add(identity)
    return result
