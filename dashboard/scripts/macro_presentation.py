"""Source-neutral display only; canonical transcript records are never modified."""
import re

MACRO_JOB_IDS = {'synthetic-job-0d', 'synthetic-job-01'}
CONFIDENCE_HELP = 'Evidence confidence describes support and relevance for each assessment, not bullishness or a probability of gains. No combined confidence score is assigned.'


def neutral_macro_text(text):
    # Video inventories contain sensational titles and host names. Keep their
    # explicitly authored stance/confidence clauses instead; do not infer a vote.
    out = []
    for line in text.splitlines():
        stance = re.search(r'\bstance:\s*(.+)', line, re.I)
        if not stance and re.search(r'(?:Meet\s*Kevin|Fast\s*Money|CNBC)\s+[—–-]\s+', line, re.I):
            continue  # An incomplete video-title fragment is not an assessment.
        if stance and re.search(r'youtu(?:be\.com|\.be)', line, re.I):
            line = 'Stance: ' + stance[1]
        line = re.sub(r'\[([^\]]+)\]\(https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[^)]+\)', '', line, flags=re.I)
        line = re.sub(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+', '', line, flags=re.I)
        line = re.sub(r'\b(?:Meet\s*Kevin|Kevin)(?:[’\']s)?', 'Commentary', line, flags=re.I)
        line = re.sub(r'\b(?:CNBC\s+Fast\s+Money|Fast\s+Money|CNBC)(?:[’\']s)?', 'news commentary', line, flags=re.I)
        line = re.sub(r'\bconfidence:', 'evidence confidence:', line, flags=re.I) if not re.search(r'evidence confidence:', line, re.I) else line
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
