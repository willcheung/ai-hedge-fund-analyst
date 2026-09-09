#!/usr/bin/env python3
"""Shared public boundary. Deterministic checks are not semantic fact checking.

No research decisions are derived here. Rejected content/diagnostics stay private.
"""
from __future__ import annotations
import copy
import ipaddress
import json
import re
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, unquote, parse_qsl
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'schema/public-content-v1.schema.json').read_text())
LABELS = json.loads((ROOT / 'schema/public-labels.json').read_text())
from brief_titles import bounded_research_title, explicit_title_tickers
from public_graph_structure import sanitize_graph_identity
UNAVAILABLE = LABELS['unavailable']
PUBLIC_LABELS = {item['label']: item for item in LABELS['labels'].values()}
# Canonical shortlist membership, NOT a public action/assessment vocabulary.
MEMBERSHIP_BUCKETS = frozenset({
    'Buy / Scout Now', 'Wait for Trigger', 'Add After Proof',
    'Research Memory / Not Live Action', 'Kill / Do Not Average',
})
# Named-owner identity/implementation is private, not a generic "will" filter.
# Preserve modal verbs (including title case) and third-party full names. Withhold
# complete units: replacing the name would launder private holdings into advice.
OWNER_IDENTITY = re.compile(
    r'(?i:\browan[\s_-]*example\b)'
    r'|(?<![a-zA-Z] )\b[A-Z][a-z]+(?:[’\']s\b|-style\b|\s+\((?:portfolio(?:/watchlist)?|manual)\))'
    r'|\b[A-Z][a-z]+\s+(?:should|already owns|asked to|wants to|insists on)\b'
    r'|\b(?:for [A-Z][a-z]+ versus|diversifies [A-Z][a-z]+ away)\b'
    r'|(?im:^\s*(?:by|author\s*:)\s+[A-Z][a-z]+\s*(?:$|[·|—]))'
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
# Contextual privacy: company revenue, prices, yields and emojis are NOT private.
PRIVATE = re.compile(r'(?i)(?:\b(?:my|our|your|[a-z]+[’\']s)\s+(?:account|holdings?|positions?|portfolio|shares|cost basis|P/?L|returns?)\b|\b(?:account[_ -]?(?:number|id|scope|value)|cost basis|position siz(?:e|ing)|share count|net worth|buying power|dry powder|personal P/?L|portfolio (?:P/?L|value|weight|allocation)|realized P/?L|unrealized P/?L|RH net|RH\s*[:(]|net tracker|masked account)\b|\b(?:P/?L)\s*(?:is|:|=)|\bposition marks\b|^\s*(?:#{1,6}\s*)?Holdings\s*:?\s*$|\|\s*Holding\s*\|\s*Qty\b|\*{3,}\d{2,}|\b\d{2}\*{2,}\d{2})')
PRIVATE = re.compile(PRIVATE.pattern + r'|(?i:common[- ]equity sleeve|aggregate cost|equity positions|\baccount\s*[:=]|ledger P/L|\bP/L\b|\b(?:I|we|you) (?:own|hold|bought|sold)\b|\b(?:existing|open) positions\b|\b(?:max fresh risk|fresh risk|size cap|funding source|bogey contribution)\b|\d+(?:\.\d+)?% (?:of |in )?(?:the |our |my )?portfolio|portfolio (?:overlap|gates|event|proof|has no better)|private strategy|broker returned|broker-certified|broker quote pack)')
OPERATIONAL = re.compile(r'(?i)(?:/(?:root|home|tmp|etc|var|workspace)/|\b(?:data/(?:private|portfolio|automation)|scripts/\S+\.py|SKILL\.md|AGENTS\.md|\.hermes/|cronTimeline|runtime-manifest|tool_call|system prompt|raw prompt|files written|execution log|traceback|task complete|tokens? used|skill\(s\)|no material (?:change|signal)|empty output|\[SILENT\])\b|\b(?:run|load|invoke|execute|read|use)\b.{0,40}\b(?:skill|script|command|tool|cron|agent)\b|\b(?:send|post|deliver)\b.{0,30}\b(?:Slack|Telegram|channel)\b|\b(?:X scan|scan completed|items scanned|posts scanned|no eligible|0 candidates)\b)')
OPERATIONAL = re.compile(OPERATIONAL.pattern + r'|(?i:roster[- ]cache|\bAPI:|\bScan:|no public draft|no dashboard build|no (?:portfolio|research-tier|broker)[^.!?]*change|ticker mutation|autonomous order|daily monitor queue|order or broker state|high-quality accounts/questions|preserve existing research tiers|\b(?:scan|cache) was a usable hit|\b(?:cache|roster) (?:hit|refresh)|no new orders|no options or crypto)')
OPERATIONAL = re.compile(OPERATIONAL.pattern + r'|(?<![/:A-Za-z0-9])(?:tickers|research|daily|queries|raw|data|scripts)/[^\s)\]]+\.(?:md|json|py)\b')
OPERATIONAL = re.compile(OPERATIONAL.pattern + r'|(?i:(?:updated|regenerated|wrote)\s+(?:log|index)\.md|fullWarRoom|see full War Room|no action-state[^.!?]*change|daily-monitor-queue|instrument-risk[^.!?]*change)')
PRIVATE = re.compile(PRIVATE.pattern + r'|(?i:private notes|owner-only|internal instructions|^\s*#{1,6}\s+(?:private|internal|owner)\s*$)|(?i:max size\s*:|cap total aggression|risk-control answer|add-small only|total aggression)')
OPERATIONAL = re.compile(OPERATIONAL.pattern + r'|(?i:method boundary|portfolio-specific implementation|separate implementation review|X signal scanner)|\[\[(?:research|daily|queries|raw|data|scripts)/')
# Empty monitor receipts and local logging/lint notes are not market research.
OPERATIONAL = re.compile(OPERATIONAL.pattern + r'|(?i:\bno new usable\b[^\n.!?]{0,120}(?:\.txt\s+)?transcripts\b|\bappended log entry\b|\bpre-existing lint debt\b|\bthis run introduced no failures\b|\b(?:Minority Mindset|transcript source|transcript feed|source|feed|job) (?:remained|was) disabled\b)')
OPERATIONAL = re.compile(OPERATIONAL.pattern + r'|(?i:\bWiki learning contract\b)|(?im:^[\s⚪*\-]*Verification:\s*$)')
MALFORMED = re.compile(r'(?i)(?:\[(?:private|redacted|private-account)[^\]]*\]|<\/?[a-z][^>]*>|```|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b)')
AMBIGUOUS = re.compile(r'(?i)(?:WAIT[-_]FOR[-_]PROOF|WATCH\s*/\s*WAIT|HOLD TINY|MIXED / HOLD|Tier 3|best actionable idea\s*/\s*avoid|starter watch|add-after-proof|\bscout\b|\bproof gate\b|\bno[- ]chase\b|\bnot chase\b|\b(?:buy|add|watch|avoid|hold|sell)\s*/\s*(?:buy|add|watch|avoid|hold|sell)\b|(?-i:\b(?:OWNABLE|EMERGING)\b)|\bTier [12]\b)')
ACTION_TEXT = re.compile(r'(?i)(?:\b(?:buy|purchase|sell|trim|add)\s+(?:now|only|after|shares|the stock|this stock|a position|\$[A-Z])|\b(?:consider|avoid|delay|wait before|do not|not)\b.{0,30}\b(?:buying|a purchase|new purchases|buy|selling)\b|\b(?:watch for now|new purchases)\b|^\s*(?:buy|sell|hold|watch)\s*[.!:—-])')
# Operational investment workflow/sizing, not corporate capital transactions.
OPERATIONAL = re.compile(OPERATIONAL.pattern + r'|(?i:\bresearch[- ]tiers?\b|\b(?:tier|monitoring|monitor[- ]queue) promotions?\b|\braise attention,? not size\b|\bWiki updates\s*:|\bcompleted OCR\b|\b(?:saved|wrote) numeric (?:CSV|JSON)\b|\bdated in-window items retained\b|\baction bucket\b|\bcoverage tier\b)')
PRIVATE = re.compile(PRIVATE.pattern + r'|(?i:\b\d+(?:\.\d+)?%\s+fresh capital\b|\bposition\s*:\s*(?:common|stock|equity|option)\b|\bcommon holding\b|\bstored AI universe\b)')
PRIVATE = re.compile(PRIVATE.pattern + '|' + OWNER_IDENTITY.pattern)
AMBIGUOUS = re.compile(AMBIGUOUS.pattern + r'|(?i:\bproof[- ]add\b)')
# Bounded cross-sentence references: preserve the local antecedent together or
# withhold the dependent passage. This is not general coreference resolution.
DEPENDENT_REFERENCE = re.compile(r'(?i)\b(?:one of (?:those|these) (?:facts|conditions)|(?:those|these|above|aforementioned) (?:facts|conditions|prerequisites))\b')
CONDITION = re.compile(r'(?i)\b(?:only if|provided that|unless|until|after (?:confirmation|evidence)|requires? evidence)\b')
NEGATION = re.compile(r'(?i)\b(?:not|never|avoid|no)\b')

class PublicationError(ValueError):
    pass

def has_private_classification(value):
    if isinstance(value,dict):
        if any(k in value and value[k] not in (None,'','public','public_ok') for k in ('privacy_class','privacyClass')): return True
        return any(has_private_classification(v) for v in value.values())
    if isinstance(value,(list,tuple)): return any(has_private_classification(v) for v in value)
    return False

def diagnostic(items, record, code):
    # Deliberately no raw prose, paths, values or unknown enum echoed.
    items.append({'recordId': record if isinstance(record,str) and re.fullmatch(r'[A-Za-z0-9:._-]{1,160}',record) else 'unidentified', 'code': code})

def safe_url(value):
    if not isinstance(value,str) or re.search(r'[\s\\\x00-\x1f<>"`“”]', value): return False
    try:
        p=urlsplit(value)
        host=p.hostname or ''
        if p.scheme not in {'https','http'} or not host or p.username or p.password: return False
        if host in {'localhost','localhost.localdomain'} or host.endswith(('.local','.internal')) or '.' not in host: return False
        try:
            if not ipaddress.ip_address(host).is_global: return False
        except ValueError: pass
        if OPERATIONAL.search(unquote(p.path)): return False
        if any(re.search(r'(?i)token|api.?key|secret|password|account', k) for k,v in parse_qsl(p.query)): return False
        return True
    except ValueError: return False

def _unsafe_links(text):
    return any(not safe_url(url) for url in re.findall(r'!?\[[^\]]*\]\(([^\s)]+)', text)) or bool(re.search(r'(?i)(?:javascript|data|file|vbscript)\s*:',text))

# Keep historical failed-run and verification receipts out of market prose too.
OPERATIONAL = re.compile(OPERATIONAL.pattern + r'|(?i:the user has invoked|the full skill content is loaded below|last tool result explains the blocker|index rebuilt|rebuilt successfully|\blint (?:failures|warnings?)\b|verification: index|internally invalid position-stop language|no notification sent)')


def clean_narrative(text, *, action_allowed=False, editorial_checks=True):
    """Drop complete sentence/line units, never replace money with fragments."""
    if not isinstance(text,str): return ''
    # Source-verified operational receipt: retain the degraded-data meaning,
    # not internal tool names. This is not a global company-name filter.
    text=re.sub(r'(?i)(?:⚠️?\s*)?Skills not found and skipped:\s*macro-regime-detector,\s*market-breadth-analyzer,\s*exposure-coach\.?', '', text)
    text=text.replace('Upstream TraderMonty scripts supplied a degraded-data fallback',
                      'Market assessment is based on incomplete data')
    text=text.strip()
    # HTML comments are non-content markers, not research prose.
    text=re.sub(r'<!--.*?-->', '', text, flags=re.S)
    text=re.sub(r'<!--.*$', '', text, flags=re.S)
    # Never strand a private heading's numeric rows or executable fenced body.
    lines=[]; blocked_level=None; fenced=False
    for line in text.splitlines():
        if re.match(r'^\s*(```|~~~)',line):
            fenced=not fenced
            continue
        if fenced: continue
        heading=re.match(r'^\s*(#{1,6})\s+',line)
        level=len(heading.group(1)) if heading else (7 if re.match(r'^\s*\*\*[^*]+\*\*\s*:?\s*$',line) else None)
        if blocked_level is not None:
            if level is None or level > blocked_level: continue
            blocked_level=None
        if level is not None and (PRIVATE.search(line) or OPERATIONAL.search(line)):
            blocked_level=level
            continue
        lines.append(line)
    text='\n'.join(lines)
    # Split prose sentences without splitting decimal company figures or URLs.
    units=[]
    sentence_boundary=r'(?<=[.!?])\s+(?=[A-Z🟢🟡🔴📌⚠])'
    for block in re.split(r'(\n\s*\n)', text):
        if DEPENDENT_REFERENCE.search(block):
            sentences=re.split(sentence_boundary, block)
            # A lone dependent statement has no auditable local antecedent.
            if len(sentences)<2 or DEPENDENT_REFERENCE.search(sentences[0]):
                continue
            units.append(block)
            continue
        for line in block.splitlines():
            # Table rows are atomic: removing part strands malformed Markdown.
            units.extend([line] if line.lstrip().startswith('|') else re.split(sentence_boundary,line))
    kept=[]
    for unit in units:
        if not unit.strip():
            if kept and kept[-1] != '': kept.append('')
            continue
        if PRIVATE.search(unit) or OPERATIONAL.search(unit) or _unsafe_links(unit): continue
        if editorial_checks and (MALFORMED.search(unit) or AMBIGUOUS.search(unit)): continue
        if editorial_checks and re.search(r'(?i)\b(?:action(?: posture)?|posture|proof[- ]add|thesis kill|kill|max size|expected contribution)\s*:',unit): continue
        if editorial_checks and unit.rstrip().endswith('…'): continue
        if editorial_checks and re.search(r'\|\s*(?:RADAR|WATCH|AVOID|BULLISH|BEARISH|PASS|FAIL|WAIT)\s*\|',unit): continue
        if editorial_checks and re.search(r'(?i)\b(?:new buys allowed|new buys need|you can buy|hold off on new risk|hold/no fresh add|hold/wait)\b',unit): continue
        if editorial_checks:
            # Plain-language wording preserves attribution and negation.
            unit=unit.replace('broad beta pressing or margin-leverage heroics',
                              'taking more broad-market risk or using borrowed money')
            unit=re.sub(r'(?i)\bWar Room\b','Detailed research',unit)
            # Explicit legacy absence markers are not company names or ratings.
            unit=unit.replace('X Signal Stub', 'Research incomplete')
            unit=re.sub(r'\bMarket Cap:\s*TBD\b', 'Market capitalization unavailable', unit)
            unit=re.sub(r'\bExchange:\s*TBD\b', 'Exchange unavailable', unit)
        if not action_allowed and ACTION_TEXT.search(unit): continue
        kept.append(unit.strip())
    return '\n'.join(kept).strip() if '\n' in text else ' '.join(x for x in kept if x).strip()

def _allowlist(value, schema) -> Any:
    if isinstance(value,dict) and schema.get('type')=='object':
        return {key:_allowlist(value[key], spec) for key,spec in schema['properties'].items() if key in value}
    if isinstance(value,list) and schema.get('type')=='array': return [_allowlist(v,schema['items']) for v in value]
    return copy.deepcopy(value)

def _action_valid(action, raw, diagnostics, rid):
    if not isinstance(action,dict): return False
    allowed=_allowlist(action, SCHEMA['properties']['action'])
    if list(Draft202012Validator(SCHEMA['properties']['action']).iter_errors(allowed)): return False
    text=' '.join(str(v) for v in action.values())
    if PRIVATE.search(text) or OPERATIONAL.search(text) or MALFORMED.search(text) or AMBIGUOUS.search(text) or _unsafe_links(text): return False
    if not action.get('sourceIds'): return False
    if CONDITION.search(text) and not action.get('prerequisites'): return False
    current=action['currentView']
    if re.fullmatch(r'[A-Z][A-Z _/-]{2,}',current.strip()): return False
    if re.search(r'(?i)\b(?:buy now|purchase now)\b',current) and not NEGATION.search(current):
        if re.search(r'(?i)\b(?:avoid new purchases|do not buy|wait for more evidence)\b', ' '.join([raw.get('title',''),raw.get('summary',''),action['why'],raw.get('assessment','')])): return False
    source=raw.get('sourceAction')
    if source is not None:
        if not isinstance(source,dict): return False
        # Source publisher provides private original structured meaning. No automated rewrite.
        for field in ('currentView','why','prerequisites','horizon','context','sourceIds'):
            if source.get(field)!=action.get(field): return False
    if raw.get('assessment')=='Watch' and re.search(r'(?i)\bbuy now\b',current) and not NEGATION.search(current): return False
    return True

def normalize_publication(raw, diagnostics=None):
    diagnostics=[] if diagnostics is None else diagnostics
    if not isinstance(raw,dict): raise PublicationError('record-not-object')
    if has_private_classification(raw): raise PublicationError('explicit-private-classification')
    rid=raw.get('id')
    out=_allowlist(raw,SCHEMA)
    # Structure validated before text mutation so wrong types cannot masquerade as missing text.
    if list(VALIDATOR.iter_errors(out)): raise PublicationError('invalid-structure')
    # Macro source provenance lives in canonical notes, not the public display.
    from macro_presentation import MACRO_JOB_IDS, neutral_macro_text
    if out.get('jobId') in MACRO_JOB_IDS and out.get('type') == 'brief':
        out['title'] = 'Macro Read'
        out['summary'] = neutral_macro_text(out['summary'])
        for sec in out['sections']:
            sec['heading'] = neutral_macro_text(sec['heading'])
            sec['markdown'] = neutral_macro_text(sec['markdown'])
            sec.pop('sourceIds', None)
        out['sources'] = []
        for part in [*out.get('thesisHistory', []), *([out['action']] if 'action' in out else [])]:
            part['sourceIds'] = []
    for date_key in ('publishedDate','informationDate'):
        if date_key in out:
            try: date.fromisoformat(out[date_key])
            except ValueError: raise PublicationError('invalid-date')
    for clock in ('publishedAt', 'informationAt'):
        if out[clock] is not None and _clock(out[clock]) is None: raise PublicationError('invalid-clock')
    if out.get('quote'):
        for clock in ('asOf', 'previousAsOf'):
            if clock in out['quote'] and _clock(out['quote'][clock]) is None: raise PublicationError('invalid-quote-clock')
    for history in out.get('thesisHistory', []):
        if _clock(history['informationAt']) is None: raise PublicationError('invalid-history-clock')
    source_ids={s['id'] for s in out['sources']}
    # Syntax alone does not make identifier payloads public-suitable.
    references=[*source_ids, *[ref for item in [*out['sections'], *out.get('thesisHistory',[]), *([out['action']] if 'action' in out else [])] for ref in item.get('sourceIds',[])]]
    if any(PRIVATE.search(identifier) or OPERATIONAL.search(identifier) for identifier in (out['id'], out['jobId'])):
        raise PublicationError('unsafe-publication-identifier')
    if any(PRIVATE.search(ref) or OPERATIONAL.search(ref) for ref in references):
        raise PublicationError('unsafe-source-identifier')
    if len(source_ids)!=len(out['sources']) or any(not safe_url(s['url']) for s in out['sources']): raise PublicationError('invalid-source')
    for s in out['sources']:
        if clean_narrative(s['title'],action_allowed=True)!=s['title']: raise PublicationError('unsafe-source-title')
    action_ok='action' in raw and _action_valid(raw['action'],raw,diagnostics,rid)
    if action_ok:
        # If safety edits touch action-bearing prose, withhold the action context as
        # a whole rather than accidentally deleting its negation or prerequisites.
        prose=[raw['title'],raw['summary'], *[s['markdown'] for s in raw['sections']]]
        if any(clean_narrative(t,action_allowed=True) != t and ACTION_TEXT.search(t) for t in prose):
            action_ok=False
    if 'action' in out and not action_ok:
        del out['action']; diagnostic(diagnostics,rid,'action-needs-source-review'); out['assessment']=UNAVAILABLE
    if 'assessment' in out:
        known=LABELS['labels'].get(out['assessment']) or PUBLIC_LABELS.get(out['assessment'])
        if not known:
            out['assessment']=UNAVAILABLE; diagnostic(diagnostics,rid,'unknown-assessment')
        else: out['assessment']=known['label']
        if out['assessment'] in {'Watch','Wait for more evidence','Avoid new purchases'} and not action_ok:
            out['assessment']=UNAVAILABLE
            diagnostic(diagnostics,rid,'action-label-needs-source-review')
    for key in ('title','summary'):
        clean=clean_narrative(out[key],action_allowed=action_ok)
        if clean != out[key]: diagnostic(diagnostics,rid,'withheld-'+key)
        if not clean: raise PublicationError('empty-public-'+key)
        out[key]=clean
    sections=[]
    for section in out['sections']:
        original_section=copy.deepcopy(section)
        section['heading']=clean_narrative(section['heading'],action_allowed=action_ok)
        section['markdown']=clean_narrative(section['markdown'],action_allowed=action_ok)
        if section.get('emoji') and clean_narrative(section['emoji'])!=section['emoji']: section.pop('emoji')
        if section != original_section: diagnostic(diagnostics,rid,'withheld-section')
        if section['heading'] and section['markdown']: sections.append(section)
    out['sections']=sections
    quote=out.get('quote')
    if quote:
        if quote['symbol'] not in out['tickers']: raise PublicationError('quote-symbol-mismatch')
        import math
        if any(isinstance(v,(float,int)) and not math.isfinite(v) for v in quote.values()): raise PublicationError('nonfinite-quote')
        if 'change' in quote and 'changePct' in quote and quote['change'] * quote['changePct'] < 0: raise PublicationError('incompatible-quote-sign')
        if any(k in quote for k in ('change','changePct')):
            if quote.get('period')!='day' or not quote.get('previousAsOf'): raise PublicationError('quote-period-required')
            delta=datetime.fromisoformat(quote['asOf'].replace('Z','+00:00'))-datetime.fromisoformat(quote['previousAsOf'].replace('Z','+00:00'))
            if not 0 < delta.total_seconds() <= 4*86400: raise PublicationError('incompatible-quote-period')
    for history in out.get('thesisHistory',[]):
        for key in ('previousView','evidence','currentView'):
            if clean_narrative(history[key],action_allowed=action_ok)!=history[key]: raise PublicationError('unsafe-history')
    for item in [*out['sections'], *out.get('thesisHistory',[]), *([out['action']] if 'action' in out else [])]:
        if not set(item.get('sourceIds',[])) <= source_ids: raise PublicationError('unknown-source-reference')
    if list(VALIDATOR.iter_errors(out)): raise PublicationError('invalid-public-structure')
    return out

def merge_publications(candidates, previous=(), diagnostics=None):
    """Repeat-safe updates; conflicts fail closed. Revalidate LKG, never relabel its clock."""
    diagnostics=[] if diagnostics is None else diagnostics
    accepted={}
    for old in previous if isinstance(previous,(list,tuple)) else []:
        try:
            clean=normalize_publication(old, [])
            if clean==old: accepted[clean['id']]=clean
        except (PublicationError,TypeError,ValueError): pass
    grouped=defaultdict(list)
    if not isinstance(candidates,(list,tuple)):
        diagnostic(diagnostics,'unidentified','records-not-array')
        candidates=[]
    for raw in candidates:
        rid=raw.get('id') if isinstance(raw,dict) else None
        if not isinstance(rid,str): diagnostic(diagnostics,rid,'missing-id'); continue
        grouped[rid].append(raw)
    for rid, rows in grouped.items():
        if any(row!=rows[0] for row in rows[1:]): diagnostic(diagnostics,rid,'conflicting-duplicate'); continue
        try:
            diagnostic_start = len(diagnostics)
            clean=normalize_publication(rows[0],diagnostics)
            old=accepted.get(rid)
            if old and len(diagnostics) > diagnostic_start:
                diagnostic(diagnostics,rid,'retained-last-valid-after-withholding')
                continue
            if old and (old['jobId']!=clean['jobId'] or old['type']!=clean['type']): raise PublicationError('identity-owner-conflict')
            accepted[rid]=clean
        except (PublicationError,TypeError,ValueError) as exc: diagnostic(diagnostics,rid,str(exc) if isinstance(exc,PublicationError) else 'malformed-record')
    return sorted(accepted.values(),key=lambda r:r['id'])

def _clock(value):
    if not isinstance(value,str) or not re.search(r'T.*(?:Z|[+-]\d\d:\d\d)$',value): return None
    try: datetime.fromisoformat(value.replace('Z','+00:00')); return value
    except ValueError: return None

def _source_clock(value):
    if not isinstance(value,str): return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.isoformat() if parsed.tzinfo is not None else None
    except ValueError: return None

def adapt_markdown(markdown, metadata):
    """Metadata is explicit; neither headings nor filesystem mtimes invent clocks."""
    return {**metadata,'sections':[{'heading':'Research','markdown':markdown}]}

def _rows(value):
    return [v for v in value if isinstance(v,dict) and not has_private_classification(v)] if isinstance(value,(list,tuple)) else []

def _strings(value):
    return [v for v in value if isinstance(v,str)] if isinstance(value,(list,tuple)) else []

def _text(value):
    return value if isinstance(value,str) else ''

def bounded_complete_markdown(text, limit=3200):
    clean=clean_narrative(text)
    blocks=[]; used=0
    for block in re.split(r'\n\s*\n',clean):
        if not block.strip(): continue
        if used+len(block)+2 > limit: continue
        blocks.append(block); used+=len(block)+2
    return '\n\n'.join(blocks)

def adapt_legacy(raw, diagnostics=None, previous=()):
    diagnostics=[] if diagnostics is None else diagnostics
    records=[]
    title_contexts = {}
    def add(rid,job,kind,title,summary,body,tickers,published=None,information=None,sourced_title=None):
        title=clean_narrative(title or '')
        summary=clean_narrative(summary or '')
        if kind == 'company':
            title = title or (tickers[0] + ' research')
            summary = summary or 'Research summary unavailable.'
        if not title or not summary: return
        if kind == 'brief':
            source_heading=re.search(r'^#\s+(.+)$', _text(body), re.M)
            heading=clean_narrative(source_heading.group(1)) if source_heading else ''
            title=bounded_research_title(sourced_title) or (heading if heading and len(heading)<=170 else ('Research update' + (' · '+', '.join(tickers[:3]) if tickers else '')))
        original_body = body if isinstance(body,str) and body else summary
        urls = sorted({u.rstrip('.,;') for u in re.findall(r'https?://[^\s<>\]\)]+', original_body) if safe_url(u.rstrip('.,;'))})
        refs = [{'id':'source-'+str(i+1),'title':urlsplit(url).hostname or 'Source','url':url} for i,url in enumerate(urls)]
        records.append({'schemaVersion':1,'id':rid,'jobId':job,'type':kind,'title':title,'summary':summary,'publishedAt':_source_clock(published),'informationAt':_source_clock(information),'tickers':tickers,'sections':[{'heading':'Research','markdown':original_body,'sourceIds':[r['id'] for r in refs]}],'sources':refs})
        for k,v in (('publishedDate',published),('informationDate',information)):
            if isinstance(v,str) and re.match(r'^\d{4}-\d{2}-\d{2}(?:$|[ T]\d{2}:\d{2})',v):
                try:
                    parsed=datetime.fromisoformat(v.replace('Z','+00:00'))
                    if parsed.tzinfo is None: records[-1][k] = parsed.date().isoformat()
                except ValueError: pass
    for row in _rows(raw.get('tickers')):
        if not isinstance(row,dict): continue
        symbol=row.get('symbol','')
        if not isinstance(symbol,str):
            diagnostic(diagnostics,'unidentified','invalid-legacy-symbol')
            continue
        original_sections=_rows(row.get('_publicSections'))
        if original_sections:
            body='\n\n'.join('## '+clean_narrative(_text(s.get('title')))+'\n\n'+bounded_complete_markdown(_text(s.get('content'))) for s in original_sections if clean_narrative(_text(s.get('title'))) and bounded_complete_markdown(_text(s.get('content'))))
        else:
            body='\n\n'.join('## '+_text(s.get('title','Evidence'))+'\n'+(_text(s.get('summary')) or '\n'.join(_strings(s.get('bullets')))) for s in _rows(row.get('detailSections'))) or row.get('fullSummary') or row.get('summary')
        add('company:'+symbol,'wiki-company-research','company',row.get('title') or symbol,row.get('summary'),body,[symbol],row.get('publishedAt') or row.get('created'),row.get('updated'))
        if records and records[-1]['id'] == 'company:'+symbol:
            urls=sorted({s['url'] for s in records[-1]['sources']} | {u for u in _strings(row.get('_sourceUrls')) if safe_url(u)})
            records[-1]['sources']=[{'id':'source-'+str(i+1),'title':urlsplit(u).hostname or 'Source','url':u} for i,u in enumerate(urls)]
            records[-1]['sections'][0].pop('sourceIds',None)
    for row in _rows(raw.get('cronTimeline')):
        if not isinstance(row,dict): continue
        if row.get('jobId') == 'synthetic-job-03':
            diagnostic(diagnostics,row.get('id'),'private-account-publisher-excluded')
            continue
        # Output IDs are already stable run identities; private job names never become titles.
        job=str(row.get('jobId') or 'legacy-cron')
        title = bounded_research_title(row.get('jobName'))
        rid = 'brief:'+job+':'+str(row.get('id',''))
        source_clock = _source_clock(row.get('runTime'))
        source_date = row['runTime'][:10] if source_clock is None and isinstance(row.get('runTime'), str) else None
        context = (job, title, tuple(explicit_title_tickers(title)), source_clock, source_date)
        title_contexts[rid] = context if rid not in title_contexts or title_contexts[rid] == context else None
        mentioned = row.get('tickers') or sorted(set(re.findall(r'(?<!\w)\$([A-Z][A-Z0-9.-]{0,19})(?!\w)', _text(row.get('articleBody')) + ' ' + _text(row.get('summary')))))
        tickers = sorted(set(_strings(mentioned)) | set(explicit_title_tickers(title)))
        body = '\n\n'.join([_text(row.get('articleBody')), *_strings(row.get('highlights'))])
        from weekly_stock_analysis import is_weekly_analysis
        if is_weekly_analysis(job):
            formatted = clean_narrative(body)
            # Permit line-breaking only, never silently bless removed evidence.
            if re.sub(r'\s+', '', formatted) == re.sub(r'\s+', '', body):
                body = formatted
        add('brief:'+job+':'+str(row.get('id','')),job,'brief',title or clean_narrative(row.get('summary','')).split('\n')[0],row.get('summary'),body,tickers,row.get('runTime'),row.get('informationAt'),sourced_title=title)
    for row in _rows(raw.get('dailyJournal')):
        if not isinstance(row,dict): continue
        add('brief:daily-journal:'+str(row.get('date','')),'daily-journal','brief',row.get('headline'),row.get('summary'),'\n'.join(_strings(row.get('keyTakeaways'))),[t['symbol'] for t in _rows(row.get('interestingTickers')) if isinstance(t.get('symbol'),str)],row.get('publishedAt'),row.get('informationAt'))
    for row in _rows(raw.get('marketPosture')):
        if not isinstance(row,dict): continue
        name=_text(row.get('name'))
        slug=re.sub(r'[^a-z0-9-]','-',name.lower()).strip('-')
        add('theme:'+slug,'market-posture','theme',row.get('plainTitle') or name,row.get('plainEnglish'), '\n'.join(_strings(row.get('watch'))) or row.get('plainEnglish'),[],row.get('publishedAt'),row.get('artifactDate'))
    # Existing canonical market-data row is a separate quote/financial clock, not
    # a replacement research timestamp. Never combine quote periods across jobs.
    financial_rows={}
    for row in _rows((raw.get('aiWarRoomCompleteData') if isinstance(raw.get('aiWarRoomCompleteData'),dict) else {}).get('rows')):
        if isinstance(row.get('symbol'),str) and row.get('symbol') not in financial_rows:
            financial_rows[row.get('symbol')] = row
    for record in records:
        if record['type'] != 'company': continue
        row=financial_rows.get(record['tickers'][0])
        if not row: continue
        currency=row.get('currency')
        if not isinstance(currency,str) or not re.fullmatch(r'[A-Z]{3}',currency): continue
        try:
            instant=datetime.fromisoformat(str(row.get('quoteAsOf','')).replace('Z','+00:00'))
            quote_clock=instant.isoformat() if instant.tzinfo is not None else None
        except ValueError: quote_clock=None
        price=row.get('price')
        import math
        if isinstance(price,(int,float)) and not isinstance(price,bool) and math.isfinite(price) and price >= 0 and quote_clock:
            record['quote']={'symbol':record['tickers'][0],'price':price,'currency':currency,'asOf':quote_clock}
            # Same-row daily change has no previous observation timestamp in the
            # legacy DTO. Omit change rather than fabricate one to pass validation.
        financial=[]
        for field,label in [('ltmRevenue','Revenue, trailing twelve months'),('marketCap','Market capitalization'),('enterpriseValue','Enterprise value'),('cash','Cash'),('debt','Debt')]:
            value=row.get(field)
            if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
                financial.append(f'- {label}: {currency} {value:,.2f}.')
        for field,label in [('revenueGrowthPct','Revenue growth'),('grossMarginPct','Gross margin'),('operatingMarginPct','Operating margin'),('fcfMarginPct','Free cash flow margin')]:
            value=row.get(field)
            if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
                financial.append(f'- {label}: {value:g}%.')
        if financial:
            record['sections'].append({'heading':'Financial context','markdown':'Financial reporting date unavailable. These metrics are distinct from the quote timestamp.\n\n'+'\n'.join(financial)})
    merged = merge_publications(records, previous,diagnostics)
    # A source-authored heading can fill an old generic title even when unsafe
    # body edits keep the prior valid evidence. Never advance clocks or replace
    # an existing informative title; only bind context to the exact job/run ID.
    for index, record in enumerate(merged):
        context = title_contexts.get(record['id'])
        if not context or not context[1] or record['type'] != 'brief' or record['jobId'] != context[0]:
            continue
        if not (context[3] or context[4]) or context[3] != record.get('publishedAt') or context[4] != record.get('publishedDate'):
            continue
        if not re.fullmatch(r'Research update(?: · .+)?', record['title']):
            continue
        corrected = {**record, 'title': context[1], 'tickers': sorted(set(record['tickers']) | set(context[2]))}
        try:
            if normalize_publication(corrected, []) == corrected:
                merged[index] = corrected
        except (PublicationError, TypeError, ValueError):
            pass
    return merged

def assert_public_suitability(snapshot):
    """Final egress gate, including old snapshots lacking publications.

    Transport must reject unsafe historical payloads, not trust a producer badge.
    """
    legacy={k:v for k,v in snapshot.items() if k not in {'schemaVersion','dataAsOf','refreshMode','focusTickers','sourceHealth','privacy','publications','macroRegimeMeter'}}
    if has_private_classification(legacy) or sanitize_legacy(legacy) != legacy:
        raise PublicationError('legacy-public-suitability-failed')
    for record in snapshot.get('publications',[]):
        if normalize_publication(record,[]) != record:
            raise PublicationError('publication-not-approved')

# Apply to legacy DTO too: safe new publications alone cannot protect a public JSON.
NARRATIVE_KEYS={'title','summary','fullSummary','headline','plainTitle','plainEnglish','thesis','catalyst','risk','trigger','entryPoint','shortlistThesis','shortlistRisk','tierReason','markdown','articleBody','why','text','bullets','highlights','keyTakeaways','details','goldSilver','watch','recommendation','policy','description','reason','entryReason','whyNotNow','proofTrigger','killTrigger','entry','opportunityCost','proof','blockedBy','selfHealSummary','brokerSafetyFindings','contradictions','howUsed'}
STATUS_KEYS={'status','stance','action','actionBucket','shortlistRec','shortlistStatus','state','actionMode','warRoomAction','dataQualityLabel','proofLevel','valuationSignal','researchTier','fromAction','toAction','decision','decisionState','capitalPriority','returnRole','tier','bucket','fromBucket','toBucket','zone'}
STATUS_KEYS |= {'entryStatus', 'researchTier'}
OMIT_KEYS={'sourcePath','sourcePaths','outputPath','artifactPaths','sourcePage','checkerPath','finalPath','decisionEventsPath','schedule','deliver','jobName','privateSizingHidden','sizeFrame','sizeClass','fundingClass','whyThisHelps50to100','targetContribution','capitalEligible','capitalEligibleFromProjection','capitalEligibleCount','slack_policy','slackWorthy','slackWorthyEventCount','slackWorthyEventCount','automation','membershipWorkflow','runSummary','decisionLearning','allowedNodes','blockedNodes','selfHealSummary','brokerSafetyFindings','sourceTypes'}

def sanitize_legacy(value, key='', diagnostics=None, pointer='$', record_id='legacy', job_id=None):
    diagnostics=[] if diagnostics is None else diagnostics
    def report(code):
        diagnostic(diagnostics,record_id,code)
        diagnostics[-1]['field'] = pointer
        if isinstance(job_id,str) and re.fullmatch(r'[A-Za-z0-9:._-]{1,160}',job_id):
            diagnostics[-1]['jobId'] = job_id
    identity = sanitize_graph_identity(value, pointer)
    if identity is not None:
        return identity
    if re.fullmatch(r'\$\.cronTimeline\[\d+\]\.jobName', pointer):
        return bounded_research_title(value)
    if re.fullmatch(r'\$\.cronTimeline\[\d+\]\.id', pointer):
        return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._-]{0,199}', value) and not re.search(r'(?i)account|credential|password|secret|token', value) else ''
    # These generator-owned workflow names identify checks, not recommendations.
    if re.fullmatch(r'\$\.marketGraphs\[\d+\]\.label', pointer) and value in ('Market research checks', 'Market research → CIO dashboard', 'Earnings proof gate'):
        return value
    # Operational health is not an investment assessment. Preserve only bounded
    # enums at exact public graph/health paths; never carry arbitrary status prose.
    operational_path = (
        re.fullmatch(r'\$\.marketGraphs\[\d+\]\.(?:finalGate|graphNodes\[\d+\]\.status|graphEdges\[\d+\]\.status|decisionEvents\[\d+\]\.gate)', pointer)
        or re.fullmatch(r'\$\.sourceHealth\.(?:status|overall|sections\.[A-Za-z][A-Za-z0-9]*\.(?:status|validation|producer\.latestStatus))', pointer)
    )
    if operational_path:
        operational_enums = {'pass', 'fail', 'failed', 'error', 'degraded', 'warning',
                             'pending', 'unknown', 'missing', 'ok', 'success',
                             'blocked', 'stale', 'paused'}
        if pointer.endswith('.producer.latestStatus'):
            operational_enums.add('not_applicable')
        if isinstance(value, str) and value in operational_enums:
            return value
        report('unknown-operational-status')
        return 'unknown'
    # Exact field and exact enum only: never relax generic bucket/action labels.
    if pointer == '$.currentAsymmetricShortlist.membershipPolicy.bucketMode' and value == 'mutually_exclusive':
        return value
    if re.fullmatch(r'\$\.currentAsymmetricShortlist\.membershipPolicy\.bucketOrder\[\d+\]', pointer):
        if isinstance(value, str) and value in MEMBERSHIP_BUCKETS:
            return value
        report('unknown-membership')
        return ''
    if key == 'bucket' and re.fullmatch(r'\$\.currentAsymmetricShortlist\.rows\[\d+\]\.bucket', pointer):
        if isinstance(value, str) and value in MEMBERSHIP_BUCKETS:
            return value
        if value != UNAVAILABLE: report('unknown-membership')
        return UNAVAILABLE
    if isinstance(value,dict):
        privacy = value.get('privacy_class', value.get('privacyClass'))
        if privacy not in (None, '', 'public', 'public_ok') or value.get('jobId') == 'synthetic-job-03': return None
        if pointer == '$.currentAsymmetricShortlist':
            # Withhold incompatible source assignments, without interpreting prose,
            # prices, research tier, entry state, or private eligibility as buckets.
            rows = value.get('rows')
            policy = value.get('membershipPolicy')
            incompatible = ('membershipPolicy' in value and not isinstance(policy, dict)) or (
                isinstance(policy, dict) and policy.get('bucketMode', 'mutually_exclusive') != 'mutually_exclusive')
            if isinstance(rows, list):
                assignments = defaultdict(list)
                for row in rows:
                    if isinstance(row, dict) and isinstance(row.get('symbol'), str):
                        assignments[row['symbol']].append(row.get('bucket'))
                conflicts = {symbol for symbol, buckets in assignments.items()
                             if any(bucket != buckets[0] for bucket in buckets[1:])}
                if incompatible or conflicts:
                    report('incompatible-membership')
                    value = {**value, 'rows': [
                        {**row, 'bucket': UNAVAILABLE} if isinstance(row, dict) and
                        (incompatible or row.get('symbol') in conflicts) else row for row in rows]}
        record_id = value.get('id') or value.get('symbol') or record_id
        job_id = value.get('jobId') or job_id
        cleaned = {k:(v if k in {'privacy_class','privacyClass'} else sanitize_legacy(v,k,diagnostics,pointer+'.'+re.sub(r'[^A-Za-z0-9_-]','?',k)[:80],record_id,job_id)) for k,v in value.items() if k not in OMIT_KEYS or (k == 'jobName' and re.fullmatch(r'\$\.cronTimeline\[\d+\]', pointer))}
        if re.fullmatch(r'\$\.cronTimeline\[\d+\]', pointer) and not any(cleaned.get(k) for k in ('summary', 'highlights', 'articleBody')):
            report('empty-research-update')
            return None
        return cleaned
    if isinstance(value,list):
        result=[sanitize_legacy(v,key,diagnostics,pointer+'['+str(i)+']',record_id,job_id) for i,v in enumerate(value)]
        return [v for v in result if v not in ('',None)]
    if isinstance(value,str):
        if key == 'entryStatus' or (key == 'status' and value in {'pass','fail','degraded','pending','unknown','missing','ok','success','blocked'}):
            return value
        if key in STATUS_KEYS:
            label=LABELS['labels'].get(value) or PUBLIC_LABELS.get(value)
            if not label: report('unknown-assessment')
            return label['label'] if label else UNAVAILABLE
        structural = {'id','jobId','symbol','primaryTicker','exchange','tradingViewSymbol','currency','date','updated','created','generatedAt','artifactDate','runTime','quoteAsOf','informationAt','publishedAt','dataAsOf','workflowId','runId','kind','from','to','entryStatus','privacyClass','privacy_class','tags','category','name','sourceType'}
        if key in NARRATIVE_KEYS or key not in structural:
            clean=clean_narrative(value)
            if clean!=value: report('withheld-narrative')
            return clean
        if PRIVATE.search(value) or OPERATIONAL.search(value) or MALFORMED.search(value) or AMBIGUOUS.search(value):
            report('withheld-value')
            return ''
    return value
