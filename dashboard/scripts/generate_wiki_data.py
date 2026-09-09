#!/usr/bin/env python3
"""Generate a public-safe static dashboard payload from explicitly configured local inputs."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_market_brief import LANE_JOBS, timestamp, validate_note
from public_content import clean_narrative, safe_url, has_private_classification, MEMBERSHIP_BUCKETS, UNAVAILABLE
from brief_titles import bounded_research_title, source_brief_title
from weekly_stock_analysis import is_weekly_analysis, weekly_selection, retain_verified_weekly_history
from macro_presentation import MACRO_JOB_IDS, CONFIDENCE_HELP, macro_row
from public_snapshot import (
    MixedGenerationError,
    PrivacyError,
    atomic_write_bytes,
    build_public_snapshot,
    canonical_json_bytes,
    represented_data_as_of,
    snapshot_id,
    stable_build,
    validate_public_snapshot_schema,
)

from dashboard_config import WIKI_ROOT, CRON_ROOT, CACHE_ROOT, require_wiki
OFFLINE = True
WIKI = WIKI_ROOT
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'public' / 'wiki-data.json'
TRADINGVIEW_CACHE = CACHE_ROOT / 'tradingview-symbols.json'
PRIVATE_PATH_PARTS = {'data/portfolio', 'brokerage', '.env'}



def safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if value == value else None
    return None


def clean_path(path: Any, limit: int = 220) -> str:
    raw = str(path or '')
    raw = raw.replace(str(WIKI) + '/', '').replace(str(ROOT) + '/', '')
    if raw.startswith('/root/'):
        raw = Path(raw).name
    return clean_inline(raw)[:limit]


def public_chart_title(filename: str) -> str:
    title = re.sub(r'^\d+_', '', Path(filename).stem).replace('_', ' ')
    return title[:1].upper() + title[1:]


def primitive_chart_rows(rows: Any, limit: int = 80) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean_row: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, str):
                clean_row[clean_inline(str(key))[:80]] = clean_inline(value)[:240]
            elif value is None or isinstance(value, bool):
                clean_row[clean_inline(str(key))[:80]] = value
            else:
                clean_row[clean_inline(str(key))[:80]] = safe_number(value)
        out.append(clean_row)
    def row_key(row: dict[str, Any]) -> tuple[str, str]:
        symbol = clean_inline(str(row.get('symbol') or row.get('ticker') or '')).upper()
        return (symbol or 'ZZZ', json.dumps(row, sort_keys=True, default=str)[:240])
    return sorted(out, key=row_key)[:limit]


def parse_ai_projection_exhibits() -> dict[str, Any] | None:
    """Load the local AI projection/comps artifact and copy chart PNGs into public/.

    This is deliberately public-safe: ticker-level metrics only, no account-scale
    dollars, no position quantities, and no raw private broker artifacts.
    """
    path = WIKI / 'data/automation/ai_projection_exhibits_latest.json'
    if not path.exists():
        return None
    try:
        payload = json.loads(read(path))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    meta = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    rows: list[dict[str, Any]] = []
    for row in payload.get('rows', [])[:80]:
        if not isinstance(row, dict):
            continue
        market = row.get('market') if isinstance(row.get('market'), dict) else {}
        fin = row.get('financials') if isinstance(row.get('financials'), dict) else {}
        val = row.get('valuation') if isinstance(row.get('valuation'), dict) else {}
        dq = row.get('dataQuality') if isinstance(row.get('dataQuality'), dict) else {}
        proj = row.get('projection') if isinstance(row.get('projection'), dict) else {}
        mb = row.get('multiBagPath') if isinstance(row.get('multiBagPath'), dict) else {}
        def case(name: str) -> dict[str, Any]:
            c = proj.get(name) if isinstance(proj.get(name), dict) else {}
            return {
                'revenueCagrPct': safe_number(c.get('revenueCagrPct')),
                'terminalMultiple': safe_number(c.get('terminalMultiple')),
                'impliedPrice': safe_number(c.get('impliedPrice')),
                'upsidePct': safe_number(c.get('upsidePct')),
                'proofNeeded': clean_inline(str(c.get('proofNeeded') or ''))[:220],
            }
        rows.append({
            'symbol': clean_inline(str(row.get('symbol') or ''))[:16],
            'companyName': clean_inline(str(row.get('companyName') or ''))[:120],
            'researchTier': clean_inline(str(row.get('researchTier') or ''))[:40],
            'tierReviewed': clean_inline(str(row.get('tierReviewed') or ''))[:40],
            'tierReason': clean_inline(str(row.get('tierReason') or ''))[:320],
            'instrumentRisk': clean_inline(str(row.get('instrumentRisk') or ''))[:40],
            'archetype': clean_inline(str(row.get('archetype') or 'unknown'))[:80],
            'benchmarkGroup': clean_inline(str(row.get('benchmarkGroup') or row.get('archetype') or 'unknown'))[:80],
            'sourcePage': clean_path(row.get('sourcePage')),
            'inclusionReason': clean_inline(str(row.get('inclusionReason') or ''))[:260],
            'price': safe_number(market.get('price')),
            'marketCap': safe_number(market.get('marketCap')),
            'enterpriseValue': safe_number(market.get('enterpriseValue')),
            'quoteAsOf': clean_inline(str(market.get('quoteAsOf') or ''))[:80],
            'fundamentalsAsOf': clean_inline(str(row.get('fundamentalsAsOf') or ''))[:80],
            'fundamentalsSource': clean_inline(str(row.get('fundamentalsSource') or ''))[:120],
            'ltmRevenue': safe_number(fin.get('ltmRevenue')),
            'ntmRevenue': safe_number(fin.get('ntmRevenue')),
            'ntmRevenueGrowthPct': safe_number(fin.get('ntmRevenueGrowthPct')),
            'evNtmRevenue': safe_number(val.get('evNtmRevenue')),
            'peNtm': safe_number(val.get('peNtm')),
            'evEbitdaNtm': safe_number(val.get('evEbitdaNtm')),
            'fcfMarginPct': safe_number(fin.get('fcfMarginPct')),
            'sectorPercentile': safe_number(val.get('sectorPercentile')),
            'ownHistoryPercentile': safe_number(val.get('ownHistoryPercentile')),
            'valuationSignal': clean_inline(str(val.get('valuationSignal') or 'unknown'))[:40],
            'relativeValueScore': safe_number(val.get('relativeValueScore')),
            'dataQualityLabel': clean_inline(str(dq.get('label') or 'unknown'))[:40],
            'dataQualityScore': safe_number(dq.get('score')),
            'missingCriticalFields': [clean_inline(str(x))[:80] for x in (dq.get('missingCriticalFields') or []) if x][:12],
            'bear': case('bear'),
            'base': case('base'),
            'bull': case('bull'),
            'multiBagPlausibility': clean_inline(str(mb.get('plausibility') or 'unknown'))[:40],
            'mainBottleneck': clean_inline(str(mb.get('mainBottleneck') or ''))[:220],
            'warRoomAction': clean_inline(str(row.get('warRoomAction') or ''))[:120],
            'capitalEligibleFromProjection': bool(row.get('capitalEligibleFromProjection')),
        })
    rows = sorted(rows, key=lambda row: clean_inline(str(row.get('symbol') or '')).upper())
    artifact_date = clean_inline(str(meta.get('artifactDate') or 'latest'))[:40]
    dq_counts: dict[str, int] = defaultdict(int)
    valuation_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        dq_counts[str(row.get('dataQualityLabel') or 'unknown')] += 1
        valuation_counts[str(row.get('valuationSignal') or 'unknown')] += 1
    chart_data = payload.get('chartData') if isinstance(payload.get('chartData'), dict) else {}
    return {
        'generatedAt': clean_inline(str(meta.get('generatedAt') or payload.get('generatedAt') or ''))[:80],
        'artifactDate': artifact_date,
        'policy': clean_inline(str(meta.get('policy') or 'Projection/relative value is one signal only.'))[:260],
        # Source may be private-local; this parser emits a separate public DTO.
        'privacyClass': 'public',
        'rowCount': len(rows),
        'excludedDiscoveredCount': int(meta.get('excludedDiscoveredCount') or 0),
        'sourcePaths': [clean_path(x) for x in meta.get('sourcePaths', []) if x and 'strategy-data.json' not in str(x) and 'main_strategy_data.json' not in str(x)],
        'summary': {
            'dataQuality': dict(sorted(dq_counts.items())),
            'valuationSignals': dict(sorted(valuation_counts.items())),
            'capitalEligibleCount': sum(1 for row in rows if row.get('capitalEligibleFromProjection')),
            'degradedOrMissingCount': sum(1 for row in rows if row.get('dataQualityLabel') in {'degraded', 'missing'}),
        },
        'rows': rows,
        'chartData': {clean_inline(str(k))[:80]: primitive_chart_rows(v) for k, v in chart_data.items()},
        'artifactPaths': {
            'json': 'data/automation/ai_projection_exhibits_latest.json',
            'csv': 'data/automation/ai_projection_exhibits_latest.csv',
            'historyCsv': 'data/automation/ai_projection_exhibits_history.csv',
            'markdown': f'research/ai_projection_exhibits_{artifact_date}.md',
        },
    }


def parse_ai_war_room_complete_data() -> dict[str, Any] | None:
    """Load The operator's complete-data AI War Room artifact for dashboard tables/charts.

    The source artifact is ticker-level public market research only. This parser
    deliberately keeps account-scale and brokerage details out of public JSON.
    """
    path = WIKI / 'data/automation/ai_war_room_complete_data_latest.json'
    manifest_path = WIKI / 'data/automation/ai_war_room_refresh_manifest.json'
    if not path.exists():
        return None
    try:
        payload = json.loads(read(path))
    except Exception:
        return None
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(read(manifest_path))
        except Exception:
            manifest = {}
    manifest_rows = manifest.get('rows', []) if isinstance(manifest.get('rows'), list) else []
    completed = sum(1 for row in manifest_rows if isinstance(row, dict) and row.get('status') == 'complete')
    pending = sum(1 for row in manifest_rows if isinstance(row, dict) and row.get('status') in {'pending', 'in_progress'})
    errors = sum(1 for row in manifest_rows if isinstance(row, dict) and row.get('status') == 'error')

    rows: list[dict[str, Any]] = []
    action_counts: dict[str, int] = defaultdict(int)
    data_quality_counts: dict[str, int] = defaultdict(int)
    for row in payload.get('rows', [])[:120]:
        if not isinstance(row, dict):
            continue
        ident = row.get('identity') if isinstance(row.get('identity'), dict) else {}
        tape = row.get('tape') if isinstance(row.get('tape'), dict) else {}
        fv = row.get('fundamentalValuation') if isinstance(row.get('fundamentalValuation'), dict) else {}
        proof = row.get('aiWarRoomProof') if isinstance(row.get('aiWarRoomProof'), dict) else {}
        decision = row.get('decision') if isinstance(row.get('decision'), dict) else {}
        sources = row.get('sources') if isinstance(row.get('sources'), dict) else {}
        primary_sources = sources.get('primaryAndWiki') if isinstance(sources.get('primaryAndWiki'), list) else []
        quote_sources = sources.get('quoteFundamentals') if isinstance(sources.get('quoteFundamentals'), dict) else {}
        action = clean_inline(str(decision.get('action') or 'unknown'))[:140]
        dq = clean_inline(str(row.get('dataQualityLabel') or 'unknown'))[:80]
        action_counts[action.split('/')[0].strip() or action] += 1
        data_quality_counts[dq] += 1
        rows.append({
            'symbol': clean_inline(str(row.get('symbol') or ident.get('primaryTicker') or ''))[:16],
            'primaryTicker': clean_inline(str(ident.get('primaryTicker') or row.get('symbol') or ''))[:24],
            'companyName': clean_inline(str(ident.get('companyName') or ''))[:140],
            'researchTier': clean_inline(str(row.get('researchTier') or ''))[:40],
            'tierReviewed': clean_inline(str(row.get('tierReviewed') or ''))[:40],
            'tierReason': clean_inline(str(row.get('tierReason') or ''))[:320],
            'instrumentRisk': clean_inline(str(row.get('instrumentRisk') or ''))[:40],
            'exchange': clean_inline(str(ident.get('exchange') or ''))[:40],
            'currency': clean_inline(str(ident.get('currency') or 'USD'))[:12],
            'price': safe_number(tape.get('price')),
            'quoteAsOf': clean_inline(str(tape.get('quoteAsOf') or ''))[:80],
            'dayChangePct': safe_number(tape.get('dayChangePct')),
            'oneMonthChangePct': safe_number(tape.get('oneMonthChangePct')),
            'threeMonthChangePct': safe_number(tape.get('threeMonthChangePct')),
            'ytdChangePct': safe_number(tape.get('ytdChangePct')),
            'sma20': safe_number(tape.get('sma20')),
            'sma50': safe_number(tape.get('sma50')),
            'sma200': safe_number(tape.get('sma200')),
            'marketCap': safe_number(fv.get('marketCap')),
            'enterpriseValue': safe_number(fv.get('enterpriseValue')),
            'ltmRevenue': safe_number(fv.get('ltmRevenue')),
            'ntmRevenueEstimate': safe_number(fv.get('ntmRevenueEstimate')),
            'revenueGrowthPct': safe_number(fv.get('revenueGrowthPct')),
            'fy1RevenueGrowthPct': safe_number(fv.get('fy1RevenueGrowthPct')),
            'fy2RevenueGrowthPct': safe_number(fv.get('fy2RevenueGrowthPct')),
            'grossMarginPct': safe_number(fv.get('grossMarginPct')),
            'operatingMarginPct': safe_number(fv.get('operatingMarginPct')),
            'fcfMarginPct': safe_number(fv.get('fcfMarginPct')),
            'epsNtm': safe_number(fv.get('epsNtm')),
            'cash': safe_number(fv.get('cash')),
            'debt': safe_number(fv.get('debt')),
            'evRevenue': safe_number(fv.get('evRevenue')),
            'evNtmRevenue': safe_number(fv.get('evNtmRevenue')),
            'peNtm': safe_number(fv.get('peNtm')),
            'evEbitda': safe_number(fv.get('evEbitda')),
            'relativePeerValuation': clean_inline(str(fv.get('relativePeerValuation') or ''))[:360],
            'backlogOrdersRpo': clean_inline(str(proof.get('backlogOrdersRpo') or ''))[:300],
            'customerProof': clean_inline(str(proof.get('customerProof') or ''))[:300],
            'insiderFlow': clean_inline(str(proof.get('insiderFlow') or ''))[:260],
            'macroTape': clean_inline(str(proof.get('macroTape') or ''))[:260],
            'proofLevel': safe_number(decision.get('proofLevel')),
            'action': action,
            'actionDelta': clean_inline(str(decision.get('actionDelta') or ''))[:220],
            'starterZone': clean_inline(str(decision.get('starterZone') or ''))[:260],
            'addZone': clean_inline(str(decision.get('addZone') or ''))[:260],
            'killZone': clean_inline(str(decision.get('killZone') or ''))[:260],
            'nextCatalystCheckDate': clean_inline(str(decision.get('nextCatalystCheckDate') or ''))[:160],
            'sizeFrame': clean_inline(str(decision.get('sizeFrame') or ''))[:160],
            'dataQualityLabel': dq,
            'missingCriticalFields': [clean_inline(str(x))[:80] for x in (row.get('missingCriticalFields') or []) if x][:16],
            'sourceFreshness': clean_inline(str(sources.get('sourceFreshness') or ''))[:260],
            'sourcePaths': [clean_path(x) for x in primary_sources[:8]] + [clean_path(x) for x in quote_sources.values()][:3],
        })

    rows = sorted(rows, key=lambda row: clean_inline(str(row.get('symbol') or '')).upper())
    chart_rows = [{'symbol': r['symbol'], 'researchTier': r.get('researchTier'), 'tierReviewed': r.get('tierReviewed'), 'tierReason': r.get('tierReason'), 'instrumentRisk': r.get('instrumentRisk'), 'revenueGrowthPct': r.get('revenueGrowthPct'), 'evNtmRevenue': r.get('evNtmRevenue'), 'proofLevel': r.get('proofLevel'), 'marketCap': r.get('marketCap'), 'action': r.get('action'), 'dataQualityLabel': r.get('dataQualityLabel')} for r in rows]
    return {
        'generatedAt': clean_inline(str(payload.get('generatedAt') or payload.get('metadata', {}).get('generatedAt') or ''))[:80],
        'rowCount': len(rows),
        'manifest': {'completed': completed or len(rows), 'pending': pending, 'errors': errors, 'total': len(manifest_rows) or len(rows)},
        'summary': {'actions': dict(sorted(action_counts.items())), 'dataQuality': dict(sorted(data_quality_counts.items()))},
        'sourcePaths': ['data/automation/ai_war_room_complete_data_latest.json', 'data/automation/ai_war_room_complete_data_latest.csv', 'data/automation/ai_war_room_refresh_manifest.json', 'research/ai_war_room_complete_data_refresh_latest.md'],
        'rows': rows,
        'chartData': {
            'growth_vs_valuation': chart_rows,
            'proof_level_bar': chart_rows,
            'market_cap_bar': chart_rows,
        },
    }

def parse_decision_learning() -> dict[str, Any] | None:
    """Project the small receipt/exception summary; never expose raw receipt files."""
    path = WIKI / 'data/automation/decision_learning_latest.json'
    if not path.exists():
        return None
    try:
        raw = json.loads(read(path))
    except Exception:
        return None
    receipt_fields = {
        'id', 'recordedAt', 'symbol', 'decision', 'decisionState', 'researchTier',
        'thesis', 'entry', 'proofTrigger', 'killTrigger', 'sizeClass',
        'decisionExpiration', 'decisionQuote', 'quoteAsOf', 'fundingClass',
        'completeness', 'missingFields', 'recordReason',
    }
    exception_fields = {
        'id', 'symbol', 'classification', 'question', 'status', 'sourceReceiptId',
        'nextReviewEvent', 'lessonCandidate',
    }
    outcome_fields = {
        'receiptId', 'sourceReceiptId', 'symbol', 'receiptDecision', 'priorDecision',
        'currentDecision', 'state', 'status', 'classification', 'observedAt',
        'returnPct', 'reviewReason', 'reason', 'supersededBy',
    }
    candidate_fields = {
        'id', 'symbol', 'classification', 'question', 'status', 'sourceReceiptId',
        'observedAt', 'severity', 'priorDecision', 'currentDecision',
        'nextReviewEvent', 'lessonCandidate', 'returnPct',
    }
    handoff_fields = {
        'canonicalState', 'capitalBoard', 'warRoom', 'weeklyIc', 'casebook',
        'dashboard', 'outcomes', 'policyRules',
    }
    receipts = []
    for row in (raw.get('recentReceipts') or [])[:6]:
        if not isinstance(row, dict):
            continue
        receipts.append({
            key: ([clean_inline(str(x))[:120] for x in value[:12]] if key == 'missingFields' and isinstance(value, list)
                  else clean_inline(str(value))[:360] if isinstance(value, str)
                  else value)
            for key, value in row.items() if key in receipt_fields
        })
    exceptions = []
    for row in (raw.get('openExceptions') or [])[:3]:
        if not isinstance(row, dict):
            continue
        exceptions.append({key: clean_inline(str(value))[:360] if isinstance(value, str) else value for key, value in row.items() if key in exception_fields})
    outcomes = []
    for row in (raw.get('recentOutcomes') or [])[:6]:
        if not isinstance(row, dict):
            continue
        outcomes.append({
            key: clean_inline(str(value))[:360] if isinstance(value, str) else value
            for key, value in row.items() if key in outcome_fields
        })
    candidates = []
    for row in (raw.get('exceptionCandidates') or []):
        if len(candidates) >= 3:
            break
        if not isinstance(row, dict) or str(row.get('status') or '').lower() != 'candidate':
            continue
        candidates.append({
            key: clean_inline(str(value))[:360] if isinstance(value, str) else value
            for key, value in row.items() if key in candidate_fields
        })
    handoffs = raw.get('handoffs') if isinstance(raw.get('handoffs'), dict) else {}
    return {
        'generatedAt': clean_inline(str(raw.get('generatedAt') or ''))[:80],
        'policy': clean_inline(str(raw.get('policy') or ''))[:320],
        'receiptCount': int(raw.get('receiptCount') or 0),
        'newReceiptCount': int(raw.get('newReceiptCount') or 0),
        'integrityGapCount': int(raw.get('integrityGapCount') or 0),
        'openExceptionCount': min(int(raw.get('openExceptionCount') or len(exceptions)), 3),
        'outcomeCount': int(raw.get('outcomeCount') or len(outcomes)),
        'reviewDueCount': int(raw.get('reviewDueCount') or 0),
        'candidateExceptionCount': int(raw.get('candidateExceptionCount') or len(candidates)),
        'policyRuleCount': int(raw.get('policyRuleCount') or 0),
        'adoptedPolicyRuleCount': int(raw.get('adoptedPolicyRuleCount') or 0),
        'unlinkedPolicyRuleCount': int(raw.get('unlinkedPolicyRuleCount') or 0),
        'casebookCount': int(raw.get('casebookCount') or 0),
        'casebookPolicy': clean_inline(str(raw.get('casebookPolicy') or ''))[:240],
        'recentReceipts': receipts,
        'openExceptions': exceptions,
        'recentOutcomes': outcomes,
        'exceptionCandidates': candidates,
        'handoffs': {key: clean_inline(str(value))[:180] for key, value in handoffs.items() if key in handoff_fields and not str(value).startswith('/')},
    }


SHORTLIST_JOB_SPECS = (
    ("research_feed", "Research Feed Digest", r"^Research Feed Digest$", "discovery", "Finds new source-backed candidates", ["research-queue.md"]),
    ("x_signal", "X Signal Scanner", r"^X Signal Scanner", "discovery", "Adds corroborated source/crowding signals", ["raw/signals/x_signals_*.json"]),
    ("sec_insider", "SEC Insider Buying Scanner", r"^SEC Insider Buying Scanner", "discovery", "Adds qualifying primary-source insider evidence", ["raw/signals/insider_buying_scan_*.json"]),
    ("earnings_scheduler", "Earnings Auto-Scheduler", r"^Earnings Auto-Scheduler$", "discovery", "Creates event-scoped earnings research runs", ["daily/briefs/*earnings*.md"]),
    ("earnings_preview", "Weekly Earnings Preview", r"^Weekly Earnings Preview$", "discovery", "Prioritizes upcoming proof events", ["daily/briefs/*earnings_preview.md"]),
    ("watchlist_movers", "Watchlist Movers + News", r"^Watchlist Movers \+ News Trigger Scan", "discovery", "Detects material price/news resets without promoting on price alone", ["data/automation/watchlist_movers_latest.json"]),
    ("explosive_radar", "Explosive Stock Radar", r"^Weekly Explosive Misunderstood Stock Radar$", "discovery", "Surfaces misunderstood candidates; any list change remains a reviewed agent decision", ["queries/daily_monitor_queue.md", "tickers/*.md"]),
    ("last30days_monthly", "Monthly Signal Scan", r"^last30days Monthly Signal-Only", "discovery", "Adds typed social/news leads from a bounded monthly source pack", ["raw/briefings/source_packs/last30days_monthly_signal_*.md"]),
    ("last30days_midweek", "Midweek Crowding Check", r"^last30days Midweek Crowding Check", "discovery", "Adds crowding context; cannot promote without company proof", ["raw/briefings/source_packs/last30days_midweek_crowding_*.md"]),
    ("x_referral", "Social Source Discovery", r"^Social Source Discovery", "discovery", "Maintains an anonymous source set; context-only, not a core signal dependency", ["raw/signals/*referral*.json"]),
    ("weekly_deep_dive", "Weekly Stock Analysis", r"^(?:Weekly Hybrid Stock Deep Dive|Weekly Stock Analysis)$", "research", "Produces or refreshes ticker theses and proof/kill gates", ["tickers/*.md", "research-queue.md"]),
    ("weekly_hygiene", "Weekly Wiki Research Refresh", r"^Weekly Market-Wiki Hygiene \+ Research Refresh$", "research", "Rotates stale ticker research and repairs coverage", ["tickers/*.md", "research-queue.md"]),
    ("rerate", "Re-rate Monitor", r"^Re-rate monitor$", "research", "Rechecks close-watch names after business evidence changes", ["queries/daily_monitor_queue.md", "tickers/*.md"]),
    ("graph_morning", "Morning Research Checker", r"^Market Graph Morning Checker", "proof", "Checks source quality, freshness, contradictions, and privacy", ["data/automation/graph_runs/*/decision_events.json"]),
    ("graph_late", "Late-day Research Checker", r"^Market Graph Phase 1 Checker", "proof", "Rechecks evidence after the market day", ["data/automation/graph_runs/*/decision_events.json"]),
    ("transcript_recovery", "Earnings Transcript Recovery", r"^Earnings Transcript Recovery Pilot", "proof", "Repairs one bounded transcript gap when requested by a checker", ["data/automation/transcript_recovery_*"] ),
    ("event_trigger_fleet", "Stock Event Trigger Fleet", r"^Stock Event Trigger Fleet$", "proof", "Monitors proof and kill conditions for names with explicit event contracts", ["data/automation/event_triggers/*.json"]),
    ("projection_builder", "AI Projection Fundamentals", r"^AI Projection Fundamentals \+ Exhibits Builder$", "proof", "Builds fundamentals and valuation exhibits used by relative-value checker nodes", ["data/automation/ai_projection_fundamentals_latest.json", "data/automation/ai_projection_exhibits_latest.json"]),
    ("morning_brief", "Morning Market Briefing", r"^Morning Market Briefing$", "market", "Supplies macro, breadth, exposure, and event context", ["daily/briefs/YYYY-MM-DD.md", "raw/briefings/tradermonty/"] ),
    ("price_watchdog", "Intraday Price-Zone Watchdog", r"^Intraday Equity Price-Zone Watchdog", "market", "Refreshes quote/entry-zone state; never promotes on price alone", ["data/automation/intraday_equity_watchdog.json"]),
    ("fast_money", "CNBC Fast Money Transcript", r"^CNBC Fast Money Transcript", "market", "Adds transcript/macro context; an OK job may still represent a deliberately degraded source note", ["daily/fastmoney/*.md"]),
    ("daily_macro_transcript", "Daily Macro Transcript Analysis", r"^Daily Macro Transcript Analysis", "market", "Adds macro narrative and conditional ticker evidence", ["daily/macro_transcripts/*.md"]),
    ("precious_metals", "Precious Metals Macro Scan", r"^Precious Metals Daily Macro Scan", "market", "Adds rates, dollar, liquidity, and metals regime context", ["research/precious_metals/latest.md"]),
    ("macro_shift", "Macro Regime Shift Monitor", r"^Market Brief — Macro regime shift monitor$", "market", "Writes only material regime changes; global context cannot promote a ticker alone", ["daily/briefs/macro_shift_*.md", "daily/briefs/market_brief_macro_shift_*.md"]),
    ("portfolio_data", "Portfolio-data Integration", r"^Portfolio-data Integration$", "portfolio", "Provides privacy-filtered portfolio context to the capital gate", ["data/automation/portfolio_data_integration_status.json"]),
    ("freshness_gate_job", "Market Wiki Freshness Gate", r"^Market Wiki Freshness Gate$", "gate", "Runs the canonical builder and fails closed on stale dependencies", ["data/automation/current_asymmetric_shortlist_latest.json"]),
    ("integrity_watchdog", "MarketWiki Integrity Watchdog", r"^MarketWiki daily freshness \+ integrity watchdog$", "delivery", "Checks the generated Wiki decision surfaces", ["data/automation/shortlist_freshness_gate_latest.json"]),
    ("blob_publisher", "Dashboard Data Publisher", r"^MarketWiki independent data publisher", "delivery", "Builds, validates, publishes, and reads back the public snapshot", ["market-data/manifest.json"]),
)


def _shortlist_cron_jobs() -> list[dict[str, Any]]:
    path = CRON_ROOT / 'jobs.json'
    if not path.exists():
        return []
    try:
        raw = json.loads(read(path))
        jobs = raw.get('jobs', raw if isinstance(raw, list) else [])
        return [job for job in jobs if isinstance(job, dict)]
    except Exception:
        return []


def _job_schedule(job: dict[str, Any]) -> str:
    schedule = job.get('schedule')
    if isinstance(schedule, dict):
        return clean_inline(str(schedule.get('display') or schedule.get('expr') or schedule.get('run_at') or ''))[:80]
    return clean_inline(str(schedule or ''))[:80]


def _job_health(job: dict[str, Any] | None) -> str:
    if not job:
        return 'missing'
    if job.get('enabled', True) is not True:
        return 'inactive'
    status = str(job.get('last_status') or '').lower()
    if status == 'ok':
        return 'pass'
    if status in {'error', 'failed', 'timeout'}:
        return 'fail'
    return 'degraded'


def _publisher_job_health(job: dict[str, Any] | None) -> tuple[str, str]:
    """Return non-self-referential publisher health and no volatile timestamp.

    The publisher job's own ``last_run_at``/``next_run_at`` and durable-state
    timestamps change as a consequence of publishing. Projecting any of them
    into the snapshot makes each successful publish create another snapshot,
    causing needless manifest churn and CDN read-back races. The durable state
    is authoritative for health only; Slack remains the failure detail surface.
    """
    fallback = _job_health(job)
    if fallback in {'missing', 'inactive'}:
        return fallback, ''
    state_path = CRON_ROOT.parent / 'state' / 'market_dashboard_data_publish_state.json'
    try:
        state = json.loads(read(state_path))
    except Exception:
        return fallback, ''
    if not isinstance(state, dict):
        return fallback, ''
    if int(state.get('consecutiveFailures') or 0) > 0 or state.get('lastError'):
        return 'fail', ''
    if state.get('lastSuccessAt'):
        return 'pass', ''
    return fallback, ''


def build_shortlist_membership_workflow(data: dict[str, Any]) -> dict[str, Any]:
    jobs = _shortlist_cron_jobs()
    job_nodes: list[dict[str, Any]] = []
    for node_id, label, pattern, stage, detail, artifacts in SHORTLIST_JOB_SPECS:
        match = next((job for job in jobs if re.search(pattern, str(job.get('name') or ''), re.I)), None)
        status = _job_health(match)
        last_run_at = clean_inline(str((match or {}).get('last_run_at') or ''))[:80]
        next_run_at = clean_inline(str((match or {}).get('next_run_at') or ''))[:80]
        if node_id == 'blob_publisher':
            status, last_run_at = _publisher_job_health(match)
            next_run_at = ''
        job_nodes.append({
            'id': node_id,
            'label': label,
            'stage': stage,
            'kind': 'job',
            'status': status,
            'schedule': _job_schedule(match or {}),
            'lastRunAt': last_run_at,
            'nextRunAt': next_run_at,
            'detail': detail,
            'artifacts': artifacts,
        })
    summary = data.get('summary') if isinstance(data.get('summary'), dict) else {}
    row_count = int(summary.get('rowCount') or 0)
    snapshot_count = int(summary.get('researchSnapshots') or 0)
    research_degraded = int(summary.get('researchGateDegraded') or 0)
    research_failures = int(summary.get('researchGateFailures') or 0)
    research_status = 'fail' if not snapshot_count else 'degraded' if snapshot_count != row_count or research_degraded or research_failures else 'pass'
    entry_status = 'degraded' if int(summary.get('refreshRequired') or 0) or int(summary.get('missingEntryZone') or 0) else 'pass'
    portfolio_rows = [row for row in data.get('all', []) if isinstance(row, dict)]
    portfolio_fresh_count = sum(1 for row in portfolio_rows if row.get('portfolioFresh') is True)
    freshness_job = next((node for node in job_nodes if node['id'] == 'freshness_gate_job'), None)
    publisher_job = next((node for node in job_nodes if node['id'] == 'blob_publisher'), None)
    core_nodes = [
        {'id': 'research_snapshots', 'label': 'Ticker thesis + ResearchSnapshot', 'stage': 'dependencies', 'kind': 'dependency', 'status': research_status, 'schedule': 'On every shortlist build', 'lastRunAt': str(data.get('generatedAt') or ''), 'nextRunAt': '', 'detail': f'{snapshot_count}/{row_count} snapshots exist; research gates are {row_count - research_degraded - research_failures} pass, {research_degraded} degraded, {research_failures} fail. Promotion fails closed.', 'artifacts': ['tickers/*.md', 'data/automation/research_snapshots/*.json']},
        {'id': 'market_entry_state', 'label': 'Market + entry state', 'stage': 'dependencies', 'kind': 'dependency', 'status': entry_status, 'schedule': 'Weekdays + intraday', 'lastRunAt': str(data.get('generatedAt') or ''), 'nextRunAt': '', 'detail': f"Fresh quotes are required; {int(summary.get('missingEntryZone') or 0)} names lack a structured zone. Macro is decision context and does not auto-promote membership.", 'artifacts': ['data/automation/intraday_equity_watchdog.json', 'config/action_freshness_policy.json', 'data/automation/macro_regime_snapshot_latest.json']},
        {'id': 'membership_policy_write', 'label': 'Reviewed membership decision', 'stage': 'decision', 'kind': 'core', 'status': 'reviewed', 'schedule': 'On material change', 'lastRunAt': str(data.get('generatedAt') or ''), 'nextRunAt': 'event-driven', 'detail': 'No job auto-promotes from price or social signals. An agent or PM must underwrite the evidence and explicitly update the canonical list; automation may only fail closed.', 'artifacts': ['queries/current_asymmetric_shortlist.md']},
        {'id': 'portfolio_fit', 'label': 'Portfolio fit', 'stage': 'dependencies', 'kind': 'dependency', 'status': 'degraded', 'schedule': 'Manual refresh required', 'lastRunAt': str(data.get('generatedAt') or ''), 'nextRunAt': '', 'detail': f'{portfolio_fresh_count}/{row_count} rows currently read fresh, but no recurring job owns the main-portfolio broker-status artifact. It blocks sizing only and never changes portfolio-blind research.', 'artifacts': ['data/automation/main_portfolio_broker_access_status.json']},
        {'id': 'membership_gate', 'label': 'Deterministic eligibility gate', 'stage': 'gate', 'kind': 'gate', 'status': (freshness_job or {}).get('status', 'missing'), 'schedule': (freshness_job or {}).get('schedule', ''), 'lastRunAt': str(data.get('generatedAt') or ''), 'nextRunAt': (freshness_job or {}).get('nextRunAt', ''), 'detail': 'Validates reviewed membership and computes freshness, entry, and capital eligibility. It can force Wait but cannot promote a ticker by itself.', 'artifacts': ['_tools/current_shortlist_builder.py']},
        {'id': 'canonical_list', 'label': 'Canonical 23-name list', 'stage': 'output', 'kind': 'output', 'status': 'pass' if row_count else 'fail', 'schedule': 'After gate', 'lastRunAt': str(data.get('generatedAt') or ''), 'nextRunAt': '', 'detail': 'One live membership surface; tiers and action states remain separate axes.', 'artifacts': ['queries/current_asymmetric_shortlist.md', 'data/automation/current_asymmetric_shortlist_latest.json']},
        {'id': 'cio_page', 'label': 'CIO membership view', 'stage': 'delivery', 'kind': 'consumer', 'status': (publisher_job or {}).get('status', 'missing'), 'schedule': 'After validated Blob publish', 'lastRunAt': (publisher_job or {}).get('lastRunAt', ''), 'nextRunAt': (publisher_job or {}).get('nextRunAt', ''), 'detail': 'Shows run deltas, all members, bucket placement, and this dependency graph.', 'artifacts': ['CIO brief']},
    ]
    bucket_order = ((data.get('membershipPolicy') or {}).get('bucketOrder') if isinstance(data.get('membershipPolicy'), dict) else []) or [
        'Buy / Scout Now', 'Wait for Trigger', 'Add After Proof', 'Research Memory / Not Live Action', 'Kill / Do Not Average'
    ]
    bucket_nodes = [{
        'id': f"bucket_{index}", 'label': clean_inline(str(bucket))[:80], 'stage': 'buckets', 'kind': 'bucket', 'status': 'pass',
        'schedule': 'Assigned every build', 'lastRunAt': str(data.get('generatedAt') or ''), 'nextRunAt': '',
        'detail': f"{sum(1 for row in data.get('all', []) if isinstance(row, dict) and row.get('bucket') == bucket)} current members",
        'artifacts': [],
    } for index, bucket in enumerate(bucket_order)]
    edges: list[dict[str, str]] = []
    for node in job_nodes:
        if node['id'] in {'freshness_gate_job', 'integrity_watchdog', 'blob_publisher'}:
            continue
        target = 'research_snapshots' if node['stage'] in {'research', 'proof'} else 'portfolio_fit' if node['stage'] == 'portfolio' else 'market_entry_state' if node['stage'] == 'market' else 'membership_policy_write'
        edges.append({'from': node['id'], 'to': target, 'label': 'feeds'})
    edges.extend([
        {'from': 'research_snapshots', 'to': 'membership_policy_write', 'label': 'checked evidence'},
        {'from': 'market_entry_state', 'to': 'membership_gate', 'label': 'required'},
        {'from': 'portfolio_fit', 'to': 'membership_gate', 'label': 'implementation gate only'},
        {'from': 'membership_policy_write', 'to': 'membership_gate', 'label': 'reviewed bucket'},
        {'from': 'freshness_gate_job', 'to': 'membership_gate', 'label': 'runs'},
        {'from': 'membership_gate', 'to': 'canonical_list', 'label': 'assigns one bucket'},
    ])
    for node in bucket_nodes:
        edges.append({'from': 'canonical_list', 'to': node['id'], 'label': 'contains'})
        edges.append({'from': node['id'], 'to': 'integrity_watchdog', 'label': 'validated'})
    edges.extend([
        {'from': 'integrity_watchdog', 'to': 'blob_publisher', 'label': 'verified'},
        {'from': 'blob_publisher', 'to': 'cio_page', 'label': 'publishes'},
    ])
    nodes = job_nodes + core_nodes + bucket_nodes
    required_ids = {'research_snapshots', 'market_entry_state', 'portfolio_fit', 'weekly_deep_dive', 'graph_morning', 'price_watchdog', 'freshness_gate_job', 'integrity_watchdog', 'blob_publisher'}
    required_health = [node['status'] for node in nodes if node['id'] in required_ids]
    status = 'fail' if 'fail' in required_health or 'missing' in required_health or 'inactive' in required_health else 'degraded' if 'degraded' in required_health else 'pass'
    return {
        'generatedAt': clean_inline(str(data.get('generatedAt') or ''))[:80],
        'status': status,
        'coverageNote': 'Green means the scheduled dependency is enabled and its latest run passed. Optional signal jobs enrich evidence; they cannot promote a ticker by themselves.',
        'nodes': nodes,
        'edges': edges,
    }


def parse_current_asymmetric_shortlist() -> dict[str, Any] | None:
    """Load the single live shortlist artifact generated by wiki-market.

    This is public-safe by construction: sizing is labels only, account-scale
    fields are hidden, and source paths exclude private portfolio files.
    """
    path = WIKI / 'data/automation/current_asymmetric_shortlist_latest.json'
    if not path.exists():
        return None
    try:
        data = json.loads(read(path))
    except Exception:
        return None
    if any(data.get(k) not in (None, '', 'public', 'public_ok') for k in ('privacyClass', 'privacy_class')):
        return None
    rows = []
    for row in data.get('all', [])[:80]:
        if not isinstance(row, dict) or has_private_classification(row):
            continue
        latest_event = row.get('latestEvent') if isinstance(row.get('latestEvent'), dict) else {}
        bucket = row.get('bucket')
        rows.append({
            'symbol': clean_inline(str(row.get('symbol') or ''))[:16],
            # Validate before cleaning; malformed tokens must not become valid enums.
            'bucket': bucket if isinstance(bucket, str) and bucket in MEMBERSHIP_BUCKETS else UNAVAILABLE,
            'bucketReason': clean_inline(str(row.get('bucketReason') or ''))[:320],
            'rank': clean_inline(str(row.get('rank') or ''))[:16],
            'state': clean_inline(str(row.get('state') or ''))[:180],
            'upsideClass': clean_inline(str(row.get('upsideClass') or ''))[:100],
            'proofLevel': clean_inline(str(row.get('proofLevel') or ''))[:20],
            'entry': clean_inline(str(row.get('entry') or ''))[:260],
            'currentPrice': row.get('currentPrice'),
            'quoteAsOf': clean_inline(str(row.get('quoteAsOf') or ''))[:80],
            'entryZoneLow': row.get('entryZoneLow'),
            'entryZoneHigh': row.get('entryZoneHigh'),
            'entryZoneCurrency': clean_inline(str(row.get('entryZoneCurrency') or ''))[:12],
            'entryZoneAsOf': clean_inline(str(row.get('entryZoneAsOf') or ''))[:80],
            'entryStatus': clean_inline(str(row.get('entryStatus') or 'unknown'))[:40],
            'entryReason': clean_inline(str(row.get('entryReason') or ''))[:180],
            'entryEligible': row.get('entryEligible') is True,
            'proofTrigger': clean_inline(str(row.get('proofTrigger') or ''))[:260],
            'killTrigger': clean_inline(str(row.get('killTrigger') or ''))[:260],
            'whyNotNow': clean_inline(str(row.get('whyNotNow') or ''))[:220],
            'freshness': clean_inline(str(row.get('freshness') or 'unknown'))[:80],
            'freshnessReason': clean_inline(str(row.get('freshnessReason') or ''))[:160],
            'decisionExpiration': clean_inline(str(row.get('decisionExpiration') or ''))[:80],
            'tickerUpdated': clean_inline(str(row.get('tickerUpdated') or ''))[:40],
            'eventAgeDays': row.get('eventAgeDays'),
            'priceAgeDays': row.get('priceAgeDays'),
            'capitalEligible': row.get('capitalEligible') is True,
            'tier': clean_inline(str(row.get('tier') or ''))[:80],
            'researchTier': clean_inline(str(row.get('researchTier') or ''))[:40],
            'tierReviewed': clean_inline(str(row.get('tierReviewed') or ''))[:40],
            'tierReason': clean_inline(str(row.get('tierReason') or ''))[:320],
            'returnRole': clean_inline(str(row.get('returnRole') or 'watch_only'))[:80],
            'targetContribution': clean_inline(str(row.get('targetContribution') or ''))[:120],
            'timeToMatter': clean_inline(str(row.get('timeToMatter') or ''))[:80],
            'actionMode': clean_inline(str(row.get('actionMode') or 'Wait'))[:40],
            'whyThisHelps50to100': clean_inline(str(row.get('whyThisHelps50to100') or ''))[:260],
            'opportunityCost': clean_inline(str(row.get('opportunityCost') or ''))[:260],
            'capitalPriority': row.get('capitalPriority'),
            'latestEvent': {
                'kind': clean_inline(str(latest_event.get('kind') or ''))[:80],
                'sourcePath': clean_inline(str(latest_event.get('sourcePath') or ''))[:180],
                'generatedAt': clean_inline(str(latest_event.get('generatedAt') or ''))[:80],
                'summary': clean_inline(str(latest_event.get('summary') or ''))[:220],
            } if latest_event else None,
            'privateSizingHidden': True,
        })
    action_changes = []
    for event in data.get('actionChanges', [])[:12]:
        if not isinstance(event, dict):
            continue
        action_changes.append({
            'symbol': clean_inline(str(event.get('symbol') or ''))[:16],
            'changeType': clean_inline(str(event.get('changeType') or ''))[:80],
            'fromBucket': clean_inline(str(event.get('fromBucket') or ''))[:80],
            'toBucket': clean_inline(str(event.get('toBucket') or ''))[:80],
            'headline': clean_inline(str(event.get('headline') or ''))[:240],
            'action': clean_inline(str(event.get('action') or ''))[:80],
            'freshness': clean_inline(str(event.get('freshness') or ''))[:80],
            'returnRole': clean_inline(str(event.get('returnRole') or ''))[:80],
            'whyThisHelps50to100': clean_inline(str(event.get('whyThisHelps50to100') or ''))[:260],
            'opportunityCost': clean_inline(str(event.get('opportunityCost') or ''))[:260],
            'slackWorthy': bool(event.get('slackWorthy')),
            'generatedAt': clean_inline(str(event.get('generatedAt') or ''))[:80],
            'expiresAt': clean_inline(str(event.get('expiresAt') or ''))[:80],
        })
    membership_policy = data.get('membershipPolicy') if isinstance(data.get('membershipPolicy'), dict) else {}
    run_summary = data.get('runSummary') if isinstance(data.get('runSummary'), dict) else {}
    membership_changes = []
    for change in data.get('membershipChanges', [])[:80]:
        if not isinstance(change, dict):
            continue
        membership_changes.append({
            'symbol': clean_inline(str(change.get('symbol') or ''))[:16],
            'changeType': clean_inline(str(change.get('changeType') or ''))[:40],
            'fromBucket': clean_inline(str(change.get('fromBucket') or ''))[:80],
            'toBucket': clean_inline(str(change.get('toBucket') or ''))[:80],
            'fromAction': clean_inline(str(change.get('fromAction') or ''))[:40],
            'toAction': clean_inline(str(change.get('toAction') or ''))[:40],
            'fromFreshness': clean_inline(str(change.get('fromFreshness') or ''))[:40],
            'toFreshness': clean_inline(str(change.get('toFreshness') or ''))[:40],
            'changedFields': [clean_inline(str(field))[:40] for field in change.get('changedFields', [])[:10]],
        })
    workflow = build_shortlist_membership_workflow(data)
    automation_node = next((node for node in workflow['nodes'] if node['id'] == 'freshness_gate_job'), {})
    return {
        'generatedAt': clean_inline(str(data.get('generatedAt') or ''))[:80],
        'policy': clean_inline(str(data.get('policy') or ''))[:260],
        'summary': data.get('summary') if isinstance(data.get('summary'), dict) else {},
        'regime': data.get('regime') if isinstance(data.get('regime'), dict) else {},
        'actionChanges': action_changes,
        'membershipPolicy': {
            'bucketMode': membership_policy.get('bucketMode', 'mutually_exclusive'),
            'description': clean_inline(str(membership_policy.get('description') or 'Each ticker occupies exactly one bucket at a time.'))[:280],
            'bucketOrder': [bucket for bucket in membership_policy.get('bucketOrder', [])[:10]
                            if isinstance(bucket, str) and bucket in MEMBERSHIP_BUCKETS],
        },
        'runSummary': {
            'builder': clean_inline(str(run_summary.get('builder') or 'current_shortlist_builder'))[:80],
            'scheduledOwner': clean_inline(str(run_summary.get('scheduledOwner') or 'Market Wiki Freshness Gate'))[:100],
            'generatedAt': clean_inline(str(run_summary.get('generatedAt') or data.get('generatedAt') or ''))[:80],
            'previousGeneratedAt': clean_inline(str(run_summary.get('previousGeneratedAt') or ''))[:80],
            'status': clean_inline(str(run_summary.get('status') or 'unknown'))[:40],
            'rowCount': int(run_summary.get('rowCount') or len(rows)),
            'addedSymbols': [clean_inline(str(symbol))[:16] for symbol in run_summary.get('addedSymbols', [])[:80]],
            'removedSymbols': [clean_inline(str(symbol))[:16] for symbol in run_summary.get('removedSymbols', [])[:80]],
            'changedCount': int(run_summary.get('changedCount') or 0),
            'unchangedCount': int(run_summary.get('unchangedCount') or 0),
        },
        'membershipChanges': membership_changes,
        'automation': {
            'jobName': automation_node.get('label', 'Market Wiki Freshness Gate'),
            'schedule': automation_node.get('schedule', ''),
            'enabled': automation_node.get('status') not in {'missing', 'inactive'},
            'lastStatus': next((str(job.get('last_status') or '') for job in _shortlist_cron_jobs() if re.search(r'^Market Wiki Freshness Gate$', str(job.get('name') or ''), re.I)), ''),
            'lastRunAt': automation_node.get('lastRunAt', ''),
            'nextRunAt': automation_node.get('nextRunAt', ''),
            'health': automation_node.get('status', 'missing'),
        },
        'membershipWorkflow': workflow,
        'rows': rows,
        'decisionLearning': parse_decision_learning(),
    }


def scrub_strategy_privacy_phrases(text: str) -> str:
    """Do not rename private facts into apparently public analysis."""
    return clean_narrative(text, action_allowed=True, editorial_checks=False)


def read(path: Path) -> str:
    text = path.read_text(encoding='utf-8', errors='replace')
    # Retired annotation metadata must never enter ordinary brief narrative.
    # Keep this read-only quarantine for historical or restored source files.
    if path.parent == WIKI / 'daily' / 'briefs':
        text = re.sub(r'\n?<!-- conviction-change:v1 -->.*?<!-- /conviction-change -->\n?', '', text, flags=re.S)
        # Quarantine an unterminated appended annotation, stopping at the next
        # real Markdown heading so later original contributions remain intact.
        text = re.sub(r'\n?<!-- conviction-change:v1 -->.*?(?=^#{1,6}\s|\Z)', '', text, flags=re.S | re.M)
    return text


def scrub_private(text: str) -> str:
    """Contextual privacy only; preserve source action codes until public mapping.

    Parser/action classification behavior must not depend on editorial rewriting.
    The final shared public boundary handles ambiguous narrative and unknown labels.
    """
    if re.fullmatch(r'(?:data|queries|tickers|daily)/[^\s]+', text):
        return text
    return clean_narrative(text, action_allowed=True, editorial_checks=False)


def strip_utc_times(text: str) -> str:
    """Keep dashboard copy in market-local terms; Readers do not need UTC noise."""
    text = re.sub(r'\(~?\d{1,2}:\d{2}\s*UTC\s*/\s*([^)]*)\)', r'(\1)', text, flags=re.I)
    text = re.sub(r'~?\d{1,2}:\d{2}\s*UTC\s*/\s*', '', text, flags=re.I)
    text = re.sub(r'\b\d{1,2}:\d{2}\s*UTC\s*(?:/\s*)?', '', text, flags=re.I)
    text = re.sub(r'\s*\(\)\s*', ' ', text)
    text = re.sub(r'\s+:', ':', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def clean_inline(text: str) -> str:
    text = scrub_private(text)
    text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', lambda m: m.group(1).split('/')[-1].replace('.md', ''), text)
    text = re.sub(r'\^\[[^\]]+\]', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = scrub_private(text)
    text = strip_utc_times(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith('[') and raw.endswith(']'):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip('"\'') for x in inner.split(',')]
    return raw.strip('"\'')


def frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith('---'):
        return {}, text
    parts = text.split('---', 2)
    if len(parts) < 3:
        return {}, text
    fm: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if ':' not in line or line.startswith(' '):
            continue
        key, val = line.split(':', 1)
        fm[key.strip()] = parse_value(val)
    return fm, parts[2]


def heading_sections(body: str) -> list[dict[str, str]]:
    matches = list(re.finditer(r'^##\s+(.+?)\s*$', body, re.M))
    sections = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        title = clean_inline(m.group(1).strip())
        content = body[start:end].strip()
        if title and content:
            sections.append({'title': title, 'content': content})
    return sections


def section(body: str, heading: str) -> str:
    for sec in heading_sections(body):
        if sec['title'].lower().startswith(heading.lower()):
            return sec['content']
    return ''


def bullets(text: str, limit: int = 6, max_len: int = 300) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(('-', '*')):
            cleaned = clean_inline(re.sub(r'^[-*]\s+', '', s))
            if len(cleaned) > 12:
                out.append(cleaned[:max_len].rstrip() + ('…' if len(cleaned) > max_len else ''))
        if len(out) >= limit:
            break
    return out


def labeled_paragraphs(text: str, labels: list[str], limit: int = 6, max_len: int = 360) -> list[str]:
    """Extract bold markdown label paragraphs like **Action posture:** ..."""
    out: list[str] = []
    label_alt = '|'.join(re.escape(label) for label in labels)
    rx = re.compile(rf'^\*\*({label_alt}):\*\*\s*(.+)$', re.I)
    for line in text.splitlines():
        m = rx.match(line.strip())
        if not m:
            continue
        cleaned = clean_inline(f"{m.group(1)}: {m.group(2)}")
        if cleaned:
            out.append(cleaned[:max_len].rstrip() + ('…' if len(cleaned) > max_len else ''))
        if len(out) >= limit:
            break
    return out


def first_paragraph(text: str, max_len: int = 440) -> str:
    for block in re.split(r'\n\s*\n', text):
        block = block.strip()
        if (
            not block
            or block.startswith('|')
            or block.startswith('>')
            or block.startswith('#')
            or re.match(r'^(\*\*)?(Source trace|Sources checked|Links|Raw source|Wiki pages updated|Verification):', block, re.I)
        ):
            continue
        cleaned = '; '.join(bullets(block, limit=3, max_len=max_len)) if block.startswith(('-', '*')) else clean_inline(block)
        if len(cleaned) > 24:
            return cleaned[:max_len].rstrip() + ('…' if len(cleaned) > max_len else '')
    return ''


def daily_lead_summary(body: str, max_len: int = 620) -> str:
    """Prefer the canonical daily brief's synthesis over incidental first sections."""
    secs = heading_sections(body)
    preferred = [
        'TL;DR / What Changed', 'What Changed', 'Executive Verdict', 'Market Setup',
        'Morning Market Briefing', 'Canonical Daily Market Update',
        # Append-only daily job briefs still carry the PM-relevant synthesis when a
        # full morning brief has not been written yet.
        'Action posture', 'Macro / exposure context', 'X signal read', 'Convergence', 'Result',
    ]
    for needle in preferred:
        for sec in secs:
            if needle.lower() in sec['title'].lower():
                bs = bullets(sec['content'], 3, 260)
                if bs:
                    joined = ' '.join(clean_inline(b) for b in bs)
                    return joined[:max_len].rstrip() + ('…' if len(joined) > max_len else '')
                para = first_paragraph(sec['content'], max_len)
                if para:
                    return para
    labeled = labeled_paragraphs(body, ['Action posture', 'Macro / exposure context', 'Tape / macro', 'X signal read', 'Convergence', 'Result'], limit=3, max_len=260)
    if labeled:
        joined = ' '.join(labeled)
        return joined[:max_len].rstrip() + ('…' if len(joined) > max_len else '')
    return first_paragraph(body, max_len)


