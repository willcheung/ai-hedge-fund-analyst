"""Source-neutral display only; canonical transcript records are never modified."""
import re

MACRO_JOB_IDS = {'synthetic-job-0d', 'synthetic-job-01'}
CONFIDENCE_HELP = 'Evidence confidence describes support and relevance for each assessment, not bullishness or a probability of gains. No combined confidence score is assigned.'
_PUBLIC_BYLINE = r'\b(?:public\s+)?(?:presenter|host|creator)(?:[’\']s)?\b'
_HTTP_URL = r'https?://[^\s)>]+'


def neutral_macro_text(text):
    # Transcript inventories contain titles, bylines, and source links. Keep their
    # explicitly authored stance/confidence clauses instead; do not infer a vote.
    out = []
    for line in text.splitlines():
        stance = re.search(r'\bstance:\s*(.+)', line, re.I)
        if not stance and re.search(_PUBLIC_BYLINE + r'.*?\s+[—–-]\s+', line, re.I):
            continue  # An attributed title fragment is not an assessment.
        if stance and (re.search(_PUBLIC_BYLINE, line, re.I) or re.search(_HTTP_URL, line, re.I)):
            line = 'Stance: ' + stance[1]
        line = re.sub(r'\[[^\]]+\]\(' + _HTTP_URL + r'\)', '', line, flags=re.I)
        line = re.sub(_HTTP_URL, '', line, flags=re.I)
        line = re.sub(_PUBLIC_BYLINE, 'Commentary', line, flags=re.I)
        line = re.sub(r'\bconfidence:', 'evidence confidence:', line, flags=re.I) if not re.search(r'evidence confidence:', line, re.I) else line
        line = re.sub(r'(\bevidence confidence:\s*(?:very\s+)?(?:low|medium|moderate|high)\b)\s+(?:after|from|based on)\s+[^—–,;.]+', r'\1', line, flags=re.I)
        out.append(line)
    return '\n'.join(out).strip()


def macro_row(row):
    if row.get('jobId') not in MACRO_JOB_IDS:
        return row
    row = dict(row)
    row['jobName'] = 'Macro Read'
    row['category'] = 'Macro Read'
    for key in ('summary', 'articleBody'):
        row[key] = neutral_macro_text(row.get(key, ''))
    row['highlights'] = [neutral_macro_text(x) for x in row.get('highlights', [])]
    return row
