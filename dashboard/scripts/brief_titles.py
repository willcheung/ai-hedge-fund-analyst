"""Bounded, source-authored brief titles; never expose scheduler job names."""
import re


def bounded_research_title(value):
    """Exact-field validator, not a generic metadata/operational allowlist."""
    from public_content import clean_narrative
    if not isinstance(value, str) or not 8 <= len(value) <= 170 or '\n' in value or len(value.split()) < 2:
        return ''
    if clean_narrative(value) != value:
        return ''
    if re.search(r'(?i)^(?:weekly |daily |earnings:)|\b(?:cron|job|prompt|pipeline|scheduler|skill|account|portfolio monitor)\b|https?://|[\\_]|\[|\]', value):
        return ''
    if value.lower() in {'market setup', 'bottom line', 'regime map', 'research', 'response', 'summary'}:
        return ''
    return value


def source_brief_title(response, canonical_titles):
    """Only the response's leading H1/H2 is a title, never a later section.

    Canonical company names may expand an explicitly titled ticker; numbers,
    job names, prompts and incidental body mentions never identify a company.
    Multi-company headings remain authored, without a guessed primary company.
    """
    first = response.strip().splitlines()[0] if response.strip() else ''
    heading = re.fullmatch(r'#{1,2}\s+(.+?)\s*#*', first)
    if not heading:
        return ''
    title = bounded_research_title(re.sub(r'\*\*|`', '', heading[1]).strip())
    if not title:
        return ''
    match = re.match(r'^\$?([A-Z][A-Z0-9.-]{0,19})\s+(?:[—–-]\s+|(?=Q[1-4]\s+FY\d{4}\b))(.+)$', title)
    if not match or match[1] not in canonical_titles:
        return title
    symbol, subtitle = match.groups()
    others = {s for s in canonical_titles if s != symbol and re.search(r'(?<![\w])\$?' + re.escape(s) + r'(?![\w])', title)}
    if others:
        return title
    canonical = canonical_titles[symbol]
    company = re.fullmatch(re.escape(symbol) + r'\s+[—–-]\s+(.+)', canonical)
    if not company:
        return title
    # Keep both source identities and the source-authored finding; do not truncate.
    enriched = f'${symbol} — {company[1]}'
    if subtitle != company[1]:
        enriched += ': ' + subtitle
    return bounded_research_title(enriched) or title


def explicit_title_tickers(title):
    """Only explicit dollar-prefixed symbols; no broad uppercase-word mining."""
    if not bounded_research_title(title):
        return []
    return sorted(set(re.findall(r'(?<!\w)\$([A-Z][A-Z0-9.-]{0,19})(?!\w)', title)))