def compact_markdown(text: str, max_len: int = 3000) -> str:
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('---') or s.startswith('|'):
            continue
        if s.startswith('#'):
            s = re.sub(r'^#+\s*', '', s)
        s = clean_inline(s)
        if s:
            lines.append(s)
    joined = '\n'.join(lines)
    return joined[:max_len].rstrip() + ('…' if len(joined) > max_len else '')


def extract_status(text: str) -> str:
    for pat in [r'\*\*Action:\*\*\s*([^\n]+)', r'\*\*House call:\*\*\s*([^\n]+)', r'\*\*Classification:\*\*\s*([^\n]+)', r'\b(BUY|HOLD|WAIT|AVOID|CATALYST WATCH|RADAR ONLY|NO CHASE|DO NOT ADD)[^\n]{0,140}']:
        m = re.search(pat, text, re.I)
        if m:
            return clean_inline(m.group(1) if m.lastindex else m.group(0))[:220]
    return ''


def labeled_value(text: str, *labels: str, max_len: int = 420) -> str:
    """Extract a bold markdown label from a bullet/paragraph without leaking markup."""
    for label in labels:
        pattern = rf'^\s*(?:[-*]\s*)?\*\*{re.escape(label)}:\*\*\s*(.+?)\s*$'
        match = re.search(pattern, text, re.I | re.M)
        if match:
            return clean_inline(match.group(1))[:max_len]
    return ''


def company_description(body: str) -> str:
    """Return a factual company description, never the investment thesis by default."""
    for heading in ('What It Is', 'Company Overview', 'Business Overview', 'Overview', 'Business'):
        description = first_paragraph(section(body, heading))
        if description:
            return description
    return ''


def freshest_war_room_section(sections: list[dict[str, str]]) -> dict[str, str] | None:
    """Return the newest dated War Room section, independent of document order."""
    candidates: list[tuple[bool, str, int, dict[str, str]]] = []
    for index, sec in enumerate(sections):
        if 'war room' not in sec['title'].lower():
            continue
        match = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', sec['title'])
        candidates.append((bool(match), match.group(1) if match else '', index, sec))
    return max(candidates, key=lambda row: row[:3])[3] if candidates else None


def war_room_overrides(body: str) -> dict[str, str]:
    """Promote the freshest War Room action/gates into the dashboard decision fields."""
    freshest = freshest_war_room_section(heading_sections(body))
    if not freshest:
        return {}
    war_room = freshest['content']
    action = labeled_value(war_room, 'Action', 'House call') or extract_status(war_room)
    entry = labeled_value(war_room, 'Scout / dislocation', 'Scout', 'Starter / add / kill', 'Entry')
    trigger = labeled_value(war_room, 'Proof-add', 'Proof trigger', 'Add trigger')
    risk = labeled_value(war_room, 'Thesis kill', 'Kill / reassess', 'Kill trigger')
    return {key: value for key, value in {
        'shortlistRec': action,
        'shortlistStatus': action,
        'entryPoint': entry,
        'trigger': trigger,
        'shortlistRisk': risk,
    }.items() if value}


def ticker_detail_sections(
    sections: list[dict[str, str]],
    preferred_sections: list[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Build ticker detail cards while guaranteeing the freshest War Room is visible.

    Ticker pages can contain many older preferred sections before a newly appended War
    Room.  Reserving the first slot for the newest dated War Room prevents the detail-card
    cap from hiding the same decision section that supplies the promoted action fields.
    Older War Rooms are deliberately omitted.
    """
    freshest = freshest_war_room_section(sections)
    ordered = ([freshest] if freshest else []) + [sec for sec in sections if sec is not freshest]
    selected: list[dict[str, Any]] = []
    for sec in ordered:
        is_war_room = 'war room' in sec['title'].lower()
        title_lower = sec['title'].lower()
        if is_war_room and sec is not freshest:
            continue
        # A current War Room owns the live decision surface. Older generic
        # Forward Signal / Action sections may contain superseded portfolio,
        # tax, or sizing implementation notes and must not reach the dashboard.
        if freshest is not None and sec is not freshest and (
            'forward signal' in title_lower or title_lower.startswith('action')
        ):
            continue
        if is_war_room or any(
            sec['title'].lower().startswith(preferred.lower())
            or preferred.lower() in sec['title'].lower()
            for preferred in preferred_sections
        ):
            selected.append({
                'title': sec['title'],
                'summary': compact_markdown(sec['content'], 1000),
                'bullets': bullets(sec['content'], 5, 260),
            })
        if len(selected) >= limit:
            break
    return selected


def ticker_full_summary(body: str, selected_sections: list[dict[str, Any]]) -> str:
    """Build the public fallback summary from current detail sections only.

    Ticker pages are append-only research ledgers and may contain superseded portfolio,
    tax, or sizing notes. When current detail cards exist, do not republish the entire
    historical body into the public snapshot's fallback field.
    """
    if not selected_sections:
        return compact_markdown(body, 4600)
    lines: list[str] = []
    for sec in selected_sections:
        title = clean_inline(str(sec.get('title') or ''))
        summary = str(sec.get('summary') or '').strip()
        if title:
            lines.append(title)
        if summary:
            lines.append(summary)
    joined = '\n'.join(lines)
    return joined[:4600].rstrip() + ('…' if len(joined) > 4600 else '')


def action_bucket(text: str) -> str:
    upper = text.upper()
    if re.search(r'\b(REMOVED|AVOID|TRIM|SELL)\b', upper):
        return 'avoid_trim'
    if re.search(r'\b(CORE HOLD|HOLD|KEEP)\b', upper):
        return 'hold'
    if re.search(r'\b(NO CHASE|DO NOT ADD|WAIT|WATCH|RADAR|CATALYST|PULLBACK)\b', upper):
        return 'wait_watch'
    if re.search(r'\b(BUY|ADD|STARTER|ACCUMULATE)\b', upper):
        return 'buy_add'
    return 'unclassified'


def table_cells(line: str) -> list[str]:
    return [clean_inline(c.strip()) for c in line.strip('|').split('|')]


def parse_shortlist() -> dict[str, dict[str, str]]:
    path = WIKI / 'conviction-shortlist.md'
    if not path.exists():
        return {}
    mapped: dict[str, dict[str, str]] = {}
    group = 'Core / strategic'
    header: list[str] = []
    rank = 0
    for line in read(path).splitlines():
        if line.startswith('##') and 'watchlist' in line.lower():
            group = 'Watchlist'
        if not line.startswith('|') or re.match(r'^\|[-: ]+\|', line):
            continue
        cells = table_cells(line)
        if len(cells) < 3:
            continue
        if 'Ticker' in cells[0]:
            header = [c.lower() for c in cells]
            continue
        m = re.search(r'\$?([A-Z][A-Z0-9]{1,7})', cells[0])
        if not m:
            continue
        rank += 1
        sym = m.group(1)

        def by_name(*names: str) -> str:
            for name in names:
                for i, h in enumerate(header):
                    if name in h and i < len(cells):
                        return cells[i]
            return ''

        if group == 'Watchlist':
            rec = by_name('status')
            thesis = by_name('why')
            entry = by_name('price')
            trigger = by_name('catalyst')
            risk = by_name('risk')
            status = rec
        else:
            rec = by_name('rec') or (cells[1] if len(cells) > 1 else '')
            thesis = by_name('thesis') or (cells[2] if len(cells) > 2 else '')
            entry = by_name('entry') or (cells[3] if len(cells) > 3 else '')
            trigger = by_name('trigger') or (cells[4] if len(cells) > 4 else '')
            risk = by_name('risk')
            status = by_name('status') or (cells[6] if len(cells) > 6 else '')
        mapped[sym] = {'shortlistGroup': group, 'shortlistRank': str(rank), 'shortlistRec': rec, 'shortlistThesis': thesis, 'entryPoint': entry, 'trigger': trigger, 'shortlistRisk': risk, 'shortlistStatus': status}
    return mapped


def infer_category(tags: list[str], text: str) -> str:
    tagset = {t.lower() for t in tags}
    blob = ' '.join(tags).lower() + ' ' + text.lower()
    # Prefer explicit wiki tags; body text often mentions adjacent themes/risk factors.
    if tagset & {'energy', 'ai-power'}:
        return 'AI power / energy'
    if tagset & {'photonics', 'optical'}:
        return 'CPO / photonics'
    if tagset & {'neocloud'}:
        return 'Neocloud / AI infrastructure'
    if tagset & {'semiconductor', 'semiconductor-test'}:
        return 'Semis / AI hardware'
    if tagset & {'fintech'}:
        return 'Fintech / crypto'
    if tagset & {'software', 'saas', 'enterprise'}:
        return 'Software / AI apps'
    if tagset & {'robotics', 'physical-ai', 'sensors', 'industrial-automation'}:
        return 'Robotics / physical AI'
    if tagset & {'space', 'defense'}:
        return 'Space / defense'
    if tagset & {'etf', 'macro'}:
        return 'Macro / ETFs'
    if re.search(r'\b(nuclear|800v|datacenter power|ppa|power demand)\b', blob):
        return 'AI power / energy'
    if re.search(r'\b(cpo|inp|transceiver|silicon photonics)\b', blob):
        return 'CPO / photonics'
    if re.search(r'\b(neocloud|gpu cloud|ai cloud)\b', blob):
        return 'Neocloud / AI infrastructure'
    if re.search(r'\b(hbm|memory|advanced-packaging|metrology|wafer|chiplet)\b', blob):
        return 'Semis / AI hardware'
    if re.search(r'\b(fintech|crypto|brokerage)\b', blob):
        return 'Fintech / crypto'
    if re.search(r'\b(cybersecurity|software|saas|arr|cloud app)\b', blob):
        return 'Software / AI apps'
    if re.search(r'\b(space|defense|uas|satellite|nato)\b', blob):
        return 'Space / defense'
    return 'Other research'


def extract_exchange(body: str) -> str:
    """Return a TradingView-friendly exchange prefix from explicit ticker-note metadata."""
    m = re.search(r'^\s*(?:\*\*)?Exchange(?:\*\*)?\s*:\s*([^\n]+)', body, re.I | re.M)
    if not m:
        return ''
    raw = m.group(1)
    if re.search(r'\b(Stockholm|Nasdaq Stockholm)\b', raw, re.I):
        return 'OMXSTO'
    if re.search(r'\b(NASDAQ|Nasdaq)\b', raw, re.I):
        return 'NASDAQ'
    if re.search(r'\b(NYSE\s*American|NYSEAMERICAN|NYSEArca|AMEX)\b', raw, re.I):
        return 'AMEX'
    if re.search(r'\bNYSE\b', raw, re.I):
        return 'NYSE'
    if re.search(r'\b(OTC|OTCQX|OTCQB|Pink)\b', raw, re.I):
        return 'OTC'
    if re.search(r'\b(Taiwan Stock Exchange|TWSE)\b', raw, re.I):
        return 'TWSE'
    if re.search(r'\b(Taipei Exchange|TPEX)\b', raw, re.I):
        return 'TPEX'
    if re.search(r'\b(XETRA|Deutsche B[oö]rse)\b', raw, re.I):
        return 'XETR'
    if re.search(r'\b(Euronext|Paris)\b', raw, re.I):
        return 'EURONEXT'
    if re.search(r'\b(London|LSE)\b', raw, re.I):
        return 'LSE'
    if re.search(r'\b(TSX Venture|TSXV)\b', raw, re.I):
        return 'TSXV'
    if re.search(r'\b(Toronto|TSX)\b', raw, re.I):
        return 'TSX'
    return ''


YAHOO_TO_TRADINGVIEW_EXCHANGE = {
    'NYQ': 'NYSE', 'NYS': 'NYSE',
    'NMS': 'NASDAQ', 'NGM': 'NASDAQ', 'NCM': 'NASDAQ', 'NAS': 'NASDAQ',
    'PCX': 'AMEX', 'ASE': 'AMEX',
    'OQX': 'OTC', 'OQB': 'OTC', 'PNK': 'OTC', 'OBB': 'OTC',
    'TAI': 'TWSE', 'TWO': 'TPEX',
    'GER': 'XETR', 'FRA': 'FWB',
    'PAR': 'EURONEXT', 'AMS': 'EURONEXT', 'BRU': 'EURONEXT', 'LIS': 'EURONEXT',
    'STO': 'OMXSTO', 'LSE': 'LSE', 'TOR': 'TSX', 'VAN': 'TSXV', 'MIL': 'MIL',
}


def tradingview_symbol_part(yahoo_symbol: str) -> str:
    """Convert a Yahoo Finance symbol into the symbol part TradingView expects."""
    symbol = yahoo_symbol.upper().replace('-', '.')
    # Yahoo encodes country exchanges as suffixes; TradingView uses the exchange prefix instead.
    return re.sub(r'\.(TW|TWO|DE|F|PA|AS|BR|LS|ST|L|TO|V|MI)$', '', symbol)


def yahoo_queries(symbol: str) -> list[str]:
    clean = symbol.upper()
    queries = [clean]
    if re.fullmatch(r'\d{4}TW', clean):
        queries.insert(0, f'{clean[:4]}.TW')
    if re.fullmatch(r'\d{4}TWO', clean):
        queries.insert(0, f'{clean[:4]}.TWO')
    return list(dict.fromkeys(queries))


def load_tradingview_cache() -> dict[str, Any]:
    try:
        return json.loads(TRADINGVIEW_CACHE.read_text())
    except Exception:
        return {}


def save_tradingview_cache(cache: dict[str, Any]) -> None:
    if OFFLINE:
        return
    TRADINGVIEW_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TRADINGVIEW_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True))


def yahoo_resolve_tradingview_symbol(symbol: str, cache: dict[str, Any]) -> dict[str, str]:
    """Best-effort generic resolver for tickers that lack exchange metadata in wiki notes.

    Uses Yahoo Finance's public search endpoint during static-data generation, then caches
    the TradingView prefix:symbol result so dashboard builds do not depend on repeated lookups.
    If lookup fails, callers fall back to explicit exchange metadata or React's small override map.
    """
    clean = symbol.upper()
    cached = cache.get(clean)
    if isinstance(cached, dict):
        return {k: str(v) for k, v in cached.items() if v}
    if OFFLINE:
        return {}
    for query in yahoo_queries(clean):
        url = 'https://query1.finance.yahoo.com/v1/finance/search?' + urllib.parse.urlencode({'q': query, 'quotesCount': 8, 'newsCount': 0})
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            data = json.loads(urllib.request.urlopen(req, timeout=3).read().decode('utf-8', errors='replace'))
        except Exception:
            continue
        wanted = clean.replace('-', '.')
        for row in data.get('quotes', []):
            quote_type = str(row.get('quoteType') or '').upper()
            if quote_type not in {'EQUITY', 'ETF'}:
                continue
            yahoo_symbol = str(row.get('symbol') or '').upper()
            base = tradingview_symbol_part(yahoo_symbol)
            # Prefer exact symbol/base matches. This avoids mapping ambiguous names like ART to AIP/ARTY.
            if yahoo_symbol.replace('-', '.') != query.upper().replace('-', '.') and base != wanted:
                continue
            tv_exchange = YAHOO_TO_TRADINGVIEW_EXCHANGE.get(str(row.get('exchange') or '').upper())
            if not tv_exchange:
                continue
            resolved = {'exchange': tv_exchange, 'tradingViewSymbol': f'{tv_exchange}:{base}|1D'}
            cache[clean] = resolved
            return resolved
    cache.setdefault(clean, {})
    return {}


def fallback_tradingview_symbol(symbol: str, exchange: str) -> str:
    if not exchange:
        return ''
    base = symbol.upper()
    if exchange in {'TWSE', 'TPEX'} and re.fullmatch(r'\d{4}TW|\d{4}TWO', base):
        base = base[:4]
    return f'{exchange}:{base}|1D'


def resolve_chart_symbol(symbol: str, body: str, cache: dict[str, Any]) -> dict[str, str]:
    exchange = extract_exchange(body)
    yahoo = yahoo_resolve_tradingview_symbol(symbol, cache) if not exchange else {}
    tv_symbol = yahoo.get('tradingViewSymbol') or fallback_tradingview_symbol(symbol, exchange)
    return {'exchange': yahoo.get('exchange') or exchange, 'tradingViewSymbol': tv_symbol}


def parse_tickers() -> list[dict[str, Any]]:
    shortlist = parse_shortlist()
    tradingview_cache = load_tradingview_cache()
    tickers = []
    preferred_sections = ['Thesis', 'Forward Signal', 'War Room', 'Catalysts', 'Financials', 'Risk', 'Risks', 'Kill', 'Action', 'Analyst Coverage']
    for path in sorted((WIKI / 'tickers').glob('*.md')):
        rel = str(path.relative_to(WIKI))
        if any(part in rel.lower() for part in PRIVATE_PATH_PARTS):
            continue
        text = read(path)
        fm, body = frontmatter(text)
        if fm.get('privacy_class', fm.get('privacyClass')) not in (None, '', 'public', 'public_ok'):
            continue
        body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
        symbol = path.stem
        secs = heading_sections(body)
        thesis = section(body, 'Thesis')
        catalysts = section(body, 'Catalysts')
        risks = section(body, 'Risks') or section(body, 'Risk') or section(body, 'Key Risks')
        selected = ticker_detail_sections(secs, preferred_sections, limit=8)
        thesis_summary = first_paragraph(thesis)
        summary = company_description(body) or first_paragraph(body)
        decision_fields = dict(shortlist.get(symbol, {}))
        decision_fields.update(war_room_overrides(body))
        status_parts: list[str] = []
        for value in (extract_status(body), decision_fields.get('shortlistRec', ''), decision_fields.get('shortlistStatus', '')):
            if value and value not in status_parts:
                status_parts.append(value)
        status_blob = ' '.join(status_parts)
        tags = fm.get('tags') if isinstance(fm.get('tags'), list) else []
        chart_symbol = resolve_chart_symbol(symbol, body, tradingview_cache)
        item: dict[str, Any] = {
            'symbol': symbol, 'title': str(fm.get('title') or symbol), 'created': str(fm.get('created') or ''), 'updated': str(fm.get('updated') or ''), 'tags': tags,
            '_sourceUrls': sorted({url.rstrip('.,;') for url in re.findall(r'https?://[^\s<>\]\)]+', body) if safe_url(url.rstrip('.,;'))}),
            '_publicSections': [sec for sec in secs if sec['title'] in {x['title'] for x in selected}],
            'researchTier': clean_inline(str(fm.get('research_tier') or ''))[:40], 'tierReviewed': clean_inline(str(fm.get('tier_reviewed') or ''))[:40], 'tierReason': clean_inline(str(fm.get('tier_reason') or ''))[:320],
            'sourcePath': rel, 'summary': summary, 'thesis': thesis_summary, 'status': clean_inline(status_blob)[:260], 'actionBucket': action_bucket(status_blob + ' ' + thesis_summary),
            'isStub': bool(re.search(r'\(stub\)|Stub created|RADAR ONLY', body[:1600], re.I)) or len(body) < 700,
            'catalyst': first_paragraph(catalysts, 280), 'risk': first_paragraph(risks, 280), 'detailSections': selected, 'fullSummary': ticker_full_summary(body, selected),
            'category': infer_category(tags, body + ' ' + summary), **chart_symbol,
        }
        item.update(decision_fields)
        tickers.append(item)
    save_tradingview_cache(tradingview_cache)
    return tickers


def latest_report_files(prefix: str) -> list[Path]:
    """Find latest posture artifacts, preferring fresh TraderMonty raw outputs over stale legacy reports."""
    candidates: list[Path] = []
    candidates.extend((WIKI / 'raw' / 'briefings' / 'tradermonty').glob(f'**/{prefix}_*.json'))
    candidates.extend((WIKI / 'reports').glob(f'{prefix}_*.json'))
    candidates = [p for p in candidates if not p.name.endswith('_history.json')]
    return sorted(candidates, key=lambda p: (file_date(p), p.stat().st_mtime), reverse=True)


def latest_json(prefix: str) -> dict[str, Any] | None:
    files = latest_report_files(prefix)
    if not files:
        return None
    return {'sourcePath': str(files[0].relative_to(WIKI)), 'data': json.loads(read(files[0])), 'artifactDate': file_date(files[0])}


def load_intraday_equity_watchdog() -> dict[str, Any] | None:
    """Load the consolidated conviction+pullback tripwire feed for the CIO brief."""
    path = WIKI / 'data' / 'automation' / 'intraday_equity_watchdog.json'
    if not path.exists():
        return None
    try:
        payload = json.loads(read(path))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    # Public-safe shaping: keep prices/technicals and source wiki paths, but cap text-heavy rows.
    def clean_hit(row: Any) -> dict[str, Any] | None:
        if not isinstance(row, dict):
            return None
        return {
            'symbol': clean_inline(str(row.get('symbol') or '')),
            'action': clean_inline(str(row.get('action') or '')),
            'trigger': clean_inline(str(row.get('trigger') or '')),
            'price': row.get('price'),
            'pct_today': row.get('pct_today'),
            'wiki_level': row.get('wiki_level'),
            'technical_quality': clean_inline(str(row.get('technical_quality') or '')),
            'technical_note': clean_inline(str(row.get('technical_note') or ''))[:220],
            'bucket': clean_inline(str(row.get('bucket') or '')),
            'source_lists': [clean_inline(str(x)) for x in (row.get('source_lists') or [])[:4]],
            'context': clean_inline(str(row.get('context') or ''))[:260],
            'text': clean_inline(str(row.get('text') or ''))[:420],
        }
    monitored = [m for m in payload.get('monitored', []) if isinstance(m, dict)]
    return {
        'last_check_utc': clean_inline(str(payload.get('last_check_utc') or '')),
        'monitored_count': int(payload.get('monitored_count') or len(monitored) or 0),
        'dashboard_hit_count': int(payload.get('dashboard_hit_count') or len(payload.get('top_hits') or []) or 0),
        'review_candidate_count': int(payload.get('review_candidate_count') or len(payload.get('review_candidates') or []) or 0),
        'slack_policy': clean_inline(str(payload.get('slack_policy') or '')),
        'summary': clean_inline(str(payload.get('summary') or ''))[:360],
        'sources': [clean_inline(str(x)) for x in (payload.get('sources') or [])[:4]],
        'monitored_symbols': [clean_inline(str(m.get('symbol') or '')) for m in monitored[:80] if m.get('symbol')],
        'top_hits': [h for h in (clean_hit(x) for x in (payload.get('top_hits') or [])[:12]) if h],
        'review_candidates': [h for h in (clean_hit(x) for x in (payload.get('review_candidates') or [])[:8]) if h],
        'sourcePath': str(path.relative_to(WIKI)),
    }


def report_score_entry(prefix: str, path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(read(path))
    except Exception:
        return None
    comp = data.get('composite', {}) if isinstance(data.get('composite'), dict) else {}
    score = comp.get('composite_score') or data.get('composite_score')
    if score is None:
        return None
    zone = comp.get('zone') or data.get('bias') or data.get('participation') or ''
    return {'date': file_date(path), 'score': round(float(score), 1), 'zone': str(zone), 'sourcePath': str(path.relative_to(WIKI))}


def report_score_history(prefix: str, days: int = 10) -> list[dict[str, Any]]:
    files = latest_report_files(prefix)
    by_date: dict[str, dict[str, Any]] = {}
    for path in files:
        date = file_date(path)
        if not date or date in by_date:
            continue
        entry = report_score_entry(prefix, path)
        if entry:
            by_date[date] = entry
        if len(by_date) >= days:
            break
    return list(reversed(list(by_date.values())))


def score_delta(history: list[dict[str, Any]]) -> float | None:
    if len(history) < 2:
        return None
    return round(float(history[-1]['score']) - float(history[-2]['score']), 1)


def freshness_status(artifact_date: str, data: dict[str, Any] | None = None) -> str:
    if not artifact_date:
        return 'missing'
    try:
        d = date.fromisoformat(artifact_date)
        age = (datetime.now(timezone.utc).date() - d).days
    except Exception:
        age = 999
    meta = data.get('metadata', {}) if isinstance(data, dict) and isinstance(data.get('metadata'), dict) else {}
    dq = meta.get('data_freshness') if isinstance(meta.get('data_freshness'), dict) else {}
    if dq and dq.get('is_fresh') is False:
        return 'degraded'
    if age <= 3:
        return 'fresh'
    if age <= 7:
        return 'stale'
    return 'stale'


def with_freshness(card: dict[str, Any], payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    artifact_date = payload.get('artifactDate') or file_date(Path(str(payload.get('sourcePath', ''))))
    card['artifactDate'] = artifact_date
    card['freshnessStatus'] = freshness_status(str(artifact_date or ''), data)
    card['generatedAt'] = clean_inline(str((data.get('metadata') or {}).get('generated_at') or data.get('generated_at') or '')) if isinstance(data, dict) else ''
    return card


def plain_report(name: str, payload: dict[str, Any] | None, history: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if not payload:
        return None
    data = payload['data']
    comp = data.get('composite', {}) if isinstance(data, dict) else {}
    regime = data.get('regime', {}) if isinstance(data, dict) else {}
    score = comp.get('composite_score') or data.get('composite_score')
    history = history or []
    delta = score_delta(history)
    if name == 'Market Breadth':
        zone = comp.get('zone', 'Unknown')
        weak = comp.get('weakest_health') or comp.get('weakest_signal') or {}
        strong = comp.get('strongest_health') or comp.get('strongest_signal') or {}
        return with_freshness({
            'name': 'Market health', 'sourcePath': payload['sourcePath'], 'score': score, 'zone': zone,
            'history': history, 'delta': delta,
            'plainTitle': f'{zone} market: selective, not all-clear',
            'plainEnglish': 'Breadth asks: is the rally broad, or are only a few leaders carrying the tape? Today it says participation is mixed, so new buys need company-specific proof instead of broad beta chasing.',
            'watch': [f"Pressure point: {weak.get('label', 'weak participation')} scored {weak.get('score', 'low')}.", f"Supportive point: {strong.get('label', 'best area')} scored {strong.get('score', 'higher')}.", 'Translation: keep winners, but size new ideas smaller unless the individual setup is exceptional.'],
        }, payload, data)
    if name == 'Macro Regime':
        label = regime.get('regime_label') or comp.get('zone') or 'Regime shift'
        evidence = [clean_inline(e.get('signal', '')) for e in (regime.get('evidence') or [])[:3] if e.get('signal')]
        return with_freshness({
            'name': 'Macro backdrop', 'sourcePath': payload['sourcePath'], 'score': score, 'zone': label,
            'history': history, 'delta': delta,
            'plainTitle': f'{label}: the backdrop is changing',
            'plainEnglish': 'Macro regime asks: what kind of market are we in — risk-on growth, defensive, inflationary, or transition? Current read says we are in transition, so leadership can rotate quickly.',
            'watch': evidence or ['Watch rates, credit, small caps, equal-weight indexes, and sector rotation for confirmation.'],
        }, payload, data)
    if name == 'Exposure Posture':
        return with_freshness({
            'name': 'Portfolio posture', 'sourcePath': payload['sourcePath'], 'score': data.get('composite_score'), 'zone': f"{data.get('bias', 'Neutral')} / {data.get('participation', 'narrow')}",
            'history': history, 'delta': delta,
            'plainTitle': f"New buys allowed, but cap total aggression around {data.get('exposure_ceiling_pct', 'n/a')}%",
            'plainEnglish': 'This is the dashboard\'s practical risk-control answer: how aggressive should we be today? Because participation is narrow, it says you can buy proof-backed names, but should avoid spraying capital across weak/noisy setups.',
            'watch': [data.get('rationale', ''), f"Confidence: {data.get('confidence', 'unknown')}. Missing inputs: {', '.join(data.get('inputs_missing', [])[:4]) or 'none'}."]
        }, payload, data)
    if name == 'Position Sizer':
        params = data.get('parameters', {})
        risk = data.get('final_risk_dollars', 0)
        return {
            'name': 'Position sizing rule', 'sourcePath': payload['sourcePath'], 'score': None, 'zone': 'Per-trade risk control',
            'plainTitle': 'Use this only after choosing a specific ticker + stop',
            'plainEnglish': 'Position sizing is not a market forecast. It answers: if I buy this stock and my stop is wrong, how much money am I willing to lose? The latest run is just an example calculation, not a recommendation to buy that ticker.',
            'watch': [f"Example: entry ${params.get('entry_price', 'n/a')}, stop ${params.get('stop_price', 'n/a')}, risk budget {params.get('risk_pct', 'n/a')}% of account.", f"That produced about ${risk:,.0f} of risk. For the command center, the more useful rule is: scouts tiny before proof, press only after proof, cut failed scouts fast."],
        }
    return None


def file_date(path: Path) -> str:
    text = path.name + ' ' + str(path)
    m = re.search(r'20\d{2}-\d{2}-\d{2}', text)
    return m.group(0) if m else ''


def latest_daily_paths(days: int = 14) -> list[Path]:
    """Return all daily markdown files for the most recent dates, sorted by date not mtime.

    The dashboard is a daily journal. Sorting by modified-time caused older source
    files from a date to crowd out the actual Daily Research Brief for that same
    date, which made some days look like a one-source media/transcript dump.
    """
    folders = [
        WIKI / 'daily', WIKI / 'daily' / 'briefs', WIKI / 'daily' / 'feeds',
        WIKI / 'daily' / 'macro_transcripts', WIKI / 'daily' / 'market_media', WIKI / 'daily' / 'podcasts',
        WIKI / 'daily' / 'deep_dives', WIKI / 'daily' / 'prices',
    ]
    files: list[Path] = []
    seen: set[Path] = set()
    for folder in folders:
        if folder.exists():
            for f in folder.glob('*.md'):
                if f not in seen and file_date(f):
                    seen.add(f)
                    files.append(f)
    recent_dates = sorted({file_date(f) for f in files if file_date(f)}, reverse=True)[:days]
    date_rank = {d: i for i, d in enumerate(recent_dates)}

    def priority(path: Path) -> tuple[int, int, str]:
        name = path.name.lower()
        rel = str(path.relative_to(WIKI)).lower()
        if re.fullmatch(r'20\d{2}-\d{2}-\d{2}\.md', name) and '/briefs/' in '/' + rel:
            kind = 0  # canonical daily research brief first
        elif 'earnings_preview' in name:
            kind = 1
        elif 'x_signals' in name or 'x_referral' in name:
            kind = 2
        elif 'deep_dives' in rel:
            kind = 3
        elif 'macro_transcripts' in rel:
            kind = 4
        elif 'market_media' in rel:
            kind = 5
        elif 'podcasts' in rel:
            kind = 6
        elif 'feeds' in rel:
            kind = 7
        else:
            kind = 8
        return (date_rank.get(file_date(path), 999), kind, str(path))

    return sorted([f for f in files if file_date(f) in date_rank], key=priority)


def readable_title(item: dict[str, Any]) -> str:
    title = clean_inline(str(item.get('title') or ''))
    if re.search(r'Daily Research Brief', title, re.I):
        return 'Daily research brief'
    return title


def extract_signed_pct(text: str, symbol: str | None = None) -> float | None:
    """Find a nearby signed percent move for a ticker/watch item when available."""
    hay = clean_inline(text)
    windows = [hay]
    if symbol:
        for m in re.finditer(rf'\$?{re.escape(symbol)}\b', hay):
            windows.insert(0, hay[max(0, m.start() - 60): m.end() + 90])
    for window in windows:
        m = re.search(r'(?<![\d%])([+-]\d+(?:\.\d+)?)\s*%', window)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def market_move_payload(text: str, symbol: str | None = None) -> dict[str, Any]:
    pct = extract_signed_pct(text, symbol)
    if pct is None:
        return {'changePct': None, 'direction': 'flat'}
    return {'changePct': pct, 'direction': 'up' if pct > 0 else 'down' if pct < 0 else 'flat'}


def ticker_mentions(lines: list[str], focus_symbols: set[str], research_symbols: set[str] | None = None) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    example: dict[str, str] = {}
    research_symbols = research_symbols or set()
    stop = {'USD', 'CEO', 'CFO', 'EPS', 'GDP', 'PCE', 'Q1', 'Q2', 'Q3', 'Q4', 'AI', 'US', 'EU', 'SPY', 'QQQ', 'DIA', 'IWM', 'VIX', 'VIXY', 'VXX', 'TLT', 'UUP', 'USO', 'GLD', 'SLV', 'IBIT'}
    for line in lines:
        explicit = set(re.findall(r'\$([A-Z][A-Z0-9]{1,7})\b', line))
        # Also catch bare symbols, but only for the curated focus list to avoid false positives.
        bare_focus = {sym for sym in focus_symbols if re.search(rf'\b{re.escape(sym)}\b', line)}
        for sym in sorted(explicit | bare_focus):
            if sym in stop:
                continue
            if research_symbols and sym not in research_symbols and sym not in focus_symbols:
                continue
            counts[sym] = counts.get(sym, 0) + (4 if sym in focus_symbols else 2 if sym in research_symbols else 1)
            example.setdefault(sym, line)
    ranked = sorted(counts, key=lambda symbol: (-counts[symbol], symbol))[:8]
    out = []
    for sym in ranked:
        why = example.get(sym, '')[:260]
        out.append({'symbol': sym, 'why': why, 'hasResearch': sym in research_symbols, **market_move_payload(why, sym)})
    return out


def extract_portfolio_actions(body: str, limit: int = 7) -> list[dict[str, str]]:
    secs = heading_sections(body)
    wanted = ['Portfolio / Watchlist Impact', 'Portfolio/Watchlist Impact', 'Conviction Watchlist', 'Portfolio translation']
    raw: list[str] = []
    for sec in secs:
        if any(w.lower() in sec['title'].lower() for w in wanted):
            raw.extend(bullets(sec['content'], 10, 340))
    if not raw:
        for sec in secs:
            if 'regime map' in sec['title'].lower():
                raw.extend([b for b in bullets(sec['content'], 8, 340) if re.search(r'portfolio|new entries|add|trim|hold|do not chase|proof', b, re.I)])
    actions = []
    seen: set[str] = set()
    for item in raw:
        text = clean_inline(item)
        if len(text) < 25:
            continue
        low = text.lower()
        if re.search(r'\b(trim|reduce|sell|do not add|no fresh adds|no chase|hold/trim)\b', low):
            stance = 'trim / do not add'
        elif re.search(r'\b(add|buy|starter|new entries allowed|proof-add|size up)\b', low):
            stance = 'add only with proof'
        elif re.search(r'\b(hold|maintain|keep|parking lot|monitor)\b', low):
            stance = 'hold / monitor'
        else:
            stance = 'no change'
        sym_match = re.search(r'\$([A-Z][A-Z0-9]{1,7})\b', text)
        symbol = sym_match.group(1) if sym_match else ''
        key = (symbol or text[:80]).lower()
        if key in seen:
            continue
        seen.add(key)
        actions.append({'symbol': symbol, 'stance': stance, 'text': text})
        if len(actions) >= limit:
            break
    return actions


def extract_market_narrative(body: str, max_items: int = 7) -> dict[str, Any]:
    """Pull a human macro story from the canonical daily brief, not scorecards.

    The interface emphasizes narrative rather than about raw Breadth/Macro scores than the narrative translation:
    why the tape moved, where leadership is, and what that means for pressing risk.
    """
    secs = heading_sections(body)
    preferred = [
        'TL;DR / What Changed', 'What Changed', 'Market Setup', 'Why It Moved',
        'News-Site Ground Truth', 'Macro Regime + Breadth', 'Regime Map',
        'Market Tape + Cross-Asset', 'Portfolio / Watchlist Impact', 'Operating stance',
    ]
    picked: list[str] = []
    for needle in preferred:
        for sec in secs:
            title = sec['title'].lower()
            if needle.lower() in title or title in needle.lower():
                picked.extend(bullets(sec['content'], 8, 330))
        if len(picked) >= max_items:
            break
    if not picked:
        picked = labeled_paragraphs(body, ['Action posture', 'Macro / exposure context', 'Tape / macro', 'X signal read', 'Convergence', 'Result'], max_items, 330)
    if not picked:
        picked = bullets(body, max_items, 330)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in picked:
        s = clean_inline(item).strip()
        # Keep the human classification, not the raw score dump appended after it.
        s = re.split(r'\bTraderMonty\s+overlay\b', s, 1, flags=re.I)[0].strip(' .;:') or s
        s = re.sub(r'\bTraderMonty\s+overlay\s+is\s+still\s+', '', s)
        s = re.sub(r'\b(Breadth|Macro|Exposure Coach)\s+\d+(?:\.\d+)?(?:/100)?\b[,; ]*', '', s)
        s = re.sub(r'\s+', ' ', s).strip(' -–—')
        if not s or len(s) < 30 or re.search(r'^(raw|source|sources|links:|wiki pages updated|verification|created research audit|command:)', s, re.I):
            continue
        key = re.sub(r'\$[A-Z0-9]+', '$TICKER', s.lower())[:150]
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(add_emoji(s))
        if len(cleaned) >= max_items:
            break
    stance = next((re.sub(r'^[•✅🎯📌⚠️🔴🟡🟢⚪ ]+', '', x) for x in cleaned if re.search(r'\b(Classification|Operating stance|selective|new entries|no chase|proof)\b', x, re.I)), '')
    if stance:
        stance = re.sub(r'^Classification:\s*', '', stance, flags=re.I)
        stance = re.split(r'\b(?:TraderMonty|constructive but|Breadth|Macro Broadening|Exposure Coach)\b', stance, 1, flags=re.I)[0].strip(' .;:')
    return {
        'title': stance[:160] or 'Macro story: read the tape, then size around proof.',
        'bullets': cleaned,
    }


def add_emoji(line: str) -> str:
    low = line.lower()
    if line.startswith(('🟢', '🟡', '🔴', '⚠️', '✅', '🎯', '💡', '📌', '⚪')):
        return line
    urgent = ['urgent', 'breaking', 'halt', 'liquidity crisis', 'default', 'fraud']
    if any(w in low for w in urgent):
        return '⚠️ ' + line
    if re.search(r'\b(no chase|avoid|kill|sell|trim|failed)\b', low):
        return '🔴 ' + line
    if re.search(r'\b(mixed|not clean|watch|monitor|wait|flat|range|closed|neutral)\b', low):
        return '🟡 ' + line
    if re.search(r'\b(mildly bullish|bullish|constructive|supportive|risk-on|beat|raise|breakout|strong|positive)\b', low) and not re.search(r'\b(but|however|failed|bearish|avoid|kill|no chase|trim)\b', low):
        return '🟢 ' + line
    negative = ['avoid', 'no chase', 'kill', 'dilution', 'bearish', 'fragile', 'sell', 'trim', 'miss', 'risk-off', 'breakdown', 'pressure', 'failed']
    positive = ['buy', 'add', 'hold', 'keep', 'starter', 'proof', 'bullish', 'risk-on', 'beat', 'raise', 'strong', 'breakout', 'positive', 'constructive', 'supportive']
    neg_count = sum(1 for w in negative if w in low)
    pos_count = sum(1 for w in positive if w in low)
    if pos_count > neg_count:
        return '🟢 ' + line
    if neg_count > pos_count:
        return '🔴 ' + line
    if pos_count or neg_count or any(w in low for w in ['earnings', 'catalyst', 'trigger', 'closer look']):
        return '🟡 ' + line
    if any(w in low for w in ['theme', 'regime', 'macro', 'inflation', 'rates', 'breadth', 'photonics', 'cpo', 'memory', 'hbm', 'ai power', 'gold', 'silver']):
        return '📌 ' + line
    return '⚪ ' + line


def extract_action_callouts(content: str, limit: int = 6) -> list[dict[str, str]]:
    """Extract dashboard-native action cards from briefing closer-look sections.

    The Slack morning briefing carries the highest-value daily trade content in
    nested bullets. A generic "first N bullets" journal extractor can bury these
    below market setup/regime bullets, so keep them as first-class cards.
    """
    callouts: list[dict[str, str]] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r'^[-*]\s+\*\*\$?([A-Z][A-Z0-9]{1,7})\s+[—-]\s+ACTION:\s*([^*]+)\*\*', line, re.I)
        if not m:
            i += 1
            continue
        symbol = m.group(1).upper()
        action = clean_inline(m.group(2))[:160]
        details: list[str] = []
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if re.match(r'^[-*]\s+\*\*\$?[A-Z][A-Z0-9]{1,7}\s+[—-]\s+ACTION:', nxt.strip(), re.I):
                break
            detail = nxt.strip()
            if detail.startswith(('-', '*')):
                cleaned = clean_inline(re.sub(r'^[-*]\s+', '', detail))
                if re.match(r'^(Why now|Proof-add trigger|Kill trigger|Max size|What would change my mind|Aggressive case):', cleaned, re.I):
                    details.append(cleaned[:240].rstrip())
            i += 1
        callouts.append({'symbol': symbol, 'action': action, 'details': details[:4]})
        if len(callouts) >= limit:
            break
    return callouts


def source_label(path: Path, fm: dict[str, Any], body: str) -> str:
    s = str(path).lower()
    rel = '/' + str(path.relative_to(WIKI)).lower()
    if '/briefs/' in rel and re.fullmatch(r'20\d{2}-\d{2}-\d{2}\.md', path.name):
        return 'Daily research brief'
    if 'market_media' in s:
        return 'Public market media'
    if 'podcast' in s or 'podcast' in fm.get('type', ''):
        return 'Podcast'
    if 'macro_transcripts' in s or 'transcript' in fm.get('type', ''):
        return 'Macro transcript source'
    if 'deep_dives' in s:
        return 'Deep dive'
    if 'feeds' in s or 'last30days' in s:
        return 'Web/blog research'
    if 'earnings' in path.name:
        return 'Earnings calendar'
    if 'x_' in path.name or 'x list' in body.lower() or 'signal' in body.lower():
        return 'X signal scan'
    return 'Daily note'


def parse_daily_journal(tickers: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    focus_symbols = set(parse_shortlist().keys())
    research_symbols = {str(t.get('symbol')) for t in (tickers or []) if t.get('symbol')}
    for path in latest_daily_paths():
        text = read(path)
        fm, body = frontmatter(text)
        date = file_date(path) or str(fm.get('updated') or fm.get('created') or path.stem)
        secs = heading_sections(body)
        source_type_for_skip = source_label(path, fm, body)
        has_decision_label = bool(labeled_paragraphs(body, ['Action posture', 'Macro / exposure context', 'Tape / macro', 'X signal read', 'Convergence', 'Result'], limit=1))
        if source_type_for_skip == 'Daily research brief' and not has_decision_label and not any(
            any(key in sec['title'].lower() for key in [
                'market setup', 'tl;dr', 'what changed', 'stocks worth', 'portfolio',
                'canonical daily market update', 'morning market briefing',
                # Decision-bearing append-only jobs are sparse but still valid dashboard leads.
                'action posture', 'macro / exposure context', 'x signal read', 'convergence', 'result',
            ])
            for sec in secs
        ):
            # Ignore sparse intra-day append-only files (e.g. overnight Fed/gold alert scans)
            # until the actual daily market brief has been written.
            continue
        wanted = [
            'Executive Verdict', 'Market Setup', 'Regime Map', 'Stocks Worth Your Closer Look',
            "Today's Catalysts", 'Signal Highlights', 'Gold Sentiment', 'Gold / Silver', 'Silver', 'Precious Metals', 'Bottom Line',
            'Portfolio Signals', 'Portfolio/Watchlist Impact', 'Conviction Watchlist',
            'Emerging Themes', 'X Signals Today', 'Today\'s Deep Dives', 'Deep Dive',
            'Macro Themes', 'Follow-up Use', 'Ticker', 'Tickers / Opinions',
            # Append-only job sections that carry PM decisions before the full brief exists.
            'Result', 'Convergence', 'Macro / exposure context', 'Tape / macro', 'X signal read', 'Action posture',
        ]
        metal_wanted = ['Gold Sentiment', 'Gold / Silver', 'Gold/Silver', 'Silver', 'Precious Metals', 'Metals']
        highlights: list[str] = []
        metal_highlights: list[str] = []
        action_callouts: list[dict[str, str]] = []
        for title in wanted:
            for sec in secs:
                if title.lower() in sec['title'].lower():
                    if 'stocks worth your closer look' in sec['title'].lower():
                        action_callouts.extend(extract_action_callouts(sec['content']))
                    vals = bullets(sec['content'], 8, 260)
                    if vals:
                        highlights.extend(vals)
                    else:
                        para = first_paragraph(sec['content'], 420)
                        if para:
                            highlights.append(para)
        for sec in secs:
            if any(title.lower() in sec['title'].lower() for title in metal_wanted):
                vals = bullets(sec['content'], 6, 260)
                if vals:
                    metal_highlights.extend(vals)
                else:
                    para = first_paragraph(sec['content'], 360)
                    if para:
                        metal_highlights.append(para)
        if source_type_for_skip == 'Daily research brief':
            highlights.extend(labeled_paragraphs(body, ['Result', 'Convergence', 'Macro / exposure context', 'Tape / macro', 'X signal read', 'Action posture'], limit=8, max_len=320))
        if not highlights:
            highlights = bullets(body, 8, 360) or [first_paragraph(body, 520)]
        # Prefer actual content over file/source bookkeeping lines.
        cleaned_highlights = []
        cleaned_metals = []
        for h in highlights:
            candidate = clean_inline(h).strip(' -–—•')
            if (
                not candidate
                or len(candidate) < 20
                or re.search(r'^(raw|source|sources|links:|wiki pages updated|updated |created research audit|score:|edges:|followers:|bio:|url:|account:|example:)', candidate, re.I)
                or re.search(r'\[\d{1,2}:\d{2}', candidate)
                or re.search(r'(buckets|bucket map):$', candidate, re.I)
            ):
                continue
            cleaned_highlights.append(add_emoji(candidate))
        for h in metal_highlights:
            candidate = clean_inline(h).strip(' -–—•')
            if candidate and len(candidate) >= 18 and not re.search(r'^(source trace|sources|raw source|verification):', candidate, re.I):
                cleaned_metals.append(add_emoji(candidate))
        source_type = source_label(path, fm, body)
        by_date[date].append({
            'title': readable_title({'title': fm.get('title') or path.stem}),
            'sourceType': source_type,
            'sourcePath': str(path.relative_to(WIKI)),
            'summary': daily_lead_summary(body, 620) if source_type == 'Daily research brief' else first_paragraph(body, 620),
            'marketNarrative': extract_market_narrative(body),
            'portfolioActions': extract_portfolio_actions(body),
            'highlights': cleaned_highlights[:12],
            'goldSilver': cleaned_metals[:6],
            'actionCallouts': action_callouts[:6]
        })
    out = []
    for date, items in sorted(by_date.items(), reverse=True)[:14]:
        items = sorted(
            items,
            key=lambda row: (
                0 if row['sourceType'] == 'Daily research brief' else 1,
                str(row.get('sourcePath', '')),
                str(row.get('title', '')),
            ),
        )
        lead = next((i for i in items if i['sourceType'] == 'Daily research brief'), items[0])
        combined: list[str] = []
        combined_metals: list[str] = []
        combined_actions: list[dict[str, str]] = []
        combined_portfolio: list[dict[str, str]] = []
        # Daily brief first, then other source color. Avoid one-source days when a brief exists.
        for item in sorted(items, key=lambda x: 0 if x['sourceType'] == 'Daily research brief' else 1):
            # Keep more canonical daily-brief content; the older 5-line cap often
            # hid the actual stock action callouts underneath setup/regime bullets.
            take_limit = 10 if item['sourceType'] == 'Daily research brief' else 5
            combined.extend(item['highlights'][:take_limit])
            combined_metals.extend(item.get('goldSilver', [])[:4])
            combined_actions.extend(item.get('actionCallouts', [])[:6])
            combined_portfolio.extend(item.get('portfolioActions', [])[:7])
        deduped: list[str] = []
        seen: set[str] = set()
        event_seen: set[str] = set()
        for line in combined:
            clean_line = re.sub(r'^[•✅🎯📌⚠️🔴🟡🟢⚪ ]+', '', line).strip()
            if re.search(r'\bNo\s+.+\searnings found\b', clean_line, re.I):
                continue
            # Avoid duplicate earnings rows from the daily brief + earnings-preview file.
            tickers_in_line = tuple(sorted(set(re.findall(r'\$([A-Z][A-Z0-9]{1,7})\b', clean_line))))
            event_key = ''
            if tickers_in_line and re.search(r'\b(AMC|BMO|earnings|Est\. EPS|Rev)\b', clean_line, re.I):
                event_key = 'earnings:' + ','.join(tickers_in_line)
                if event_key in event_seen:
                    continue
                event_seen.add(event_key)
            key = re.sub(r'\$[A-Z0-9]+', '$TICKER', clean_line.lower())[:140]
            if key not in seen and len(clean_line) > 18:
                seen.add(key)
                deduped.append(line)
        ticker_lines = [re.sub(r'^[•✅🎯📌⚠️🔴🟡🟢⚪ ]+', '', x) for x in deduped]
        metal_deduped: list[str] = []
        metal_seen: set[str] = set()
        for line in combined_metals:
            clean_line = re.sub(r'^[•✅🎯📌⚠️🔴🟡🟢⚪ ]+', '', line).strip()
            key = clean_line.lower()[:140]
            if key and key not in metal_seen:
                metal_seen.add(key)
                metal_deduped.append(line)
        action_deduped: list[dict[str, str]] = []
        action_seen: set[str] = set()
        for action in combined_actions:
            key = f"{action.get('symbol','')}|{action.get('action','')[:80]}".lower()
            if action.get('symbol') and key not in action_seen:
                action_seen.add(key)
                action_deduped.append(action)
        summary = lead['summary']
        if re.match(r'\s*Links:', summary or '', re.I):
            summary = re.sub(r'^[•✅🎯📌⚠️🔴🟡🟢⚪ ]+', '', deduped[0]) if deduped else ''
        portfolio_deduped: list[dict[str, str]] = []
        portfolio_seen: set[str] = set()
        for action in combined_portfolio:
            key = f"{action.get('symbol','')}|{action.get('text','')[:90]}".lower()
            if key not in portfolio_seen:
                portfolio_seen.add(key)
                portfolio_deduped.append(action)
            if len(portfolio_deduped) >= 7:
                break
        if not portfolio_deduped:
            portfolio_deduped.append({'symbol': '', 'stance': 'no change', 'text': 'No clean portfolio adjustment signal was captured in the latest brief; default to no changes until a proof/add/trim trigger appears.'})
        action_tickers = []
        for a in action_deduped:
            sym = a.get('symbol', '')
            if not sym:
                continue
            why = f"{a.get('action', '')}: " + '; '.join(a.get('details', [])[:2])
            action_tickers.append({'symbol': sym, 'why': why, 'hasResearch': sym in research_symbols, **market_move_payload(why, sym)})
        mention_tickers = ticker_mentions(ticker_lines, focus_symbols, research_symbols)
        ticker_map: dict[str, dict[str, str]] = {}
        for row in action_tickers + mention_tickers:
            sym = row.get('symbol', '')
            if sym and sym not in ticker_map:
                ticker_map[sym] = row
        out.append({
            'date': date,
            'headline': lead['title'],
            'summary': summary,
            'marketNarrative': lead.get('marketNarrative') or {'title': '', 'bullets': []},
            'portfolioActions': portfolio_deduped,
            'keyTakeaways': deduped[:14],
            'actionCallouts': action_deduped[:6],
            'interestingTickers': sorted(ticker_map.values(), key=lambda row: str(row.get('symbol', '')))[:8],
            'goldSilver': metal_deduped[:5],
            'items': items,
            'sourceTypes': sorted(set(i['sourceType'] for i in items)),
        })
    return out

def parse_sources() -> list[dict[str, Any]]:
    x_files = sorted((WIKI / 'raw' / 'signals').glob('x_signals_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    x_count = 0
    if x_files:
        try:
            d = json.loads(read(x_files[0]))
            x_count = int(d.get('account_count') or len(d.get('accounts', {})))
        except Exception:
            pass
    return [
        {'name': 'Public social signals', 'role': 'Find early signal and consensus shifts', 'summary': f'An anonymized public-source scanner watches {x_count or "dozens of"} sources for cross-source ticker convergence, long-form theses, and new theme language.', 'examples': [], 'howUsed': 'Good for surfacing leads and changing sentiment; never enough by itself to buy without primary-source proof.'},
        {'name': 'Macro transcript sources', 'role': 'Translate public macro commentary into trade-relevant notes', 'summary': 'Public transcript sources are turned into macro, index, sector, geopolitical, and portfolio-impact notes.', 'examples': ['Macro transcript source', 'Public market-media transcript'], 'howUsed': 'Used for regime context and near-term risk, not as standalone stock underwriting.'},
        {'name': 'Company filings, press releases, IR pages', 'role': 'Verify numbers and kill bad narratives', 'summary': 'Primary-source articles, earnings releases, 8-K/6-K/10-Q excerpts, investor presentations, and company news are saved under raw articles/briefings.', 'examples': ['SEC/EDGAR excerpts', 'IR earnings releases', 'Investor presentations'], 'howUsed': 'This is the evidence layer for War Room summaries, conviction-list upgrades, proof gates, and kill triggers.'},
        {'name': 'Market data / APIs', 'role': 'Daily market posture and event calendar', 'summary': 'Breadth, macro-regime, exposure-posture, earnings calendar, price snapshots, and signal-scanner raw data feed the command center.', 'examples': ['TraderMonty breadth/regime reports', 'Nasdaq earnings calendar', 'price snapshots', 'FMP/Finnhub-style data feeds'], 'howUsed': 'Used to decide how hard to press new ideas and which catalyst windows matter now.'},
        {'name': 'Blogs / web research / deep dives', 'role': 'Theme research and thesis development', 'summary': 'Last-30-days web sweeps, manual deep dives, papers, and blog/article notes are synthesized into daily journal entries and ticker pages.', 'examples': ['AI power', 'CPO/photonics', 'neoclouds', 'memory/HBM', 'robotics/physical AI'], 'howUsed': 'Used to build watchlists and answer “what is this?” before a full War Room refresh is needed.'},
    ]


def latest_file(patterns: list[str]) -> Path | None:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(WIKI.glob(pattern))
    files = [f for f in files if f.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: (file_date(p), p.stat().st_mtime))


def artifact(path: Path | None, label: str) -> dict[str, str] | None:
    if not path or not path.exists():
        return None
    try:
        text = read(path)
        if path.suffix.lower() == '.json':
            data = json.loads(text)
            comp = data.get('composite') if isinstance(data.get('composite'), dict) else data
            score = comp.get('composite_score') or comp.get('score')
            zone = comp.get('zone') or comp.get('bias') or comp.get('regime') or ''
            guidance = comp.get('guidance') or data.get('rationale') or data.get('summary') or ''
            title = clean_inline(label)
            parts = []
            if score is not None:
                parts.append(f'Score {round(float(score), 1)}')
            if zone:
                parts.append(str(zone))
            if guidance:
                parts.append(clean_inline(str(guidance))[:260])
            summary = ' · '.join(parts) or 'Structured dashboard input generated by a market pipeline.'
            return {'label': label, 'title': title, 'date': file_date(path), 'sourcePath': str(path.relative_to(WIKI)), 'summary': summary}
        fm, body = frontmatter(text)
        title = clean_inline(str(fm.get('title') or re.sub(r'[_-]+', ' ', path.stem)))
        summary = first_paragraph(body, 520) or first_paragraph(text, 520)
        if re.match(r'^Links:', summary or '', re.I):
            summary = first_paragraph(section(body, 'Market Setup') or section(body, 'Overall read') or section(body, 'Executive Verdict') or section(body, 'Bottom Line'), 520)
            if not summary:
                blocks = [clean_inline(b) for b in re.split(r'\n\s*\n', body) if clean_inline(b) and not re.match(r'^(Links:|#|---)', clean_inline(b), re.I)]
                summary = next((b for b in blocks if len(b) > 30), '')[:520]
        return {
            'label': label,
            'title': title[:180],
            'date': file_date(path) or str(fm.get('updated') or fm.get('created') or ''),
            'sourcePath': str(path.relative_to(WIKI)),
            'summary': summary,
        }
    except Exception:
        return None


def load_cron_jobs() -> list[dict[str, Any]]:
    path = CRON_ROOT / 'jobs.json'
    if not path.exists():
        return []
    try:
        raw = json.loads(read(path))
        jobs = raw.get('jobs', raw if isinstance(raw, list) else [])
    except Exception:
        return []
    out = []
    for job in jobs:
        if not job.get('enabled', True):
            continue
        schedule = job.get('schedule')
        if isinstance(schedule, dict):
            schedule_text = str(schedule.get('display') or schedule.get('expr') or schedule.get('run_at') or '')
        else:
            schedule_text = str(schedule or '')
        out.append({
            'id': job.get('job_id') or job.get('id') or '',
            'name': job.get('name') or 'Unnamed job',
            'schedule': schedule_text,
            'deliver': job.get('deliver') or '',
        })
    return out


def pick_jobs(jobs: list[dict[str, Any]], patterns: list[str]) -> list[dict[str, str]]:
    regexes = [re.compile(p, re.I) for p in patterns]
    picked = []
    for job in jobs:
        name = job.get('name', '')
        if any(r.search(name) for r in regexes):
            picked.append({k: str(job.get(k, '')) for k in ['id', 'name', 'schedule', 'deliver']})
    return picked[:12]


def parse_coverage() -> list[dict[str, Any]]:
    jobs = load_cron_jobs()
    groups = [
        {
            'name': 'Daily market command center', 'emoji': '🌅', 'cadence': 'Weekday/daily pre-market',
            'whatItCovers': 'The morning market brief, daily research brief, breadth/regime/exposure overlays, and the final dashboard refresh.',
            'dashboardRole': 'This should be the first thing you read each morning: what changed, what matters, and what to watch today.',
            'jobs': pick_jobs(jobs, ['Morning Market Briefing', 'Daily Research Brief', 'Market Dashboard Refresh', 'X Signal Scanner', 'SEC Insider']),
            'artifacts': [artifact(latest_file(['daily/briefs/20*.md']), 'Latest daily brief'), artifact(latest_file(['reports/market_breadth_*.json']), 'Breadth report'), artifact(latest_file(['reports/macro_regime_*.json']), 'Macro regime'), artifact(latest_file(['reports/exposure_posture_*.json']), 'Portfolio posture')],
        },
        {
            'name': 'Crowd / sentiment radar', 'emoji': '🧠', 'cadence': 'Weekly Sunday + midweek Wednesday',
            'whatItCovers': 'Reddit/YouTube crowding, creator attention, theme hype, and whether a good thesis has become too consensus to chase.',
            'dashboardRole': 'This was underrepresented before. It now gets its own coverage card and is also pulled into the dated market journal.',
            'jobs': pick_jobs(jobs, ['last30days Weekly Market Sentiment', 'last30days Midweek Crowding']),
            'artifacts': [artifact(latest_file(['daily/feeds/last30days_20*.md']), 'Weekly sentiment scan'), artifact(latest_file(['daily/feeds/last30days_midweek_20*.md']), 'Midweek crowding check')],
        },
        {
            'name': 'Stock research / War Room pipeline', 'emoji': '🔬', 'cadence': 'Scheduled deep dives + hourly high-priority sweep while active',
            'whatItCovers': 'Ticker pages, conviction list, proof/kill triggers, thesis refreshes, and War Room-quality updates.',
            'dashboardRole': 'Feeds the Stock Research tab. If a ticker is refreshed but not on the focus list, search can still find it; focus names stay curated.',
            'jobs': pick_jobs(jobs, ['Stock Deep Dive', 'Weekly Auto Deep Research', 'High Priority Wiki Stock War Room', 'Portfolio Monitor']),
            'artifacts': [artifact(latest_file(['research-queue.md']), 'Research queue'), artifact(latest_file(['conviction-shortlist.md']), 'Conviction shortlist'), artifact(latest_file(['daily/deep_dives/*.md', 'raw/papers/*.md', 'raw/articles/*.md']), 'Latest deep research artifact')],
        },
        {
            'name': 'Earnings / catalyst calendar', 'emoji': '📅', 'cadence': 'Weekly preview + one-off earnings jobs around report dates',
            'whatItCovers': 'Upcoming earnings, beat/miss reactions, guide changes, and whether a result creates proof, no-proof, or kill-trigger evidence.',
            'dashboardRole': 'Feeds daily journal bullets and ticker pages; useful for deciding what needs attention this week.',
            'jobs': pick_jobs(jobs, ['Weekly Earnings Preview', 'Earnings Auto', '^Earnings:']),
            'artifacts': [artifact(latest_file(['daily/briefs/*earnings_preview.md']), 'Weekly earnings preview'), artifact(latest_file(['daily/briefs/*earnings*.md', 'raw/briefings/*earnings*.md']), 'Latest earnings note')],
        },
        {
            'name': 'Macro / media tape', 'emoji': '🎥', 'cadence': 'Daily / weekday transcript ingestion',
            'whatItCovers': 'Public macro transcripts, market-media framing, index levels, oil/geopolitical risk, and broad sentiment.',
            'dashboardRole': 'Provides context and narrative color, but gets weighted below primary data and company proof.',
            'jobs': pick_jobs(jobs, ['Daily Macro Transcript', 'CNBC Fast Money']),
            'artifacts': [artifact(latest_file(['daily/macro_transcripts/*.md']), 'Latest macro transcript note'), artifact(latest_file(['daily/market_media/*.md']), 'Latest public market-media note')],
        },
        {
            'name': 'Metals / futures monitor', 'emoji': '🥇', 'cadence': 'Weekday pre-market/post-market + central-bank alert checks',
            'whatItCovers': 'Gold/silver positioning, Fed/central-bank headlines, futures levels, and risk notes for the separate metals workflow.',
            'dashboardRole': 'Shown as coverage awareness here; detailed trade management still lives in the metals channel.',
            'jobs': pick_jobs(jobs, ['Gold Futures', 'Silver Futures', 'Gold .*Central Bank', 'Weekly Gold']),
            'artifacts': [artifact(latest_file(['themes/gold_precious_metals.md']), 'Gold / precious-metals theme page')],
        },
        {
            'name': 'Publishing / social amplification', 'emoji': '📣', 'cadence': 'Multiple weekly slots',
            'whatItCovers': 'Public posts, watchlists, replies, weekly research summaries, and post-close takes.',
            'dashboardRole': 'Not an input source by itself; included so the command center shows where research gets converted into public output.',
            'jobs': pick_jobs(jobs, ['Public Publishing Workflow']),
            'artifacts': [artifact(latest_file(['log.md']), 'Wiki activity log')],
        },
    ]
    for group in groups:
        group['artifacts'] = [a for a in group.get('artifacts', []) if a]
    return groups


def parse_agentic_trading_report() -> dict[str, Any] | None:
    """Latest completed MES paper-algo recap for the dashboard.

    The MES trading profile writes these into the market wiki after RTH. Keep this
    separate from the daily research brief to track whether the agentic
    trading loop is improving without digging through Slack or cron output.
    """
    files = sorted(
        (WIKI / 'daily' / 'briefs').glob('mes_algo_20*.md'),
        key=lambda p: (file_date(p), p.stat().st_mtime),
        reverse=True,
    )
    files = [p for p in files if re.fullmatch(r'mes_algo_20\d{2}-\d{2}-\d{2}\.md', p.name)]
    if not files:
        return None
    path = files[0]
    fm, body = frontmatter(read(path))
    m = re.search(r'```text\s*(.*?)```', body, flags=re.S)
    code = m.group(1).strip() if m else body
    report_lines = [clean_inline(line) for line in code.splitlines() if clean_inline(line)]
    data: dict[str, str] = {}
    notes: list[str] = []
    in_notes = False
    for line in report_lines:
        if line.lower().startswith('learning notes'):
            in_notes = True
            continue
        if in_notes:
            if line.startswith('-'):
                notes.append(clean_inline(line.lstrip('- ')))
            continue
        if ':' in line:
            key, val = line.split(':', 1)
            data[key.strip().lower()] = clean_inline(val)
    signal_line = data.get('signals', '')
    signal_pairs = dict(re.findall(r'([A-Z_]+)=([\w.-]+)', signal_line))
    entries = int(float(signal_pairs.get('ENTRY', '0'))) if signal_pairs.get('ENTRY') else 0
    total_match = re.search(r'total=([\d.]+)', signal_line)
    total_signals = int(float(total_match.group(1))) if total_match else 0
    status = 'Learning / calibrating'
    traffic = '🟡'
    if entries > 0:
        status = 'Entries appeared — review quality, not just count'
        traffic = '🟢'
    if re.search(r'total_R=-|verdict=REFINE|blocked=[1-9]', ' '.join(data.values()), re.I):
        status = 'Needs refinement before live-money trust'
        traffic = '🟡'
    cards = []
    for key, label in [
        ('stream', 'Stream health'),
        ('signals', 'Signals'),
        ('shadow', 'Shadow P&L'),
        ('paper router', 'Paper router'),
        ('latest backtest', 'Latest backtest'),
        ('macro/research', 'Macro gate'),
    ]:
        if data.get(key):
            cards.append({'label': label, 'text': data[key]})
    return {
        'lane': 'Futures / MES',
        'date': file_date(path) or str(fm.get('created') or ''),
        'title': clean_inline(str(fm.get('title') or path.stem)),
        'sourcePath': str(path.relative_to(WIKI)),
        'traffic': traffic,
        'status': status,
        'summary': f"{total_signals} evaluator checks, {entries} ENTRY_READY signals. {data.get('shadow', 'No shadow report captured.')}",
        'cards': cards,
        'learningNotes': notes[:4],
    }


def sanitize_private_numbers(text: str) -> str:
    """Withhold complete private claims; retain company financial figures."""
    return clean_narrative(text)


def latest_cron_output(job_id: str) -> Path | None:
    root = CRON_ROOT / 'output' / job_id
    if not root.exists():
        return None
    files = sorted(root.glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def redact_private_markdown(text: str) -> str:
    """Public narrative boundary: never produce redaction fragments."""
    return clean_narrative(text)


def cron_response_from_output(text: str) -> str:
    if re.search(r'\*\*Status:\*\*\s*silent \(empty output\)', text, re.I):
        return ''
    if '## Response' in text:
        response = text.rsplit('## Response', 1)[1].strip()
        # Skill-loader notices and scheduler sentinels are operational metadata, not market events.
        response = re.sub(r'^⚠️\s*Skill\(s\) not found and skipped:.*?(?:\n\n|\n(?=\S))', '', response, count=1, flags=re.I | re.S)
        response = re.sub(r'\n?\[SILENT\]\s*$', '', response, flags=re.I).strip()
        return response
    # A failed agent run may contain its entire prompt and no final response.
    # Never treat that prompt/skill payload as no-agent stdout.
    if re.search(r'^## Prompt\s*$', text, re.M):
        return ''
    # no_agent jobs with non-empty stdout may not have a Response section. Drop the cron metadata block.
    lines = text.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if i > 0 and line.startswith('# '):
            body_start = i
            break
        if i >= 6 and line.strip():
            body_start = i
            break
    return '\n'.join(lines[body_start:]).strip()


def cron_timeline_category(job_name: str) -> str:
    name = job_name.lower()
    if any(x in name for x in ['x signal', 'last30days', 'crowding', 'sentiment', 'referral graph']):
        return 'Sentiment / source radar'
    if any(x in name for x in ['earnings']):
        return 'Earnings / catalysts'
    if any(x in name for x in ['robinhood', 'portfolio', 'war room', 'conviction', 're-rate', 'radar']):
        return 'Portfolio / stock decisions'
    if any(x in name for x in ['macro', 'market briefing', 'dashboard', 'hygiene', 'research feed']):
        return 'Market brief / research ops'
    if any(x in name for x in ['mes', 'trading execution']):
        return 'Execution / trading system'
    return 'Other research job'


def is_market_decision_job(job_name: str) -> bool:
    """Keep the Daily Brief focused on market events and capital decisions, not system operations."""
    name = job_name.lower()
    excluded = [
        'dashboard', 'publish', 'deploy', 'hygiene', 'checker', 'freshness gate',
        'auto-scheduler', 'ingestion', 'builder', 'recovery pilot', 'execution watchdog',
        'e2e tester', 'memory & skill', 'public publishing workflow',
    ]
    if any(term in name for term in excluded):
        return False
    included = [
        'market briefing', 'earnings', 'macro', 'portfolio', 'conviction', 'war room',
        're-rate', 'radar', 'deep dive', 'x signal', 'insider buying', 'watchlist movers',
        'gold', 'silver', 'crowding', 'sentiment', 'research feed',
    ]
    return any(term in name for term in included)


def is_market_decision_response(response: str) -> bool:
    """Reject tool/runtime failure reports even when the parent job is market-related."""
    failure_only = [
        'script exited with code', 'command failed (', 'specified token is not valid',
        'i stopped retrying', 'same_tool_failure_halt', 'tool-call guardrail',
        'uncaught exception', 'traceback (most recent call last)',
    ]
    lower = response.lower()
    return not any(marker in lower for marker in failure_only)


def is_operational_brief_line(line: str) -> bool:
    """Remove pipeline bookkeeping while preserving market facts and recommendations."""
    lower = clean_inline(line).lower()
    operational = [
        'raw scan:', 'api pages', 'page cap', 'tweets fetched', 'ticker groups found',
        'read path:', 'files changed', 'verification', 'rebuilt index', 'wiki lint',
        'warnings appear', 'generatedat:', 'board updated', 'shortlist refreshed',
        'freshness gate', 'quote tape:', 'portfolio/broker:', 'thesis/macro: fresh',
        'no automated brokerage', 'job successfully completed', 'wiki was updated',
        'skill(s) not found', 'account scope', 'cash / buying power', 'position marks',
        'net tracker p/l', 'what happened today', 'no positions or orders',
        'wiki audit', 'build index', 'artifacts:', 'read-only broker check',
        'freshness:', 'event/news:', 'thesis pages:', 'counts:', 'status:',
    ]
    return any(marker in lower for marker in operational)


def market_brief_bullets(response: str, limit: int = 6) -> list[str]:
    """Extract both numbered recommendations and markdown market-event bullets."""
    numbered: list[str] = []
    for raw in response.splitlines():
        if not re.match(r'^\s*\d+[.)]\s+', raw):
            continue
        line = clean_inline(re.sub(r'^\s*\d+[.)]\s+', '', raw))[:280]
        if line:
            numbered.append(line)
    # Recommendations/top signals are normally numbered, so rank them ahead of bookkeeping bullets.
    candidates = numbered + bullets(response, 30, 280)
    out: list[str] = []
    for line in candidates:
        cleaned = clean_inline(line)
        if not cleaned or cleaned.endswith(':') or is_operational_brief_line(cleaned) or cleaned in out:
            continue
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def parse_market_brief_notes() -> list[dict[str, Any]]:
    """Opt-in canonical notes only; invalid migrated notes fail generation visibly."""
    out = []
    for path in sorted((WIKI / 'daily' / 'briefs').glob('market_brief_*.md')):
        fm, body = validate_note(path)
        body = redact_private_markdown(body)
        summary = first_paragraph(body, 420)
        highlights = market_brief_bullets(section(body, 'Key points'), 6)
        out.append({
            'id': path.stem,
            'jobId': str(fm['job_id']),
            'jobName': bounded_research_title(str(fm['title'])),
            'runTime': timestamp(fm['updated']),
            'schedule': '',
            'deliver': 'market-brief',
            'category': 'Market brief / ' + fm['market_brief_lane'].replace('_', ' '),
            'sourcePath': str(path.relative_to(WIKI)),
            'summary': summary,
            'articleBody': body,
            'highlights': [add_emoji(h) for h in highlights if h != summary][:5],
        })
    return out


def timeline_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    try:
        stamp = timestamp(item['runTime'])
    except (ValueError, TypeError):
        stamp = str(item['runTime'])
    return stamp, item['id']


def parse_cron_timeline(limit: int = 30) -> list[dict[str, Any]]:
    """Build a curated market-event brief from final cron responses.

    Operational failures, deployment logs, and repeated runs of the same job on the same day
    are intentionally excluded. The dashboard is a decision surface, not a system log viewer.
    """
    root = CRON_ROOT / 'output'
    notes = parse_market_brief_notes()
    job_meta = {j.get('id', ''): j for j in load_cron_jobs()}
    # Resolve only explicit heading identities against existing canonical titles.
    # No new feed, financial matching, prompt mining or scheduler-name fallback.
    canonical_titles = {}
    for ticker_path in (WIKI / 'tickers').glob('*.md'):
        fm, _ = frontmatter(read(ticker_path))
        if not has_private_classification(fm):
            raw_title = fm.get('title')
            if isinstance(raw_title, str) and not re.match(r'^' + re.escape(ticker_path.stem) + r'\s+[—–-]\s+', raw_title):
                raw_title = ticker_path.stem + ' — ' + raw_title
            title = bounded_research_title(raw_title)
            if title:
                canonical_titles[ticker_path.stem] = title
    files = sorted(root.glob('*/*.md'), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    seen_job_days: set[tuple[str, str]] = set()
    for path in files[:300]:
        # Migrated jobs are represented exclusively by canonical notes, never X history/statuses.
        if path.parent.name in LANE_JOBS.values():
            continue
        try:
            text = read(path)
        except Exception:
            continue
        response = redact_private_markdown(cron_response_from_output(text))
        if not response or len(response) < 20:
            continue
        if not is_market_decision_response(response):
            continue
        if re.search(r'^\s*\*\*Status:\*\*\s*silent \(empty output\)', response, re.I):
            continue
        job_id = path.parent.name
        job_name_match = re.search(r'^# Cron Job:\s*(.+)$', text, re.M)
        run_time_match = re.search(r'^\*\*Run Time:\*\*\s*(.+)$', text, re.M)
        schedule_match = re.search(r'^\*\*Schedule:\*\*\s*(.+)$', text, re.M)
        job_name = job_name_match.group(1) if job_name_match else job_meta.get(job_id, {}).get('name') or job_id
        run_time = run_time_match.group(1) if run_time_match else file_date(path) or ''
        if not is_market_decision_job(str(job_name)) and not is_weekly_analysis(job_id, str(job_name)):
            continue
        run_day = clean_inline(str(run_time))[:10]
        dedupe_key = (job_id, run_day)
        if dedupe_key in seen_job_days:
            continue
        seen_job_days.add(dedupe_key)
        schedule = schedule_match.group(1) if schedule_match else job_meta.get(job_id, {}).get('schedule') or ''
        highlight_lines = market_brief_bullets(response, 6)
        if not highlight_lines:
            highlight_lines = labeled_paragraphs(response, ['Result', 'Convergence', 'Action', 'Macro / exposure context', 'Status'], 5, 280)
        if not highlight_lines:
            highlight_lines = [clean_inline(line)[:280] for line in response.splitlines() if clean_inline(line) and not line.startswith('#')][:5]
        summary = first_paragraph(response, 420)
        if not summary or is_operational_brief_line(summary):
            summary = highlight_lines[0] if highlight_lines else ''
        display_highlights = [h for h in highlight_lines if clean_inline(h) != clean_inline(summary)]
        weekly = is_weekly_analysis(job_id, str(job_name))
        if not summary and not display_highlights:
            continue  # Do not resurrect a no-sample receipt with old commentary.
        why_selected = weekly_selection(job_id, path.stem, cron_response_from_output(text), WIKI) if weekly else ''
        # Existing articleBody carries the sourced selection without a new schema.
        # Privacy policy remains in force for the source rationale.
        selection_body = ('## Why selected this week\n\n' + why_selected) if why_selected else ('## Why selected this week\n\nSelection rationale is unavailable for this run.' if weekly else '')
        out.append({
            'id': f'{job_id}-{path.stem}',
            'jobId': job_id,
            'jobName': source_brief_title(cron_response_from_output(text), canonical_titles) if '## Response' in text else '',
            'runTime': clean_inline(str(run_time)),
            'schedule': clean_inline(str(schedule)),
            'deliver': clean_inline(str(job_meta.get(job_id, {}).get('deliver') or 'local/output')),
            'category': 'Weekly Stock Analysis' if weekly else cron_timeline_category(str(job_name)),
            'articleBody': selection_body,
            'sourcePath': f'cron/output/{job_id}/{path.name}',
            'summary': summary,
            'highlights': [add_emoji(h) for h in display_highlights[:5] if h],
        })
    for row in out:
        if row.get('jobId') in MACRO_JOB_IDS:
            row.update(macro_row(row))
            source_path = CRON_ROOT / 'output' / row['jobId'] / (row['id'].removeprefix(row['jobId'] + '-') + '.md')
            authored = cron_response_from_output(read(source_path))
            if re.match(r'^#{1,2}\s+Macro Read\b', authored.strip(), re.I):
                from macro_presentation import neutral_macro_text
                row['articleBody'] = clean_narrative(neutral_macro_text(authored)) + '\n\n' + CONFIDENCE_HELP
                continue
            try:
                run_date = datetime.fromisoformat(row['runTime'][:10]).replace(tzinfo=timezone.utc)
                commentary = macro_opinion_read(now=run_date)
            except ValueError:
                commentary = ['Commentary date unavailable; no combined opinion is assigned.']
            row['articleBody'] = '## Commentary views\n\n' + '\n\n'.join(commentary) + '\n\n' + CONFIDENCE_HELP
    return sorted(notes + out, key=timeline_sort_key, reverse=True)[:limit]


def section_lines(markdown: str, heading: str, limit: int = 6) -> list[str]:
    pattern = rf'##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s+|\Z)'
    m = re.search(pattern, markdown, flags=re.S | re.I)
    if not m:
        bold_pattern = rf'\*\*{re.escape(heading)}:\*\*\s*(.*?)(?=\n\s*\*\*[^\n:]+:\*\*|\n##\s+|\Z)'
        m = re.search(bold_pattern, markdown, flags=re.S | re.I)
    if not m:
        return []
    lines = []
    for raw in m.group(1).splitlines():
        line = sanitize_private_numbers(raw.strip().strip('- '))
        if not line or line.startswith('|---') or line == '|':
            continue
        if 'data/portfolio/' in line or 'brokerage_snapshot_latest' in line:
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def dollarize_candidate_line(line: str) -> str:
    """Make portfolio-integration candidate rows scannable."""
    line = re.sub(r'^(\s*\d+\.\s+)(?!\$)([A-Z][A-Z0-9]{1,7})(\s+[—-])', r'\1$\2\3', line)
    line = re.sub(r'^(\s*[-*•]\s+)(?!\$)([A-Z][A-Z0-9]{1,7})(\s+[—-])', r'\1$\2\3', line)
    return line


def parse_key_value_table(markdown: str, heading: str) -> dict[str, str]:
    sec = section(markdown, heading)
    out: dict[str, str] = {}
    for raw in sec.splitlines():
        if not raw.strip().startswith('|') or '---' in raw:
            continue
        cells = table_cells(raw)
        if len(cells) >= 2 and cells[0].lower() != 'field':
            out[cells[0]] = cells[1]
    return out


def parse_current_decision_queue(markdown: str, limit: int = 8) -> list[dict[str, str]]:
    sec = section(markdown, 'Current decision queue')
    rows: list[dict[str, str]] = []
    header: list[str] = []
    for raw in sec.splitlines():
        if not raw.strip().startswith('|'):
            continue
        if '---' in raw:
            continue
        cells = table_cells(raw)
        if cells and cells[0].lower() == 'rank':
            header = [c.lower().replace(' ', '_').replace('/', '_') for c in cells]
            continue
        if header and len(cells) >= len(header):
            row = dict(zip(header, cells))
            rows.append({
                'rank': row.get('rank', ''),
                'tickerTheme': row.get('ticker_theme', ''),
                'state': row.get('state', ''),
                'requiredTrigger': row.get('required_trigger', ''),
                'fundingSource': row.get('funding_source', ''),
                'freshness': row.get('freshness', ''),
                'decision': row.get('decision', ''),
            })
        if len(rows) >= limit:
            break
    return rows


def parse_macro_state() -> dict[str, Any] | None:
    # Canonical deterministic bridge first; the legacy hand-maintained state is
    # retained only as a compatibility fallback during rollout.
    paths = [
        WIKI / 'data' / 'automation' / 'macro_regime_snapshot_latest.json',
        WIKI / 'data' / 'macro_regime_state.json',
    ]
    path = next((candidate for candidate in paths if candidate.exists()), None)
    if path is None:
        return None
    try:
        data = json.loads(read(path))
    except Exception:
        return None
    allowed = {
        'as_of', 'structural_regime', 'tactical_risk', 'exposure_dial', 'confidence',
        'freshness_status', 'external_sentiment', 'blocking_events_next_14d',
        'press_allowed', 'add_size_allowed', 'reason', 'source_paths'
    }
    return {k: scrub_private(v) if isinstance(v, str) else v for k, v in data.items() if k in allowed}


def macro_opinion_read(*, now: datetime | None = None) -> list[str]:
    """Bounded excerpts, not a vote or confidence model.

    Read only the newest dated note in each canonical lane. A missing/degraded
    note never falls back to an older opinion. Date-only notes have a conservative
    three-calendar-day window; modification times do not refresh evidence.
    Only complete, public-safe opinion bullets are eligible. Raw provenance stays
    in the canonical notes, never in the display strings.
    """
    today = (now or datetime.now(timezone.utc)).date()
    views: list[str] = []
    available = 0
    gaps: list[str] = []
    attribution = re.compile(r'(?i)\b(?:macro transcript source|public market media|presenter|host|creator)\s+(?:says?|argues?|warns?)\b|https?://')
    for lane in ('macro_transcripts', 'market_media'):
        dated = []
        for path in (WIKI / 'daily' / lane).glob('*.md'):
            match = re.fullmatch(re.escape(lane) + r'_(\d{4}-\d{2}-\d{2})\.md', path.name)
            if not match:
                continue
            try:
                note_day = date.fromisoformat(match.group(1))
                if note_day <= today:
                    dated.append((note_day, path))
            except ValueError:
                continue
        if not dated:
            gaps.append('unavailable')
            continue
        day, path = max(dated)
        age = (today - day).days
        if not 0 <= age <= 2:
            gaps.append('stale' if age > 2 else 'unavailable')
            continue
        text = read(path)
        # Fail closed for explicitly private or incomplete source records.
        if re.search(r'(?im)^privacy[_ -]?class:\s*(?!public(?:_ok)?\s*$)\S+', text) or re.search(r'(?i)degraded[ /-]*(?:transcript|no[ -]signal)|transcription was (?:killed|timed out)|no (?:new )?usable[^\n]*transcripts', text):
            gaps.append('unavailable')
            continue
        section = re.search(r'(?ms)^## (?:Creator Recommendations / Opinions|Macro Themes)\s*\n(.*?)(?=^## |\Z)', text)
        bullets = []
        if section:
            for line in section.group(1).splitlines():
                if not re.match(r'^\s*-\s+', line):
                    continue
                line = re.sub(r'^\s*-\s+', '', line)
                line = re.sub(r'\^\[[^\]]*\]', '', line)
                line = re.sub(r'\[\d{1,2}:\d{2}(?::\d{2})?(?:-\d{1,2}:\d{2}(?::\d{2})?)?\]', '', line)
                line = re.sub(r'\s+', ' ', line).strip()
                # Do not silently strip attribution or salvage transcript fragments.
                if attribution.search(line) or '…' in line or '...' in line or not re.search(r'[.!?]$', line):
                    continue
                # Preserve complete qualifiers/negations: unsafe bullets are atomic.
                clean = clean_narrative(line)
                if not clean or clean != line or len(clean) > 700:
                    continue
                if clean not in bullets:
                    bullets.append(clean)
        if not bullets:
            gaps.append('unavailable')
            continue
        available += 1
        views.append(f'Commentary view ({day.isoformat()}): ' + ' '.join(bullets[:3]))
    if available:
        coverage = f'{available} available commentary note' + ('s' if available != 1 else '') + '; opinions, not independent confirmation.'
    else:
        coverage = 'No current publishable commentary; no combined opinion is available.'
    if gaps:
        coverage += f" {len(gaps)} commentary note" + ('s' if len(gaps) != 1 else '') + ' unavailable' + (' or stale' if 'stale' in gaps else '') + '.'
    return [coverage, *views]


def canonical_macro_posture() -> dict[str, Any] | None:
    """Project the canonical macro bridge into one compact CIO posture card."""
    path = WIKI / 'data' / 'automation' / 'macro_regime_snapshot_latest.json'
    if not path.exists():
        return None
    try:
        data = json.loads(read(path))
    except Exception:
        return None
    observed = data.get('observedMarket') or {}
    pressure = data.get('qualitativeLeadingPressure') or {}
    policy = data.get('decisionPolicy') or {}
    freshness = data.get('freshness') or {}
    regime = clean_inline(str(data.get('structuralRegime') or 'unknown')).replace('_', ' ').title()
    tactical = clean_inline(str(data.get('tacticalRisk') or 'unknown')).replace('_', ' ')
    tactical = tactical.replace('risk on', 'risk-on').replace('risk off', 'risk-off')
    transition = observed.get('transitionScore')
    breadth = observed.get('breadthScore')
    breadth_zone = clean_inline(str(observed.get('breadthZone') or ''))
    exposure = clean_inline(str(observed.get('exposureRecommendation') or 'SELECTIVE')).replace('_', ' ')
    press = bool(policy.get('pressAllowed'))
    add_size = bool(policy.get('addSizeAllowed'))
    if press:
        plain_title = 'Broad strength. We can lean in.'
        plain_english = 'The market backdrop supports adding risk, but company proof still matters.'
    elif 'NEW ENTRY' in exposure and not add_size:
        plain_title = 'More stocks are working, but stay selective'
        plain_english = 'Small new positions are okay. Wait for stronger proof before adding size.'
    elif add_size:
        plain_title = 'Constructive, but do not chase'
        plain_english = 'New positions and measured adds are okay when the company evidence is strong.'
    else:
        plain_title = 'The backdrop is not helping'
        plain_english = 'Hold off on new risk until market conditions improve.'

    watch: list[str] = []
    if isinstance(breadth, (int, float)):
        if breadth >= 65 or breadth_zone.lower() in {'healthy', 'strong'}:
            watch.append('Market participation is broad and healthy')
        elif breadth < 40 or breadth_zone.lower() in {'weak', 'fragile'}:
            watch.append('Only a narrow group of stocks is holding up')
        else:
            watch.append('Market participation is mixed')
    pressure_score = pressure.get('score')
    pressure_label = clean_inline(str(pressure.get('label') or '')).replace('_', ' ')
    if isinstance(pressure_score, (int, float)):
        if pressure_score >= 2 or pressure_label in {'positive', 'supportive'}:
            watch.append('Outside research is leaning more bullish')
        elif pressure_score <= -2 or pressure_label in {'negative', 'cautious'}:
            watch.append('Outside research is leaning more cautious')
        else:
            watch.append('Outside research is mixed, with no strong push either way')
    warning_keys = {clean_inline(str(row)).lower() for row in (policy.get('axisWarnings') or []) if row}
    if 'liquidity_policy' in warning_keys:
        watch.append('Main risk: the flow of money into markets is becoming less supportive')
    elif 'credit_funding' in warning_keys:
        watch.append('Main risk: borrowing and funding conditions are getting tighter')
    elif warning_keys:
        watch.append('The macro backdrop still has an important risk to clear')
    channels = data.get('decisionTransmission', {}).get('channels') or []
    reduce_keys = {clean_inline(str(row.get('channel') or '')).lower() for row in channels if row.get('actionEffect') == 'reduce_one_step'}
    improve_keys = {clean_inline(str(row.get('channel') or '')).lower() for row in channels if row.get('actionEffect') == 'improve_timing_only'}
    reduce: list[str] = []
    if 'crypto' in reduce_keys:
        reduce.append('crypto')
    if {'duration_sensitive_growth', 'financing_dependent_growth'} & reduce_keys:
        reduce.append('growth companies that depend on low rates or cheap funding')
    improve_labels = {
        'cash_duration_hedges': 'cash and bond hedges',
        'cyclicals': 'cyclical stocks',
        'small_caps': 'small caps',
        'earnings_leaders': 'proven earners',
        'gold': 'gold',
    }
    improve = [label for key, label in improve_labels.items() if key in improve_keys]
    if reduce:
        watch.append('Be more careful with ' + ' and '.join(reduce))
    if improve:
        watch.append('Better setup for ' + ', '.join(improve))
    return {
        'name': 'Canonical regime',
        'sourcePath': str(path.relative_to(WIKI)),
        'score': transition if isinstance(transition, (int, float)) else None,
        'zone': f"{regime} · {tactical}",
        'plainTitle': plain_title,
        'plainEnglish': plain_english,
        'watch': watch[:5],
        'artifactDate': clean_inline(str(data.get('asOf') or data.get('as_of') or ''))[:80],
        'freshnessStatus': clean_inline(str(freshness.get('status') or data.get('freshness_status') or 'unknown'))[:40],
    }


def parse_portfolio_data_integration_report() -> dict[str, Any] | None:
    cron_path = latest_cron_output('synthetic-job-03')
    raw_files = sorted((WIKI / 'raw' / 'briefings').glob('portfolio_data_integration_20*.md'), key=lambda p: p.stat().st_mtime, reverse=True)
    candidates = [p for p in [cron_path, *(raw_files[:1])] if p]
    if not candidates:
        return None
    path = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    text = read(path)
    response = text.split('## Response', 1)[-1] if '## Response' in text else text
    title = next((clean_inline(l.lstrip('# ')) for l in response.splitlines() if l.startswith('## Portfolio-data Integration Report')), '')
    is_agentic_account = bool(title)
    if not title:
        title = next((clean_inline(l.lstrip('# ')) for l in response.splitlines() if l.startswith('## Post-Market Portfolio-data Summary')), 'Portfolio-data integration summary')
    date_match = re.search(r'(20\d{2}-\d{2}-\d{2})', title) or re.search(r'(20\d{2}-\d{2}-\d{2})', path.name)
    if is_agentic_account:
        account = section_lines(response, 'Account scope', 5)
        happened = section_lines(response, 'What happened today', 6)
        macro = section_lines(response, 'Macro / exposure dial', 6)
        candidates = [dollarize_candidate_line(x) for x in section_lines(response, 'Candidate watchlist', 8)]
        action = section_lines(response, 'Proposed next action', 6)
        status_lines = section_lines(response, 'Status', 3)
        summary = sanitize_private_numbers(' '.join((status_lines or account or macro)[:3]))[:320] or 'Latest privacy-filtered portfolio-data integration report.'
        status = summary
        traffic = '🟡'
        if re.search(r'\b(do not trade|cash|wait)\b', summary + ' ' + ' '.join(action), re.I):
            traffic = '🟡'
        if re.search(r'\b(starter candidate|buy small|press)\b', summary + ' ' + ' '.join(action), re.I):
            traffic = '🟢'
        if re.search(r'\b(red|avoid|halt|broken)\b', summary + ' ' + ' '.join(action), re.I):
            traffic = '🔴'
        cards = [c for c in [
            {'label': 'Account scope', 'text': ' '.join(account[:5])},
            {'label': 'What happened', 'text': ' '.join(happened[:5])},
            {'label': 'Macro / exposure dial', 'text': ' '.join(macro[:5])},
            {'label': 'Candidate watchlist', 'text': '\n'.join(candidates[:7])},
            {'label': 'Proposed next action', 'text': ' '.join(action[:5])},
        ] if c['text']]
        notes = [
            'Optional isolated execution summary; excluded from the public demo.',
            'Any broker action remains explicit-confirmation gated after order review.',
        ]
    else:
        first = response.split('## Portfolio Change Headline', 1)[0]
        macro = [sanitize_private_numbers(l) for l in first.splitlines() if clean_inline(l) and not l.startswith('#')][:6]
        portfolio = section_lines(response, 'Portfolio Change Headline', 6)
        metals = section_lines(response, 'Metals / GLD-SLV Options', 6)
        action = section_lines(response, 'Action Items', 7)
        score = section_lines(response, 'Scorecard', 8)
        summary = 'Latest portfolio-data integration captured macro context, concentration drift, risk notes, and action items. Raw account values stay private.'
        if macro:
            summary = sanitize_private_numbers(' '.join(macro[:3]))[:320]
        status = 'Legacy default-portfolio report — superseded by Agentic account scope on the next run'
        traffic = '🟡'
        cards = [c for c in [
            {'label': 'Macro / exposure dial', 'text': ' '.join(macro[:5])},
            {'label': 'Portfolio drift', 'text': ' '.join(portfolio[:5])},
            {'label': 'Metals / options', 'text': ' '.join(metals[:5])},
            {'label': 'Scorecard', 'text': ' '.join(score[:8])},
            {'label': 'Action items', 'text': ' '.join(action[:6])},
        ] if c['text']]
        notes = [
            'Legacy report used the default portfolio; future runs are pinned to the Agentic account.',
            'Any broker action remains explicit-confirmation gated after order review.',
        ]
    return {
        'lane': 'Portfolio-data integration',
        'date': date_match.group(1) if date_match else '',
        'title': title,
        'sourcePath': str(path.relative_to(WIKI)) if str(path).startswith(str(WIKI)) else f'cron/output/synthetic-job-03/{path.name}',
        'traffic': traffic,
        'status': status,
        'summary': summary,
        'cards': cards,
        'learningNotes': notes,
    }


def parse_agentic_trading_reports() -> list[dict[str, Any]]:
    reports = [parse_agentic_trading_report(), parse_portfolio_data_integration_report()]
    return [r for r in reports if r]


GRAPH_LABELS = {
    'market_research_cio_dashboard': 'Market research checks',
    'earnings_proof_gate': 'Earnings proof gate',
}


def graph_node_label(node_id: str) -> str:
    label = node_id.replace('_', ' ').title()
    for title_case, acronym in [('Ai', 'AI'), ('Ic', 'IC'), ('Sec', 'SEC')]:
        label = re.sub(rf'\b{title_case}\b', acronym, label)
    return label


def extract_markdown_section_lines(text: str, heading: str, limit: int = 8, max_len: int = 220) -> list[str]:
    body = section(text, heading)
    if not body:
        return []
    return bullets(body, limit=limit, max_len=max_len)


def parse_market_graphs() -> list[dict[str, Any]]:
    """Load public-safe Phase 1 graph status for the CIO dashboard.

    The dashboard should ingest the graph's checker output, not raw private node
    detail. Keep this intentionally small: gate status, degraded/blocked nodes,
    self-heal notes, and enough paths for local audit.
    """
    base = WIKI / 'data/automation/graph_runs'
    if not base.exists():
        return []
    graphs: list[dict[str, Any]] = []
    for workflow_id, label in GRAPH_LABELS.items():
        latest_path = base / workflow_id / 'latest.json'
        if not latest_path.exists():
            decision_events = [{
                'privacy_class': 'public_ok',
                'id': f'{workflow_id}:missing:latest',
                'workflowId': workflow_id,
                'runId': '',
                'gate': 'fail',
                'scope': 'research',
                'decision': 'Graph latest.json is missing; block checked dashboard synthesis for this workflow.',
                'proof': ['latest.json missing'],
                'blockedBy': ['latest.json'],
                'sourcePaths': [],
                'slackWorthy': True,
                'severity': 'urgent',
                'generatedAt': '',
            }]
            graphs.append({
                'privacy_class': 'public_ok',
                'workflowId': workflow_id,
                'label': label,
                'finalGate': 'missing',
                'recommendation': 'No graph run has been captured yet.',
                'allowedNodes': [],
                'blockedNodes': ['latest.json missing'],
                'selfHealSummary': [],
                'privacyFindings': [],
                'brokerSafetyFindings': [],
                'contradictions': [],
                'tickers': [],
                'themes': [],
                'nodeCount': 0,
                'passCount': 0,
                'degradedCount': 0,
                'failCount': 1,
                'decisionEvents': decision_events,
                'decisionEventCount': len(decision_events),
                'slackWorthyEventCount': 1,
            })
            continue
        try:
            latest = json.loads(read(latest_path))
        except Exception:
            decision_events = [{
                'privacy_class': 'public_ok',
                'id': f'{workflow_id}:fail:latest-parse',
                'workflowId': workflow_id,
                'runId': '',
                'gate': 'fail',
                'scope': 'research',
                'decision': 'Graph latest.json could not be parsed; block checked dashboard synthesis for this workflow.',
                'proof': ['latest.json parse failed'],
                'blockedBy': ['latest.json'],
                'sourcePaths': [],
                'slackWorthy': True,
                'severity': 'urgent',
                'generatedAt': '',
            }]
            graphs.append({
                'privacy_class': 'public_ok',
                'workflowId': workflow_id,
                'label': label,
                'finalGate': 'fail',
                'recommendation': 'latest.json could not be parsed.',
                'allowedNodes': [],
                'blockedNodes': ['latest.json parse failed'],
                'selfHealSummary': [],
                'privacyFindings': [],
                'brokerSafetyFindings': [],
                'contradictions': [],
                'tickers': [],
                'themes': [],
                'nodeCount': 0,
                'passCount': 0,
                'degradedCount': 0,
                'failCount': 1,
                'decisionEvents': decision_events,
                'decisionEventCount': len(decision_events),
                'slackWorthyEventCount': 1,
            })
            continue
        checker_rel = str(latest.get('checker_path') or '')
        final_rel = str(latest.get('final_path') or '')
        events_rel = str(latest.get('decision_events_path') or '')
        checker_path = WIKI / checker_rel if checker_rel else Path()
        final_path = WIKI / final_rel if final_rel else Path()
        events_path = WIKI / events_rel if events_rel else Path()
        checker: dict[str, Any] = {}
        if checker_path.exists():
            try:
                checker = json.loads(read(checker_path))
            except Exception:
                checker = {}
        raw_events: list[dict[str, Any]] = []
        if events_path.exists():
            try:
                parsed_events = json.loads(read(events_path))
                if isinstance(parsed_events, list):
                    raw_events = [
                        event for event in parsed_events
                        if isinstance(event, dict)
                        and event.get('privacy_class') in {'public', 'public_ok'}
                    ]
            except Exception:
                raw_events = []
        final_text = read(final_path) if final_path.exists() else ''
        # Checker output is private by default. Missing classification must not
        # silently become public at this export boundary.
        node_results = [
            n for n in (checker.get('node_results') or [])
            if isinstance(n, dict) and n.get('privacy_class') in {'public', 'public_ok'}
        ]
        pass_count = sum(1 for n in node_results if n.get('status') == 'pass')
        degraded_count = sum(1 for n in node_results if n.get('status') == 'degraded')
        fail_count = sum(1 for n in node_results if n.get('status') == 'fail')
        graph_nodes = []
        graph_edges = []
        for n in node_results:
            node_id = clean_inline(str(n.get('node_id') or 'node'))[:80]
            graph_nodes.append({
                'privacy_class': 'public_ok',
                'id': node_id,
                'label': graph_node_label(node_id),
                'kind': 'source',
                'status': clean_inline(str(n.get('status') or 'unknown'))[:40],
                'freshness': clean_inline(str(n.get('freshness_status') or 'unknown'))[:40],
                'freshnessContext': clean_inline(str(n.get('freshness_context') or 'unknown'))[:80],
                'pipelineStale': bool(n.get('pipeline_stale')),
                'allowedIntoSynthesis': bool(n.get('allowed_into_synthesis')),
                'reason': clean_inline(str(n.get('reason') or ''))[:220],
                'outputPath': clean_inline(str(n.get('output_path') or ''))[:220],
                'sourceCount': len(n.get('source_paths') or []),
                'healActions': [clean_inline(str(x))[:220] for x in n.get('heal_actions', []) if x][:5],
            })
            graph_edges.append({'from': node_id, 'to': 'checker', 'status': clean_inline(str(n.get('status') or 'unknown'))[:40]})
        graph_nodes.append({
            'privacy_class': 'public_ok',
            'id': 'checker',
            'label': 'Checker gate',
            'kind': 'checker',
            'status': latest.get('final_gate') or checker.get('final_gate') or checker.get('checker_status') or 'unknown',
            'freshness': 'n/a',
            'allowedIntoSynthesis': (latest.get('final_gate') or checker.get('final_gate')) != 'fail',
            'reason': 'Freshness, proof-quality, privacy, contradictions, and broker-safety gate.',
            'outputPath': checker_rel,
            'sourceCount': len(node_results),
            'healActions': [clean_inline(str(x))[:220] for x in checker.get('self_heal_summary', []) if x][:5],
        })
        graph_nodes.append({
            'privacy_class': 'public_ok',
            'id': 'synthesis',
            'label': 'Dashboard synthesis',
            'kind': 'synthesis',
            'status': latest.get('final_gate') or checker.get('final_gate') or checker.get('checker_status') or 'unknown',
            'freshness': 'n/a',
            'allowedIntoSynthesis': True,
            'reason': 'Consumes checker-approved output only; public dashboard payload stays privacy scrubbed.',
            'outputPath': final_rel,
            'sourceCount': len([n for n in node_results if n.get('allowed_into_synthesis')]),
            'healActions': [],
        })
        graph_edges.append({'from': 'checker', 'to': 'synthesis', 'status': latest.get('final_gate') or checker.get('final_gate') or 'unknown'})

        # The dashboard graph is an operational lineage view, not just a
        # research sketch. Once checker-approved synthesis exists, this builder
        # structurally projects it into the public snapshot, the Blob manifest
        # points clients at that immutable snapshot. Workflow Ops is the only
        # current UI consumer of graph status; CIO no longer reads it. Keep the
        # consumers explicit so future tabs are not implied before they are
        # actually wired to marketGraphs.
        delivery_nodes = [
            {
                'privacy_class': 'public_ok',
                'id': 'public_snapshot',
                'label': 'Public snapshot',
                'kind': 'publish',
                'status': 'pass',
                'freshness': 'current-build',
                'allowedIntoSynthesis': True,
                'reason': 'Structural projection allowlists the graph DTO and privacy-scrubs it before publication.',
                'outputPath': 'public/wiki-data.json',
                'sourceCount': 1,
                'healActions': [],
            },
            {
                'privacy_class': 'public_ok',
                'id': 'runtime_manifest',
                'label': 'Blob manifest',
                'kind': 'transport',
                'status': 'configured',
                'freshness': 'runtime-verified',
                'allowedIntoSynthesis': True,
                'reason': 'Manifest points clients to an immutable, hash-verified public snapshot; live status is resolved in the browser.',
                'outputPath': '',
                'sourceCount': 1,
                'healActions': [],
            },
            {
                'privacy_class': 'public_ok',
                'id': 'workflow_ops',
                'label': 'Workflow Ops',
                'kind': 'consumer',
                'status': 'configured',
                'freshness': 'runtime-verified',
                'allowedIntoSynthesis': True,
                'reason': 'Reads recorded workflow checks and source diagnostics; the browser independently reports actual edition delivery.',
                'outputPath': '#ops',
                'sourceCount': 1,
                'healActions': [],
            },
        ]
        graph_nodes.extend(delivery_nodes)
        graph_edges.extend([
            {'from': 'synthesis', 'to': 'public_snapshot', 'status': 'pass'},
            {'from': 'public_snapshot', 'to': 'runtime_manifest', 'status': 'configured'},
            {'from': 'runtime_manifest', 'to': 'workflow_ops', 'status': 'configured'},
        ])
        allowed = [
            f"{n.get('node_id')}: {n.get('status')} / {n.get('freshness_status')}"
            for n in node_results
            if n.get('allowed_into_synthesis')
        ][:10]
        blocked = [
            f"{n.get('node_id')}: {n.get('status')} — {n.get('reason', 'blocked')}"
            for n in node_results
            if not n.get('allowed_into_synthesis')
        ][:10]
        if not blocked:
            blocked = extract_markdown_section_lines(final_text, 'Blocked / excluded nodes', limit=4)
        privacy = [clean_inline(str(f.get('node_id', 'privacy')) + ': ' + str(f.get('finding', 'privacy finding'))) for f in checker.get('privacy_findings', [])][:6]
        broker = [clean_inline(str(f)) for f in checker.get('broker_safety_findings', [])][:6]
        contradictions = [clean_inline(f"{c.get('claim_a', '')} vs {c.get('claim_b', '')}: {c.get('resolution_needed', '')}") for c in checker.get('contradictions', [])][:4]
        recommendation = first_paragraph(section(final_text, 'Recommendation'), 260) or clean_inline(str(latest.get('final_gate') or checker.get('final_gate') or 'unknown'))
        decision_events = []
        for event in raw_events[:16]:
            decision_events.append({
                'privacy_class': 'public_ok',
                'id': clean_inline(str(event.get('id') or 'graph-event'))[:160],
                'workflowId': workflow_id,
                'runId': clean_inline(str(event.get('runId') or latest.get('run_id') or ''))[:80],
                'gate': clean_inline(str(event.get('gate') or 'unknown'))[:40],
                'scope': clean_inline(str(event.get('scope') or 'research'))[:80],
                'decision': clean_inline(str(event.get('decision') or 'Graph decision event'))[:360],
                'proof': [clean_inline(str(x))[:260] for x in event.get('proof', []) if x][:8],
                'blockedBy': [clean_inline(str(x))[:140] for x in event.get('blockedBy', []) if x][:8],
                'sourcePaths': [clean_inline(str(x))[:180] for x in event.get('sourcePaths', []) if x][:8],
                'slackWorthy': bool(event.get('slackWorthy')),
                'severity': clean_inline(str(event.get('severity') or 'info'))[:40],
                'generatedAt': clean_inline(str(event.get('generatedAt') or latest.get('generated_at') or ''))[:80],
            })
        if not decision_events:
            gate = latest.get('final_gate') or checker.get('final_gate') or checker.get('checker_status') or 'unknown'
            decision_events = [{
                'privacy_class': 'public_ok',
                'id': f'{workflow_id}:{latest.get("run_id") or "latest"}:status',
                'workflowId': workflow_id,
                'runId': latest.get('run_id') or checker.get('run_id') or '',
                'gate': gate,
                'scope': 'research',
                'decision': clean_inline(recommendation),
                'proof': [f'checker_report.json final_gate={gate}'],
                'blockedBy': [x.split(':', 1)[0] for x in blocked][:8],
                'sourcePaths': [checker_rel] if checker_rel else [],
                'slackWorthy': gate == 'fail',
                'severity': 'urgent' if gate == 'fail' else 'warning' if gate in {'degraded', 'missing', 'unknown'} else 'info',
                'generatedAt': latest.get('generated_at') or checker.get('generated_at') or '',
            }]
        graphs.append({
            'privacy_class': 'public_ok',
            'workflowId': workflow_id,
            'label': label,
            'runId': latest.get('run_id') or checker.get('run_id') or '',
            'generatedAt': latest.get('generated_at') or checker.get('generated_at') or '',
            'finalGate': latest.get('final_gate') or checker.get('final_gate') or checker.get('checker_status') or 'unknown',
            'recommendation': clean_inline(recommendation),
            'allowedNodes': [clean_inline(x) for x in allowed],
            'blockedNodes': [clean_inline(x) for x in blocked if x and not re.search(r'\bnone\b', x, re.I)],
            'selfHealSummary': [clean_inline(str(x)) for x in checker.get('self_heal_summary', [])][:8],
            'privacyFindings': privacy,
            'brokerSafetyFindings': broker,
            'contradictions': contradictions,
            'tickers': [x.strip().replace('$', '') for x in ','.join(extract_markdown_section_lines(final_text, 'Tickers detected', limit=2, max_len=1200)).split(',') if x.strip()][:40],
            'themes': [x.strip() for x in ','.join(extract_markdown_section_lines(final_text, 'Themes detected', limit=2, max_len=600)).split(',') if x.strip()][:20],
            'nodeCount': len(node_results),
            'passCount': pass_count,
            'degradedCount': degraded_count,
            'failCount': fail_count,
            'finalPath': final_rel,
            'checkerPath': checker_rel,
            'decisionEventsPath': events_rel,
            'decisionEvents': decision_events,
            'decisionEventCount': len(decision_events),
            'slackWorthyEventCount': sum(1 for e in decision_events if e.get('slackWorthy')),
            'marketClosedCarryCount': sum(1 for n in node_results if n.get('freshness_context') == 'market_closed_carry_forward'),
            'pipelineStaleCount': sum(1 for n in node_results if n.get('freshness_context') == 'pipeline_stale'),
            'graphNodes': graph_nodes,
            'graphEdges': graph_edges,
        })
    return graphs


def build_legacy_sections() -> dict[str, Any]:
    if not (WIKI / 'tickers').exists():
        raise FileNotFoundError(f'wiki source {WIKI} unavailable')

    tickers = parse_tickers()
    reports = [
        canonical_macro_posture(),
        plain_report('Market Breadth', latest_json('market_breadth'), report_score_history('market_breadth')),
        plain_report('Macro Regime', latest_json('macro_regime'), report_score_history('macro_regime')),
        plain_report('Exposure Posture', latest_json('exposure_posture'), report_score_history('exposure_posture')),
    ]
    reports = [r for r in reports if r]
    buckets: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for t in tickers:
        buckets[t['actionBucket']] = buckets.get(t['actionBucket'], 0) + 1
        category_counts[t['category']] = category_counts.get(t['category'], 0) + 1
        for tag in t.get('tags', []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    shortlist = [t for t in tickers if t.get('shortlistGroup')]
    daily_journal = parse_daily_journal(tickers)
    agentic_trading_reports = parse_agentic_trading_reports()
    intraday_watchdog = load_intraday_equity_watchdog()
    market_graphs = parse_market_graphs()
    intraday_symbols = [str(s).upper() for s in (intraday_watchdog or {}).get('monitored_symbols', []) if s]
    intraday_rank = {sym: i for i, sym in enumerate(intraday_symbols)}
    focus_symbols = {t['symbol'] for t in shortlist} | set(intraday_symbols)
    focus_tickers = [t for t in tickers if t['symbol'] in focus_symbols]

    def focus_rank(t: dict[str, Any]) -> tuple[int, int, str]:
        if t.get('shortlistRank'):
            try:
                return (0, int(t.get('shortlistRank') or 999), t['symbol'])
            except ValueError:
                return (0, 999, t['symbol'])
        return (1, intraday_rank.get(t['symbol'], 999), t['symbol'])

    payload = {
        'counts': {'tickers': len(tickers), 'researched': sum(1 for t in tickers if not t['isStub']), 'stubs': sum(1 for t in tickers if t['isStub']), 'reports': len(reports), 'convictionItems': len(focus_tickers), 'journalDays': len(daily_journal)},
        'actionBuckets': buckets,
        'topTags': sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:30],
        'categoryCounts': dict(sorted(category_counts.items(), key=lambda kv: kv[1], reverse=True)),
        'marketPosture': reports,
        'dailyJournal': daily_journal,
        'cronTimeline': parse_cron_timeline(),
        'intradayEquityWatchdog': intraday_watchdog,
        'marketGraphs': market_graphs,
        'currentAsymmetricShortlist': parse_current_asymmetric_shortlist(),
        'aiProjectionExhibits': parse_ai_projection_exhibits(),
        'aiWarRoomCompleteData': parse_ai_war_room_complete_data(),
        'agenticTradingReport': agentic_trading_reports[0] if agentic_trading_reports else None,
        'agenticTradingReports': agentic_trading_reports,
        'sources': parse_sources(),
        'tickers': tickers,
        'focusTickers': sorted(focus_tickers, key=focus_rank),
    }
    # Future jobs publish shared records here; no new registration/UI branch.
    publication_root = WIKI / 'data/publications'
    payload['publications'] = []
    for publication_file in sorted(publication_root.glob('*.json')):
        try:
            record = json.loads(publication_file.read_text(encoding='utf-8'))
            payload['publications'].extend(record if isinstance(record, list) else [record])
        except (OSError, ValueError):
            print('publication input unreadable; retaining previous valid records', file=sys.stderr)
    return payload


def main(argv: list[str] | None = None) -> int:
    global WIKI, OUT, CRON_ROOT, OFFLINE
    parser = argparse.ArgumentParser(description='Build canonical public MarketWiki snapshot')
    parser.add_argument('--wiki-root', required=True)
    parser.add_argument('--cron-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--macro-meter', type=Path, help='Read an existing producer meter JSON artifact unchanged; never calculate a score')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--offline', action='store_true', help='Read existing artifacts only; no external quote lookups or cache writes')
    args = parser.parse_args(argv)
    if any(not value.strip() for value in (args.wiki_root, args.cron_root, args.output)):
        parser.error("explicit input and output paths must not be empty")
    if not args.offline:
        parser.error("generator requires explicit --offline")
    OFFLINE = True
    WIKI = Path(args.wiki_root).resolve()
    CRON_ROOT = Path(args.cron_root).resolve()
    OUT = Path(args.output).resolve()
    try:
        require_wiki(WIKI)
        require_wiki(CRON_ROOT)
        meter_path = args.macro_meter.resolve() if args.macro_meter else None
        inventory_roots = [WIKI, CRON_ROOT]
        if meter_path:
            if meter_path.suffix.lower() != '.json':
                raise ValueError('macro meter artifact must be JSON')
            inventory_roots.append(meter_path.parent)

        def build_sections():
            raw = build_legacy_sections()
            if meter_path:
                meter = json.loads(meter_path.read_text(encoding='utf-8'))
                # Explicit malformed input must fail, not become an unavailable fallback.
                if not isinstance(meter, dict) or not meter:
                    raise ValueError('macro meter artifact must be a nonempty object')
                raw['macroRegimeMeter'] = meter
            return raw

        raw, inventory = stable_build(build_sections, inventory_roots, attempts=2)
        previous_snapshot = json.loads(OUT.read_text()) if OUT.exists() else {}
        previous = previous_snapshot.get('publications', [])
        raw['cronTimeline'] = sorted(retain_verified_weekly_history(
            raw['cronTimeline'], previous_snapshot.get('cronTimeline', []), WIKI,
        ), key=timeline_sort_key, reverse=True)[:30]
        publication_diagnostics = []
        body = build_public_snapshot(
            raw,
            previous_publications=previous, diagnostics=publication_diagnostics,
            data_as_of=represented_data_as_of(raw, inventory, trusted_roots=[WIKI, CRON_ROOT]),
            cron_root=CRON_ROOT,
        )
        if publication_diagnostics:
            print(json.dumps({'publicationDiagnostics': publication_diagnostics}), file=sys.stderr)
        validate_public_snapshot_schema(body)
        data = canonical_json_bytes(body)
        changed = atomic_write_bytes(OUT, data)
    except (MixedGenerationError, PrivacyError, ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    if not args.quiet:
        print(f"{'wrote' if changed else 'unchanged'} {OUT} ({len(data)} bytes, {snapshot_id(body)})")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
