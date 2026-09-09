#!/usr/bin/env python3
"""Canonical, deterministic and privacy-safe MarketWiki public snapshot primitives.

The immutable snapshot body deliberately excludes snapshotId, builtAt and
publishedAt.  Its identity is SHA-256 of :func:`canonical_json_bytes` exactly.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo
from public_content import adapt_legacy, merge_publications, sanitize_legacy, assert_public_suitability

SCHEMA_VERSION = 1
MAX_BYTES = 5_800_000
TEXT_SUFFIXES = {".json", ".js", ".mjs", ".cjs", ".html", ".css", ".txt", ".md", ".map", ".xml", ".svg"}
DENIED_PUBLIC_FILENAMES = {"strategy-data.json"}
FORBIDDEN_KEY_FRAGMENTS = (
    "accountnumber", "accountvalue", "accountid", "brokerid", "token", "apikey",
    "secret", "password", "taxlot", "quantity", "sharecount", "contractcount",
    "account", "portfolio", "positionvalue", "costbasis", "realizedpnl", "unrealizedpnl", "pnl",
    "drypowder", "goalgap", "networth", "portfolioheatmap", "portfolioallocation",
)
FORBIDDEN_TEXT = (
    "/root/", "data/portfolio", "data/private", "private_local_only", "broker_access_token",
    "rhs_account_number", "current rh net", "dry powder", "goal gap",
)
PUBLIC_PATH_PREFIXES = (
    "/root/synthetic-wiki/",
    "/root/synthetic-dashboard/",
)

# Every top-level source section must be named here.  Projection never spreads an
# arbitrary source object into the snapshot root.
PUBLIC_SECTIONS = (
    "counts", "actionBuckets", "topTags", "categoryCounts", "marketPosture",
    "macroRegimeMeter",
    "dailyJournal", "cronTimeline",
    "intradayEquityWatchdog", "marketGraphs", "currentAsymmetricShortlist",
    "aiProjectionExhibits", "aiWarRoomCompleteData", "sources", "tickers",
)
CRITICAL_SECTIONS = ("tickers", "marketPosture", "currentAsymmetricShortlist", "marketGraphs")
SECTION_THRESHOLDS_SECONDS = {
    "tickers": 7 * 86400,
    "marketPosture": 36 * 3600,
    "currentAsymmetricShortlist": 36 * 3600,
    "marketGraphs": 36 * 3600,
    "aiProjectionExhibits": 36 * 3600,
    "aiWarRoomCompleteData": 36 * 3600,
}
SECTION_PRODUCERS = {
    "aiProjectionExhibits": "synthetic-job-0b",
    "aiWarRoomCompleteData": "synthetic-job-06",
}
METER_PILLARS = (
    ("trend_breadth", "Trend & breadth", 25),
    ("liquidity_financial_conditions", "Liquidity & financial conditions", 20),
    ("credit", "Credit", 15),
    ("growth_earnings", "Growth & earnings", 15),
    ("inflation_policy", "Inflation & policy", 15),
    ("volatility_positioning", "Volatility & positioning", 10),
)
METER_BAND_LABELS = {
    "risk_off": "Risk off",
    "defensive": "Defensive",
    "neutral_mixed": "Neutral / mixed",
    "selective_risk_on": "Selective risk on",
    "constructive": "Constructive",
    "broad_risk_on": "Broad risk on",
    "unavailable": "Unavailable",
}
METER_SOURCE_IDS = {
    "tradermonty.market_breadth", "tradermonty.rsp_spy_proxy", "tradermonty.iwm_spy_proxy",
    "tradermonty.hyg_lqd_proxy", "tradermonty.shy_tlt_proxy",
}
METER_UNAVAILABLE_REASONS = {
    "trend_breadth": "Current complete structured breadth inputs are unavailable",
    "liquidity_financial_conditions": "No robust current structured daily series",
    "credit": "Current HYG/LQD proxy is unavailable",
    "growth_earnings": "No robust current structured daily series",
    "inflation_policy": "Current SHY/TLT proxy is unavailable",
    "volatility_positioning": "Current structured VIX or sentiment history is unavailable",
}
METER_POSTURES = {'risk_off': 'Preserve risk capacity; require unusually strong proof for new exposure.', 'defensive': 'Keep risk constrained and favor resilience while conditions remain fragile.', 'neutral_mixed': 'Keep sizing selective; wait for broader confirmation before adding risk.', 'selective_risk_on': 'Risk is permitted selectively, with confirmation and disciplined sizing.', 'constructive': 'Conditions support measured risk-taking while normal controls remain in place.', 'broad_risk_on': 'Broad risk participation is supported; retain normal concentration controls.', 'unavailable': 'Insufficient current structured evidence to set macro risk permission.'}

METER_DRIVERS = {
    "Breadth health plus RSP/SPY and IWM/SPY participation percentiles",
    "HYG/LQD percentile proxy",
    "SHY/TLT percentile proxy, inverted because a rising ratio implies duration pressure",
}
METER_HEALTH_REASONS = {None, "missing", "Canonical artifact was not supplied", "Canonical artifact is missing or unreadable", "Canonical artifact is not an object", "Canonical artifact failed its closed contract", "Canonical artifact failed its semantic privacy and vocabulary contract"}
METER_PATH_PATTERN = '^(?![\\s\\S]*[\\x00-\\x20\\x7f])(?!.*[Pp][Rr][Ii][Vv][Aa][Tt][Ee])(?!.*[Aa][Cc][Cc][Oo][Uu][Nn][Tt])(?!.*[Pp][Oo][Rr][Tt][Ff][Oo][Ll][Ii][Oo])(?!.*[Pp][Nn][Ll])(?!.*[Rr][Oo][Bb][Ii][Nn][Hh][Oo][Oo][Dd])(?!.*[Cc][Oo][Ss][Tt][_-]?[Bb][Aa][Ss][Ii][Ss])(?!.*[Dd][Rr][Yy][_-]?[Pp][Oo][Ww][Dd][Ee][Rr])(?!.*[Gg][Oo][Aa][Ll][_-]?[Gg][Aa][Pp])(?!.*\\.\\.)[A-Za-z0-9_-]+(?:[.][A-Za-z0-9_-]+)*(?:/[A-Za-z0-9_-]+(?:[.][A-Za-z0-9_-]+)*)*$'
METER_INPUTS = {
    "trend_breadth": (["Breadth health plus RSP/SPY and IWM/SPY participation percentiles"], ["tradermonty.market_breadth", "tradermonty.rsp_spy_proxy", "tradermonty.iwm_spy_proxy"]),
    "credit": (["HYG/LQD percentile proxy"], ["tradermonty.hyg_lqd_proxy"]),
    "inflation_policy": (["SHY/TLT percentile proxy, inverted because a rising ratio implies duration pressure"], ["tradermonty.shy_tlt_proxy"]),
}


def _meter_dates(value):
    if isinstance(value, list):
        return all(_meter_dates(item) for item in value)
    if not isinstance(value, dict):
        return True
    for key, item in value.items():
        if key in {"asOf", "comparisonAsOf", "generatedAt"} and item is not None:
            if not isinstance(item, str):
                return False
            pattern = r"[0-9]{4}-[0-9]{2}-[0-9]{2}" if key != "generatedAt" else r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})"
            if not re.fullmatch(pattern, item):
                return False
            try:
                if key == "generatedAt":
                    datetime.fromisoformat(item.replace("Z", "+00:00"))
                    if int(item[11:13]) > 23 or int(item[14:16]) > 59 or int(item[17:19]) > 59 or (item[-1] != "Z" and (int(item[-5:-3]) > 23 or int(item[-2:]) > 59)):
                        return False
                else:
                    date.fromisoformat(item)
            except ValueError:
                return False
        if not _meter_dates(item):
            return False
    return True


def _meter_band_possible(score, band, daily):
    bands = list(METER_BAND_LABELS)[:-1]
    bounds = [(1, 2.9), (3, 4.4), (4.5, 5.9), (6, 7.4), (7.5, 8.9), (9, 10)]
    index = bands.index(band)
    low, high = bounds[index]
    if low <= score <= high:
        return True
    if daily.get("status") != "available":
        return False
    prior = score - daily["value"]
    # A confirmed adjacent band may persist for the two tenths at its edge.
    return low - .2 - 1e-8 <= score <= high + .2 + 1e-8 and low - .2 - 1e-8 <= prior <= high + .2 + 1e-8


MARKET_SESSION_SECTIONS = {
    "marketPosture", "currentAsymmetricShortlist", "marketGraphs", "aiProjectionExhibits",
}


class PrivacyError(ValueError):
    pass


class MixedGenerationError(RuntimeError):
    pass


def unavailable_macro_regime_meter(reason: str) -> dict[str, Any]:
    change = {"status": "unavailable", "value": None, "comparisonAsOf": None}
    pillars = [
        {"id": identifier, "label": label, "score": None, "weight": weight, "direction": "unavailable",
         "confidence": "unavailable", "freshnessStatus": "unavailable", "asOf": None, "drivers": [],
         "sourceIds": [], "eligibility": False, "reason": METER_UNAVAILABLE_REASONS[identifier]}
        for identifier, label, weight in METER_PILLARS
    ]
    return {
        "schemaVersion": 1, "methodologyVersion": "macro-regime-meter-v1", "generatedAt": None, "asOf": None,
        "score": None, "regimeBand": "unavailable", "regimeLabel": "Unavailable", "direction": "unavailable",
        "dailyChange": dict(change), "weeklyChange": dict(change), "confidence": "unavailable",
        "freshnessStatus": "unavailable", "postureInterpretation": "Insufficient current structured evidence to set macro risk permission.",
        "positiveDrivers": [], "negativeDrivers": [], "pillars": pillars,
        "sourceHealth": {"status": "fail_closed", "eligibleWeight": 0, "minimumEligibleWeight": 55,
                         "totalWeight": 100, "unavailablePillars": [item[0] for item in METER_PILLARS],
                         "sources": [], "reason": reason if reason in METER_HEALTH_REASONS else "Canonical artifact is missing or unreadable"},
        "history": [],
    }


def _nfc(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_nfc(v) for v in value]
    if isinstance(value, tuple):
        return [_nfc(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, value in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized = unicodedata.normalize("NFC", key)
            if normalized in out:
                raise ValueError(f"NFC key collision: {normalized!r}")
            out[normalized] = _nfc(value)
        return out
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN and Infinity are forbidden in canonical JSON")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """UTF-8/NFC, sorted keys, compact JSON, and exactly one trailing LF."""
    text = json.dumps(
        _nfc(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


def snapshot_id(body: dict[str, Any]) -> str:
    forbidden = {"snapshotId", "builtAt", "publishedAt"}.intersection(body)
    if forbidden:
        raise ValueError(f"immutable snapshot body contains manifest-only fields: {sorted(forbidden)}")
    return "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def validate_public_snapshot_schema(body: dict[str, Any]) -> None:
    """Validate the production DTO against the checked-in Draft 2020-12 contract."""
    from jsonschema import Draft202012Validator, FormatChecker
    from decimal import Decimal

    schema_path = Path(__file__).resolve().parents[1] / "schema" / "public-snapshot-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # Exact decimal tenths belong only to the meter contract.
    schema["properties"]["macroRegimeMeter"] = json.loads(json.dumps(schema["properties"]["macroRegimeMeter"]), parse_float=Decimal)
    from referencing import Registry, Resource
    from public_content import SCHEMA as content_schema
    registry = Registry().with_resource(content_schema["$id"], Resource.from_contents(content_schema))
    validator = Draft202012Validator(schema, format_checker=FormatChecker(), registry=registry)
    validation_body = {**body}
    if "macroRegimeMeter" in body:
        validation_body["macroRegimeMeter"] = json.loads(json.dumps(body["macroRegimeMeter"]), parse_float=Decimal)
    errors = sorted(validator.iter_errors(validation_body), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "$"
        raise ValueError(f"public snapshot schema violation at {location}: {first.message}")
    validate_macro_regime_meter_semantics(body.get("macroRegimeMeter"))


def _key_token(key: str) -> str:
    return "".join(c for c in key.casefold() if c.isalnum())


def _public_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PrivacyError("non-finite number in public DTO")
        return value
    if isinstance(value, str):
        value = unicodedata.normalize("NFC", value)
        lowered = value.casefold()
        for marker in FORBIDDEN_TEXT:
            if marker in lowered:
                raise PrivacyError(f"forbidden private/path marker {marker!r} in public DTO value")
        return value
    raise PrivacyError(f"unsupported public DTO scalar: {type(value).__name__}")


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.casefold()
        return any(marker in lowered for marker in FORBIDDEN_TEXT)
    if isinstance(value, list):
        return any(_contains_forbidden_text(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_forbidden_text(item) for item in value.values())
    return False


def validate_macro_regime_meter_semantics(value: Any) -> None:
    """Reject contradictory or non-canonical meter claims before projection."""
    if not isinstance(value, dict) or type(value.get("schemaVersion")) is not int or value.get("schemaVersion") != 1 or value.get("methodologyVersion") != "macro-regime-meter-v1":
        raise PrivacyError("macroRegimeMeter has invalid identity")
    if _contains_forbidden_text(value):
        raise PrivacyError("macroRegimeMeter contains a forbidden private/path marker")
    if not isinstance(value.get("regimeBand"), str):
        raise PrivacyError("macroRegimeMeter band must be a string")
    if not _meter_dates(value):
        raise PrivacyError("macroRegimeMeter date is invalid")
    if value.get("postureInterpretation") != METER_POSTURES.get(value.get("regimeBand")):
        raise PrivacyError("macroRegimeMeter posture vocabulary is non-canonical")
    for field in ("positiveDrivers", "negativeDrivers"):
        if not isinstance(value.get(field), list) or any(driver not in METER_DRIVERS for driver in value[field]):
            raise PrivacyError(f"macroRegimeMeter {field} vocabulary is non-canonical")

    pillars = value.get("pillars")
    if not isinstance(pillars, list) or len(pillars) != len(METER_PILLARS):
        raise PrivacyError("macroRegimeMeter must contain exactly six pillars")
    for item, (identifier, label, weight) in zip(pillars, METER_PILLARS):
        if not isinstance(item, dict) or (item.get("id"), item.get("label"), item.get("weight")) != (identifier, label, weight):
            raise PrivacyError("macroRegimeMeter pillar identity, label, or weight is non-canonical")
        eligible = item.get("eligibility") is True
        score = item.get("score")
        if not isinstance(item.get("drivers"), list) or any(driver not in METER_DRIVERS for driver in item["drivers"]):
            raise PrivacyError("macroRegimeMeter driver vocabulary is non-canonical")
        if eligible:
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 1 <= score <= 10 or round(score, 1) != score:
                raise PrivacyError("eligible macroRegimeMeter pillar score is invalid")
            if item.get("direction") not in {"supportive", "mixed", "restrictive"} or item.get("freshnessStatus") != "current" or not isinstance(item.get("asOf"), str):
                raise PrivacyError("eligible macroRegimeMeter pillar state is contradictory")
            expected_confidence = "medium" if identifier == "trend_breadth" else "low"
            if item.get("confidence") != expected_confidence:
                raise PrivacyError("macroRegimeMeter proxy confidence is non-canonical")
            expected_direction = "supportive" if score >= 6 else "restrictive" if score < 4.5 else "mixed"
            if item.get("direction") != expected_direction or identifier not in METER_INPUTS or (item.get("drivers"), item.get("sourceIds")) != METER_INPUTS[identifier]:
                raise PrivacyError("macroRegimeMeter pillar semantics are contradictory")
            if item.get("reason") is not None:
                raise PrivacyError("eligible macroRegimeMeter pillar cannot have an unavailable reason")
        elif not (score is None and item.get("direction") == "unavailable" and item.get("confidence") == "unavailable"
                  and item.get("freshnessStatus") == "unavailable" and item.get("asOf") is None
                  and item.get("drivers") == [] and item.get("sourceIds") == []
                  and item.get("reason") == METER_UNAVAILABLE_REASONS[identifier]):
            raise PrivacyError("unavailable macroRegimeMeter pillar state is contradictory")

    source_health = value.get("sourceHealth")
    if not isinstance(source_health, dict):
        raise PrivacyError("macroRegimeMeter source health is missing")
    eligible_pillars = [item for item in pillars if item.get("eligibility") is True]
    unavailable_ids = [item["id"] for item in pillars if item.get("eligibility") is not True]
    eligible_weight = sum(item["weight"] for item in eligible_pillars)
    if (source_health.get("eligibleWeight") != eligible_weight or source_health.get("minimumEligibleWeight") != 55
            or source_health.get("totalWeight") != 100 or source_health.get("unavailablePillars") != unavailable_ids):
        raise PrivacyError("macroRegimeMeter source-health totals are contradictory")
    sources = source_health.get("sources")
    if not isinstance(sources, list) or any(not isinstance(source, dict) or source.get("id") not in METER_SOURCE_IDS
                                            or not isinstance(source.get("path"), str) for source in sources):
        raise PrivacyError("macroRegimeMeter source vocabulary is invalid")
    if source_health.get("reason") not in METER_HEALTH_REASONS or any(not re.fullmatch(METER_PATH_PATTERN, source["path"]) for source in sources):
        raise PrivacyError("macroRegimeMeter provenance is unsafe")
    resolved = [source["id"] for source in sources]
    if len(resolved) != len(set(resolved)):
        raise PrivacyError("macroRegimeMeter source IDs must be unique")
    if any(source_id not in resolved for item in pillars for source_id in item.get("sourceIds", [])):
        raise PrivacyError("macroRegimeMeter pillar source ID is unresolved")

    if set(resolved) != {source for item in pillars for source in item["sourceIds"]}:
        raise PrivacyError("macroRegimeMeter sources do not match eligible inputs")
    for field, predicate in (("positiveDrivers", lambda score: score >= 6), ("negativeDrivers", lambda score: score < 4.5)):
        if value[field] != [item["drivers"][0] for item in eligible_pillars if predicate(item["score"])][:3]:
            raise PrivacyError("macroRegimeMeter aggregate drivers are contradictory")
    score = value.get("score")
    band = value.get("regimeBand")
    if band not in METER_BAND_LABELS or value.get("regimeLabel") != METER_BAND_LABELS[band]:
        raise PrivacyError("macroRegimeMeter band vocabulary is invalid")
    if score is None:
        if not (eligible_weight < 55 and band == "unavailable" and value.get("direction") == "unavailable"
                and value.get("confidence") == "unavailable" and value.get("freshnessStatus") == "unavailable"
                and source_health.get("status") == "fail_closed"):
            raise PrivacyError("unavailable macroRegimeMeter state is contradictory")
    else:
        if (not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 1 <= score <= 10
                or round(score, 1) != score or eligible_weight < 55 or band == "unavailable" or not isinstance(value.get("generatedAt"), str)
                or value.get("confidence") not in {"low", "medium", "high"} or value.get("freshnessStatus") != "current"
                or source_health.get("status") != "pass"):
            raise PrivacyError("available macroRegimeMeter state is contradictory")
        if score != round(sum(item["score"] * item["weight"] for item in eligible_pillars) / eligible_weight, 1):
            raise PrivacyError("macroRegimeMeter weighted score is contradictory")
        if value.get("confidence") != ("medium" if eligible_weight >= 70 else "low"):
            raise PrivacyError("macroRegimeMeter confidence is contradictory")
        eligible_dates = [item.get("asOf") for item in eligible_pillars]
        if not eligible_dates or value.get("asOf") != min(eligible_dates):
            raise PrivacyError("macroRegimeMeter asOf is not the oldest eligible observation")

    for field in ("dailyChange", "weeklyChange"):
        change = value.get(field)
        if not isinstance(change, dict) or change.get("status") not in {"available", "unavailable"}:
            raise PrivacyError(f"macroRegimeMeter {field} is invalid")
        available = change.get("status") == "available"
        if available != (isinstance(change.get("value"), (int, float)) and not isinstance(change.get("value"), bool)
                         and math.isfinite(change["value"]) and isinstance(change.get("comparisonAsOf"), str)):
            raise PrivacyError(f"macroRegimeMeter {field} availability is contradictory")
        if not available and (change.get("value") is not None or change.get("comparisonAsOf") is not None):
            raise PrivacyError(f"macroRegimeMeter {field} unavailable fields must be null")
        if available and (score is None or not -9 <= change["value"] <= 9 or round(change["value"], 1) != change["value"] or not 1 - 1e-8 <= score - change["value"] <= 10 + 1e-8 or change["comparisonAsOf"] >= value["asOf"]):
            raise PrivacyError("macroRegimeMeter comparison is impossible")
    daily = value.get("dailyChange")
    if score is not None and not _meter_band_possible(score, band, daily):
        raise PrivacyError("macroRegimeMeter score and band are contradictory")
    expected_direction = "unavailable" if daily.get("status") == "unavailable" else (
        "steady" if abs(round(float(daily["value"]), 1)) < 0.2 else "improving" if daily["value"] > 0 else "deteriorating")
    history = value.get("history")
    if not isinstance(history, list) or len(history) > 40:
        raise PrivacyError("macroRegimeMeter history bounds are invalid")
    for row in history:
        if (not isinstance(row, dict) or set(row) != {"asOf", "score", "regimeBand", "generatedAt", "methodologyVersion"}
                or not isinstance(row.get("score"), (int, float)) or isinstance(row["score"], bool)
                or not math.isfinite(row["score"]) or not 1 <= row["score"] <= 10 or round(row["score"], 1) != row["score"]
                or row.get("methodologyVersion") != "macro-regime-meter-v1" or row.get("regimeBand") not in list(METER_BAND_LABELS)[:-1]
                or not isinstance(row.get("asOf"), str) or not isinstance(row.get("generatedAt"), str)):
            raise PrivacyError("macroRegimeMeter history observation is invalid")
        bounds = [(1, 3.1), (2.8, 4.6), (4.3, 6.1), (5.8, 7.6), (7.3, 9.1), (8.8, 10)]
        low, high = bounds[list(METER_BAND_LABELS).index(row["regimeBand"])]
        if not low <= row["score"] <= high:
            raise PrivacyError("macroRegimeMeter history score and band are contradictory")
    if value.get("direction") != expected_direction:
        raise PrivacyError("macroRegimeMeter direction contradicts daily comparison")


def _normalize_known_public_paths(value: Any) -> Any:
    """Make canonical Wiki/dashboard citations host-neutral in narrative sections."""
    if isinstance(value, str):
        for prefix in PUBLIC_PATH_PREFIXES:
            value = value.replace(prefix, "")
        return value
    if isinstance(value, list):
        return [_normalize_known_public_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_known_public_paths(item) for key, item in value.items()}
    return value


def _normalize_section_order(section: str, value: Any) -> Any:
    """Sort only arrays whose contract is explicitly set-like; preserve ranked arrays."""
    if section == "dailyJournal" and isinstance(value, list):
        days: list[Any] = []
        for source in value:
            if not isinstance(source, dict):
                days.append(source)
                continue
            day = dict(source)
            tickers = day.get("interestingTickers")
            if isinstance(tickers, list):
                day["interestingTickers"] = sorted(
                    tickers,
                    key=lambda row: str(row.get("symbol", "")) if isinstance(row, dict) else str(row),
                )
            if isinstance(day.get("sourceTypes"), list):
                day["sourceTypes"] = sorted(day["sourceTypes"], key=str)
            days.append(day)
        return days
    if section == "tickers" and isinstance(value, list):
        rows: list[Any] = []
        for source in value:
            if isinstance(source, dict) and isinstance(source.get("tags"), list):
                source = {**source, "tags": sorted(source["tags"], key=str)}
            rows.append(source)
        return rows
    if section == "sources" and isinstance(value, list):
        return [
            {**row, "examples": sorted(row.get("examples", []), key=str)}
            if isinstance(row, dict) and isinstance(row.get("examples"), list) else row
            for row in value
        ]
    return value


def _public_market_graphs(value: Any) -> list[dict[str, Any]]:
    """Build a graph DTO without carrying private nodes or derived claims."""
    if not isinstance(value, list):
        return []
    allowed = {
        "workflowId", "label", "runId", "generatedAt", "finalGate", "recommendation",
        "allowedNodes", "blockedNodes", "selfHealSummary", "brokerSafetyFindings",
        "contradictions", "tickers", "themes", "nodeCount", "passCount", "degradedCount",
        "failCount", "marketClosedCarryCount", "pipelineStaleCount", "decisionEventCount",
        "slackWorthyEventCount", "graphNodes", "graphEdges", "decisionEvents",
    }
    graphs: list[dict[str, Any]] = []
    for source in value:
        if not isinstance(source, dict):
            continue
        privacy = [source[k] for k in ("privacy_class", "privacyClass") if k in source]
        if not privacy or any(tag not in ("public", "public_ok") for tag in privacy):
            continue
        graph = {key: source[key] for key in allowed if key in source}
        from public_graph_structure import project_graph_structure
        nodes = source.get("graphNodes")
        # Keep excluded identities only inside this local copy so incident edges
        # can be removed, rather than surviving as dangling public dependencies.
        topology_source = dict(source)
        if isinstance(nodes, list):
            topology_source["graphNodes"] = [
                {**node, "privacy_class": "private"} if isinstance(node, dict) and _contains_forbidden_text(node) else node
                for node in nodes
            ]
        graph.update(project_graph_structure(topology_source))
        events = graph.get("decisionEvents")
        if isinstance(events, list):
            graph["decisionEvents"] = [
                event for event in events
                if isinstance(event, dict)
                and str(event.get("privacy_class", event.get("privacyClass", ""))) in {"public", "public_ok"}
                and not _contains_forbidden_text(event)
            ]
        graphs.append(graph)
    return graphs


S = "scalar"
SL = ("list", S)
NM = ("map", S)

DETAIL = {"title": S, "summary": S, "bullets": SL}
ACTION = {"symbol": S, "action": S, "details": SL}
JOURNAL_ITEM = {"title": S, "sourceType": S, "sourcePath": S, "summary": S,
                "highlights": SL, "goldSilver": SL, "actionCallouts": ("list", ACTION),
                "marketNarrative": {"title": S, "bullets": SL}}
GRAPH_NODE = {"id": S, "label": S, "kind": S, "status": S, "freshness": S,
              "freshnessContext": S, "pipelineStale": S, "allowedIntoSynthesis": S,
              "reason": S, "outputPath": S, "sourceCount": S, "healActions": SL}
GRAPH_EVENT = {"id": S, "workflowId": S, "runId": S, "gate": S, "scope": S,
               "decision": S, "proof": SL, "blockedBy": SL, "sourcePaths": SL,
               "slackWorthy": S, "severity": S, "generatedAt": S}
GRAPH = {key: S for key in ("workflowId label runId generatedAt finalGate recommendation nodeCount passCount "
                             "degradedCount failCount marketClosedCarryCount pipelineStaleCount "
                             "decisionEventCount slackWorthyEventCount").split()}
GRAPH.update({key: SL for key in ("allowedNodes blockedNodes selfHealSummary brokerSafetyFindings contradictions tickers themes").split()})
GRAPH.update({"graphNodes": ("list", GRAPH_NODE), "graphEdges": ("list", {"from": S, "to": S, "status": S}),
              "decisionEvents": ("list", GRAPH_EVENT)})
TICKER = {key: S for key in ("symbol title updated created sourcePath summary fullSummary status actionBucket isStub category "
                              "exchange tradingViewSymbol thesis catalyst risk shortlistGroup shortlistRank shortlistRec "
                              "shortlistStatus shortlistThesis shortlistRisk trigger entryPoint researchTier tierReviewed tierReason").split()}
TICKER.update({"tags": SL, "detailSections": ("list", DETAIL)})
SHORTLIST_EVENT = {"kind": S, "sourcePath": S, "generatedAt": S, "summary": S}
SHORTLIST_CHANGE = {key: S for key in ("symbol changeType fromBucket toBucket headline action freshness returnRole "
                                        "whyThisHelps50to100 opportunityCost slackWorthy generatedAt expiresAt").split()}
MEMBERSHIP_CHANGE = {key: S for key in ("symbol changeType fromBucket toBucket fromAction toAction fromFreshness toFreshness").split()}
MEMBERSHIP_CHANGE["changedFields"] = SL
MEMBERSHIP_POLICY = {"bucketMode": S, "description": S, "bucketOrder": SL}
MEMBERSHIP_RUN = {key: S for key in ("builder scheduledOwner generatedAt previousGeneratedAt status rowCount changedCount unchangedCount").split()}
MEMBERSHIP_RUN.update({"addedSymbols": SL, "removedSymbols": SL})
MEMBERSHIP_AUTOMATION = {key: S for key in ("jobName schedule enabled lastStatus lastRunAt nextRunAt health").split()}
MEMBERSHIP_NODE = {key: S for key in ("id label stage kind status schedule lastRunAt nextRunAt detail").split()}
MEMBERSHIP_NODE["artifacts"] = SL
MEMBERSHIP_WORKFLOW = {
    "generatedAt": S,
    "status": S,
    "coverageNote": S,
    "nodes": ("list", MEMBERSHIP_NODE),
    "edges": ("list", {"from": S, "to": S, "label": S}),
}
SHORTLIST_ROW = {key: S for key in ("symbol bucket bucketReason rank state upsideClass proofLevel entry currentPrice quoteAsOf "
                                     "entryZoneLow entryZoneHigh entryZoneCurrency entryZoneAsOf entryStatus entryReason entryEligible "
                                     "proofTrigger killTrigger whyNotNow freshness freshnessReason decisionExpiration tickerUpdated tickerAgeDays "
                                     "eventAgeDays priceAgeDays capitalEligible tier returnRole targetContribution timeToMatter "
                                     "actionMode whyThisHelps50to100 opportunityCost capitalPriority privateSizingHidden "
                                     "researchTier tierReviewed tierReason").split()}
SHORTLIST_ROW["latestEvent"] = SHORTLIST_EVENT
DECISION_RECEIPT = {key: S for key in ("id recordedAt symbol decision decisionState researchTier thesis entry proofTrigger "
                                               "killTrigger sizeClass decisionExpiration decisionQuote quoteAsOf fundingClass "
                                               "completeness recordReason").split()}
DECISION_RECEIPT["missingFields"] = SL
DECISION_EXCEPTION = {key: S for key in ("id symbol classification question status sourceReceiptId nextReviewEvent lessonCandidate").split()}
DECISION_OUTCOME = {key: S for key in ("receiptId sourceReceiptId symbol receiptDecision priorDecision currentDecision state status "
                                       "classification observedAt returnPct reviewReason reason supersededBy").split()}
DECISION_EXCEPTION_CANDIDATE = {key: S for key in ("id symbol classification question status sourceReceiptId observedAt severity "
                                                   "priorDecision currentDecision nextReviewEvent lessonCandidate returnPct").split()}
DECISION_LEARNING = {key: S for key in ("generatedAt policy receiptCount newReceiptCount integrityGapCount openExceptionCount "
                                               "outcomeCount reviewDueCount candidateExceptionCount policyRuleCount "
                                               "adoptedPolicyRuleCount unlinkedPolicyRuleCount casebookCount casebookPolicy").split()}
DECISION_LEARNING.update({
    "recentReceipts": ("list", DECISION_RECEIPT),
    "openExceptions": ("list", DECISION_EXCEPTION),
    "recentOutcomes": ("list", DECISION_OUTCOME),
    "exceptionCandidates": ("list", DECISION_EXCEPTION_CANDIDATE),
    "handoffs": {key: S for key in "canonicalState capitalBoard warRoom weeklyIc casebook dashboard outcomes policyRules".split()},
})
PROJECTION_CASE = {key: S for key in "revenueCagrPct terminalMultiple impliedPrice upsidePct proofNeeded".split()}
PROJECTION_ROW = {key: S for key in ("symbol companyName archetype benchmarkGroup sourcePage inclusionReason price marketCap "
                                      "enterpriseValue quoteAsOf ltmRevenue ntmRevenue ntmRevenueGrowthPct evNtmRevenue peNtm "
                                      "evEbitdaNtm fcfMarginPct sectorPercentile ownHistoryPercentile valuationSignal "
                                      "relativeValueScore dataQualityLabel dataQualityScore multiBagPlausibility mainBottleneck "
                                      "warRoomAction capitalEligibleFromProjection fundamentalsSource fundamentalsAsOf "
                                      "researchTier tierReviewed tierReason instrumentRisk").split()}
PROJECTION_ROW.update({"missingCriticalFields": SL, "bear": PROJECTION_CASE, "base": PROJECTION_CASE, "bull": PROJECTION_CASE})
WAR_ROOM_ROW = {key: S for key in ("symbol primaryTicker companyName exchange currency price quoteAsOf dayChangePct oneMonthChangePct "
                                    "threeMonthChangePct ytdChangePct marketCap enterpriseValue ltmRevenue ntmRevenueEstimate "
                                    "revenueGrowthPct fy1RevenueGrowthPct fy2RevenueGrowthPct grossMarginPct operatingMarginPct "
                                    "fcfMarginPct epsNtm cash debt evRevenue evNtmRevenue peNtm evEbitda relativePeerValuation "
                                    "backlogOrdersRpo customerProof insiderFlow macroTape proofLevel action actionDelta starterZone "
                                    "addZone killZone nextCatalystCheckDate sizeFrame dataQualityLabel sourceFreshness sma20 sma50 sma200").split()}
WAR_ROOM_ROW.update({key: S for key in "researchTier tierReviewed tierReason instrumentRisk".split()})
WAR_ROOM_ROW.update({"missingCriticalFields": SL, "sourcePaths": SL})
CHART_ROW = {key: S for key in ("symbol archetype action dataQualityLabel valuationSignal plausibility threeX fiveX tenX "
                                 "baseUpsidePct bullUpsidePct evNtmRevenue ntmRevenueGrowthPct ownHistoryPercentile base bear bull "
                                 "currentPrice currentMultiple dataQualityScore growthPct sectorPercentile marketCap proofLevel "
                                 "revenueGrowthPct researchTier tierReviewed tierReason instrumentRisk").split()}

SECTION_SPECS: dict[str, Any] = {
    "counts": {key: S for key in "tickers researched stubs reports convictionItems journalDays".split()},
    "actionBuckets": {key: S for key in "buy_add hold wait_watch avoid_trim unclassified".split()},
    "topTags": ("list", ("tuple", (S, S))),
    "categoryCounts": NM,
    "marketPosture": ("list", {"name": S, "sourcePath": S, "score": S, "zone": S, "delta": S,
                                "artifactDate": S, "freshnessStatus": S, "plainTitle": S, "plainEnglish": S,
                                "watch": SL, "history": ("list", {"date": S, "score": S, "zone": S, "sourcePath": S})}),
    "macroRegimeMeter": {
        "schemaVersion": S, "methodologyVersion": S, "generatedAt": S, "asOf": S, "score": S,
        "regimeBand": S, "regimeLabel": S, "direction": S,
        "dailyChange": {"status": S, "value": S, "comparisonAsOf": S},
        "weeklyChange": {"status": S, "value": S, "comparisonAsOf": S},
        "confidence": S, "freshnessStatus": S, "postureInterpretation": S,
        "positiveDrivers": SL, "negativeDrivers": SL,
        "pillars": ("list", {"id": S, "label": S, "score": S, "weight": S, "direction": S,
                              "confidence": S, "freshnessStatus": S, "asOf": S, "drivers": SL,
                              "sourceIds": SL, "eligibility": S, "reason": S}),
        "sourceHealth": {"status": S, "eligibleWeight": S, "minimumEligibleWeight": S,
                           "totalWeight": S, "unavailablePillars": SL,
                           "sources": ("list", {"id": S, "path": S}), "reason": S},
        "history": ("list", {"asOf": S, "score": S, "regimeBand": S, "generatedAt": S,
                                "methodologyVersion": S}),
    },

    "dailyJournal": ("list", {"date": S, "headline": S, "summary": S, "marketNarrative": {"title": S, "bullets": SL},
                               "portfolioActions": ("list", {"symbol": S, "stance": S, "text": S}), "keyTakeaways": SL,
                               "actionCallouts": ("list", ACTION), "goldSilver": SL,
                               "interestingTickers": ("list", {"symbol": S, "why": S, "hasResearch": S, "changePct": S, "direction": S}),
                               "items": ("list", JOURNAL_ITEM), "sourceTypes": SL}),
    "cronTimeline": ("list", {key: (SL if key == "highlights" else S) for key in "id jobId jobName runTime schedule deliver category sourcePath summary highlights articleBody".split()}),
    "intradayEquityWatchdog": {**{key: S for key in "last_check_utc monitored_count dashboard_hit_count review_candidate_count slack_policy summary sourcePath".split()},
                                "sources": SL, "monitored_symbols": SL,
                                "top_hits": ("list", {**{key: S for key in "symbol action trigger price pct_today wiki_level technical_quality technical_note bucket context text".split()}, "source_lists": SL}),
                                "review_candidates": ("list", {**{key: S for key in "symbol action trigger price pct_today wiki_level technical_quality technical_note bucket context text".split()}, "source_lists": SL})},
    "marketGraphs": ("list", GRAPH),
    "currentAsymmetricShortlist": {"generatedAt": S, "policy": S, "summary": NM, "regime": NM,
                                    "actionChanges": ("list", SHORTLIST_CHANGE),
                                    "membershipPolicy": MEMBERSHIP_POLICY,
                                    "runSummary": MEMBERSHIP_RUN,
                                    "membershipChanges": ("list", MEMBERSHIP_CHANGE),
                                    "automation": MEMBERSHIP_AUTOMATION,
                                    "membershipWorkflow": MEMBERSHIP_WORKFLOW,
                                    "rows": ("list", SHORTLIST_ROW),
                                    "decisionLearning": DECISION_LEARNING},
    "aiProjectionExhibits": {"generatedAt": S, "artifactDate": S, "policy": S, "privacyClass": S, "rowCount": S,
                              "excludedDiscoveredCount": S, "sourcePaths": SL,
                              "summary": {"dataQuality": NM, "valuationSignals": NM, "capitalEligibleCount": S, "degradedOrMissingCount": S},
                              "rows": ("list", PROJECTION_ROW), "chartData": ("map", ("list", CHART_ROW)), "artifactPaths": ("map", S)},
    "aiWarRoomCompleteData": {"generatedAt": S, "rowCount": S, "manifest": {key: S for key in "completed pending errors total".split()},
                               "summary": {"actions": NM, "dataQuality": NM}, "sourcePaths": SL,
                               "rows": ("list", WAR_ROOM_ROW), "chartData": ("map", ("list", CHART_ROW))},
    "sources": ("list", {"name": S, "role": S, "summary": S, "examples": SL, "howUsed": S}),
    "tickers": ("list", TICKER),
}


def _project_with_spec(value: Any, spec: Any, *, section: str) -> Any:
    if spec == S:
        return _public_scalar(value)
    if isinstance(spec, tuple):
        kind, child_spec = spec
        if kind == "list":
            if not isinstance(value, (list, tuple)):
                return []
            rows = []
            for item in value:
                if isinstance(item, dict):
                    privacy = item.get("privacy_class", item.get("privacyClass"))
                    if privacy not in (None, "", "public", "public_ok"):
                        continue
                rows.append(_project_with_spec(item, child_spec, section=section))
            return rows
        if kind == "tuple":
            if not isinstance(value, (list, tuple)) or len(value) != len(child_spec):
                return []
            return [_project_with_spec(item, item_spec, section=section) for item, item_spec in zip(value, child_spec)]
        if kind == "map":
            if not isinstance(value, dict):
                return {}
            return {str(key): _project_with_spec(item, child_spec, section=section) for key, item in sorted(value.items())}
    if isinstance(spec, dict):
        if value is None:
            return None
        if not isinstance(value, dict):
            return {}
        privacy = value.get("privacy_class", value.get("privacyClass"))
        if privacy not in (None, "", "public", "public_ok"):
            raise PrivacyError(f"non-public object reached {section} DTO")
        out = {}
        unknown_keys = set(value).difference(spec).difference({"privacy_class", "privacyClass"})
        for key in unknown_keys:
            if _contains_forbidden_text(value[key]):
                raise PrivacyError(f"forbidden private/path marker in unknown {section}.{key} claim")
        for key in sorted(set(value).intersection(spec)):
            token = _key_token(str(key))
            if any(fragment in token for fragment in FORBIDDEN_KEY_FRAGMENTS):
                continue
            out[key] = _project_with_spec(value[key], spec[key], section=section)
        return out
    raise PrivacyError(f"invalid structural projection spec for {section}")


def project_dto(value: Any, *, section: str) -> Any:
    """Project a section through its recursive allowlist; unknown claims are dropped."""
    if section not in SECTION_SPECS:
        raise PrivacyError(f"unknown public section: {section}")
    if section == "macroRegimeMeter":
        validate_macro_regime_meter_semantics(value)
    projected = _project_with_spec(value, SECTION_SPECS[section], section=section)
    if section == "macroRegimeMeter" and projected != value:
        raise PrivacyError("macroRegimeMeter must match its closed DTO without rewriting")
    if section == "currentAsymmetricShortlist" and isinstance(projected, dict):
        learning = projected.get("decisionLearning")
        if isinstance(learning, dict):
            learning["recentOutcomes"] = (learning.get("recentOutcomes") or [])[:6]
            learning["exceptionCandidates"] = [
                row for row in (learning.get("exceptionCandidates") or [])
                if isinstance(row, dict) and str(row.get("status") or "").lower() == "candidate"
            ][:3]
    return projected


def _parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _iso_from_ns(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1_000_000_000, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _section_as_of(value: Any, fallback: str | None = None) -> str | None:
    candidates: list[datetime] = []
    timestamp_keys = {"dataAsOf", "artifactDate", "quoteAsOf", "generatedAt", "generated_at",
                      "lastCheckUtc", "last_check_utc", "updated", "created", "date", "informationAt", "informationDate"}
    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in timestamp_keys:
                    parsed = _parse_timestamp(child)
                    if parsed:
                        candidates.append(parsed)
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(node, list):
            for child in node[:500]:
                visit(child)
    visit(value)
    if candidates:
        return max(candidates).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return fallback


def _jobs_by_id(cron_root: Path) -> dict[str, dict[str, Any]]:
    for candidate in (cron_root / "jobs.json", cron_root.parent / "jobs.json"):
        if not candidate.exists():
            continue
        try:
            obj = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        jobs = obj.get("jobs", obj) if isinstance(obj, dict) else obj
        if isinstance(jobs, list):
            return {str(j.get("id")): j for j in jobs if isinstance(j, dict) and j.get("id")}
        if isinstance(jobs, dict):
            return {str(k): v for k, v in jobs.items() if isinstance(v, dict)}
    return {}


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    cursor = next_month - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _us_market_holidays(year: int) -> set[date]:
    return {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(year, 6, 19),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
        _observed_fixed_holiday(year + 1, 1, 1),
    }


def _is_us_market_session(day: date) -> bool:
    return day.weekday() < 5 and day not in _us_market_holidays(day.year)


def _expected_market_session_date(reference: datetime) -> date:
    eastern = reference.astimezone(ZoneInfo("America/New_York"))
    day = eastern.date()
    if _is_us_market_session(day) and eastern.time() >= datetime_time(9, 30):
        return day
    day -= timedelta(days=1)
    while not _is_us_market_session(day):
        day -= timedelta(days=1)
    return day


def _section_is_stale(name: str, reference: datetime | None, artifact: datetime | None, threshold: int) -> bool:
    if reference is None or artifact is None:
        return False
    if artifact > reference + timedelta(minutes=5):
        return True
    if (reference - artifact).total_seconds() <= threshold:
        return False
    if name in MARKET_SESSION_SECTIONS and artifact.date() >= _expected_market_session_date(reference):
        return False
    return True


def build_source_health(sections: dict[str, Any], *, data_as_of: str | None, cron_root: Path) -> dict[str, Any]:
    jobs = _jobs_by_id(cron_root)
    reference = _parse_timestamp(data_as_of)
    rows: dict[str, Any] = {}
    stale: list[str] = []
    missing: list[str] = []
    for name in PUBLIC_SECTIONS:
        value = sections.get(name)
        present = value is not None and value != [] and value != {}
        # A section without a represented timestamp is unknown, not magically as
        # fresh as the newest unrelated section in the snapshot.
        artifact_ts = _section_as_of(value)
        threshold = SECTION_THRESHOLDS_SECONDS.get(name, 7 * 86400)
        artifact_dt = _parse_timestamp(artifact_ts)
        is_stale = _section_is_stale(name, reference, artifact_dt, threshold)
        if not present:
            missing.append(name)
        elif is_stale:
            stale.append(name)
        job_id = SECTION_PRODUCERS.get(name)
        job = jobs.get(job_id or "", {})
        state_obj = job.get("state") if isinstance(job.get("state"), dict) else {}
        state_name = job.get("state") if isinstance(job.get("state"), str) else ""
        latest_status = (
            "paused" if state_name == "paused" else
            state_obj.get("lastStatus") or state_obj.get("last_status") or
            job.get("lastStatus") or job.get("last_status") or
            ("not_applicable" if not job_id else "unknown")
        )
        last_success = (
            state_obj.get("lastSuccessAt") or state_obj.get("last_success_at") or
            job.get("lastSuccessAt") or job.get("last_success_at")
        )
        if last_success is None and latest_status in {"ok", "pass", "success"}:
            last_success = job.get("last_run_at") or job.get("lastRunAt")
        validation = "pass" if present else "fail"
        usable_lkg = bool(present and validation == "pass")
        status = "fail" if not present else "degraded" if is_stale or latest_status in {"error", "failed", "paused"} else "pass"
        rows[name] = {
            "status": status,
            "dataAsOf": artifact_ts,
            "producer": {"jobId": job_id, "latestStatus": latest_status, "lastSuccessAt": last_success},
            "artifactTimestamp": artifact_ts,
            "validation": validation,
            "usableLastKnownGood": usable_lkg,
            "stalenessThresholdSeconds": threshold,
        }
    critical_statuses = [rows[name]["status"] for name in CRITICAL_SECTIONS]
    global_status = "fail" if "fail" in critical_statuses else "degraded" if "degraded" in critical_statuses else "pass"
    return {"status": global_status, "criticalSections": list(CRITICAL_SECTIONS), "staleSections": stale, "missingSections": missing, "sections": rows}


def _project_public_sections(raw: dict[str, Any]) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    for section in PUBLIC_SECTIONS:
        source = raw.get(section)
        if section == "marketGraphs":
            source = _public_market_graphs(source)
        elif section in {"cronTimeline", "tickers"}:
            source = _normalize_known_public_paths(source)
        source = _normalize_section_order(section, source)
        sections[section] = project_dto(source, section=section)
    return sections


def build_public_snapshot(raw: dict[str, Any], *, data_as_of: str, cron_root: Path,
                          previous_publications: list | None = None, diagnostics: list | None = None) -> dict[str, Any]:
    diagnostics = [] if diagnostics is None else diagnostics
    # Sanitize BEFORE legacy structural projection as well as shared publications.
    # Keep private originals outside all public serialization paths.
    # Validate topology before generic prose cleaning can remove its identities.
    # Only already-public graphs receive this structural preparation.
    meter = raw.get("macroRegimeMeter")
    if meter is None or meter == {}:
        meter = unavailable_macro_regime_meter("Canonical artifact was not supplied")
    prepared = {**{key: value for key, value in raw.items() if key != 'macroRegimeMeter'},
                'marketGraphs': [{**graph, 'privacy_class': 'public_ok'} for graph in _public_market_graphs(raw.get('marketGraphs'))]}
    sanitized = sanitize_legacy(prepared, diagnostics=diagnostics)
    # The numeric DTO is validated by project_dto and the final schema, never
    # prose-cleaned. The legacy prose sanitizer would rewrite stable IDs
    # such as ``risk_off`` and ``unavailable`` into display copy.
    sanitized['macroRegimeMeter'] = meter
    sections = _project_public_sections(sanitized)
    native_rows = raw.get('publications') or []
    if not isinstance(native_rows,list):
        diagnostics.append({'recordId':'unidentified','code':'records-not-array'})
        native_rows=[]
    native_ids = {r['id'] for r in native_rows if isinstance(r,dict) and isinstance(r.get('id'),str)}
    legacy_previous = [r for r in (previous_publications or []) if isinstance(r,dict) and r.get('id') not in native_ids]
    publications = merge_publications(
        [*adapt_legacy(raw, diagnostics, previous=legacy_previous), *native_rows],
        previous_publications or [], diagnostics,
    )
    tickers = sections.get("tickers") or []
    ticker_ids = {str(row.get("symbol", "")).upper() for row in tickers if isinstance(row, dict)}
    raw_focus = raw.get("focusTickers") or []
    ordered_ids: list[str] = []
    for item in raw_focus:
        symbol = item.get("symbol") if isinstance(item, dict) else item
        symbol = str(symbol or "").upper()
        if symbol and symbol in ticker_ids and symbol not in ordered_ids:
            ordered_ids.append(symbol)
    body = {
        "schemaVersion": SCHEMA_VERSION,
        "dataAsOf": data_as_of,
        "refreshMode": "runtime-manifest",
        **sections,
        "publications": publications,
        "focusTickers": ordered_ids,
    }
    body["sourceHealth"] = build_source_health(sections, data_as_of=data_as_of, cron_root=cron_root)
    body["privacy"] = {
        "classification": "public",
        "projection": "structural-allowlist-v1",
        "excluded": ["broker accounts", "positions", "weights", "cost basis", "P&L", "private graph nodes"],
        "note": "Public structural projection; private portfolio and account data excluded before synthesis.",
    }
    # Canonical serialization is also the final non-finite/key-collision check.
    encoded = canonical_json_bytes(body)
    if len(encoded) > MAX_BYTES:
        sizes = {key: len(canonical_json_bytes(value)) for key, value in body.items()}
        largest = sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:6]
        raise ValueError(f"public snapshot exceeds {MAX_BYTES} bytes ({len(encoded)}); largest sections={largest}")
    return body


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    dev: int
    ino: int
    size: int
    mtime_ns: int
    sha256: str


def input_inventory(roots: Iterable[Path]) -> tuple[InventoryEntry, ...]:
    entries: list[InventoryEntry] = []
    suffixes = {".json", ".md", ".csv", ".yaml", ".yml", ".txt"}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.casefold() in suffixes), key=lambda p: str(p)):
            try:
                stat = path.stat()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                stat2 = path.stat()
            except OSError:
                continue
            # A file changing while it is fingerprinted guarantees mismatch.
            if (stat.st_size, stat.st_mtime_ns) != (stat2.st_size, stat2.st_mtime_ns):
                digest = "CHANGING:" + digest
            entries.append(InventoryEntry(str(path.resolve()), stat2.st_dev, stat2.st_ino, stat2.st_size, stat2.st_mtime_ns, digest))
    return tuple(entries)


def stable_build(builder: Callable[[], dict[str, Any]], roots: Iterable[Path], *, attempts: int = 2) -> tuple[dict[str, Any], tuple[InventoryEntry, ...]]:
    roots = tuple(roots)
    for _ in range(attempts):
        before = input_inventory(roots)
        raw = builder()
        after = input_inventory(roots)
        if before == after:
            return raw, after
    raise MixedGenerationError("source inventory changed during both projection attempts; prior output left intact")


def inventory_data_as_of(inventory: tuple[InventoryEntry, ...]) -> str:
    return _iso_from_ns(max((entry.mtime_ns for entry in inventory), default=0))


def represented_data_as_of(
    raw: dict[str, Any],
    inventory: tuple[InventoryEntry, ...],
    *,
    trusted_roots: Iterable[Path],
) -> str:
    """Newest declared timestamp or trusted file actually represented in ``raw``.

    Global inventory churn remains useful for mixed-generation detection, but it
    must not advance public freshness unless the changed artifact is cited by a
    projected section.
    """
    candidates: list[datetime] = []
    referenced: set[str] = set()
    timestamp_keys = {"dataAsOf", "artifactDate", "quoteAsOf", "generatedAt", "generated_at",
                      "lastCheckUtc", "last_check_utc", "updated", "created", "date", "informationAt", "informationDate"}
    path_keys = {"sourcePath", "sourcePaths", "outputPath", "artifactPaths", "checkerPath",
                 "finalPath", "decisionEventsPath", "fundamentalsSource"}

    def visit(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            if key in path_keys:
                for child in node.values():
                    visit(child, key)
                return
            for child_key, child in node.items():
                if child_key in timestamp_keys:
                    parsed = _parse_timestamp(child)
                    if parsed:
                        candidates.append(parsed)
                if child_key in path_keys:
                    visit(child, child_key)
                elif isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child, key)
        elif key in path_keys and isinstance(node, str) and node:
            referenced.add(node)

    # Projection first ensures excluded/private/unknown source material cannot
    # contribute a freshness timestamp either.
    sanitized = sanitize_legacy({key: value for key, value in raw.items() if key != 'macroRegimeMeter'})
    meter = raw.get("macroRegimeMeter")
    sanitized["macroRegimeMeter"] = unavailable_macro_regime_meter("Canonical artifact was not supplied") if meter is None or meter == {} else meter
    visit(_project_public_sections(sanitized))
    visit(merge_publications(raw.get("publications") or [], [], []))
    inventory_by_path = {entry.path: entry for entry in inventory}
    roots = tuple(root.resolve() for root in trusted_roots)
    for citation in referenced:
        citation_path = Path(citation)
        paths = [citation_path.resolve()] if citation_path.is_absolute() else [(root / citation_path).resolve() for root in roots]
        for path in paths:
            if not any(path == root or root in path.parents for root in roots):
                continue
            entry = inventory_by_path.get(str(path))
            if entry:
                candidates.append(datetime.fromtimestamp(entry.mtime_ns / 1_000_000_000, timezone.utc))
    if not candidates:
        raise ValueError("public snapshot has no represented trusted freshness timestamp")
    return max(candidates).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_bytes(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return False
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True


def scan_public_assets(roots: Iterable[Path]) -> list[str]:
    errors: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root)
            if path.name.casefold() in DENIED_PUBLIC_FILENAMES:
                errors.append(f"denied public filename: {root.name}/{rel}")
            if path.suffix.casefold() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace").casefold()
            except OSError as exc:
                errors.append(f"cannot scan {path}: {exc}")
                continue
            if path.suffix.casefold() == '.json':
                try:
                    candidate = json.loads(path.read_text(encoding='utf-8'))
                    if isinstance(candidate,dict) and {'schemaVersion','dataAsOf','tickers'} <= candidate.keys():
                        validate_public_snapshot_schema(candidate)
                        assert_public_suitability(candidate)
                except (ValueError, TypeError):
                    errors.append(f"public snapshot suitability failed: {root.name}/{rel}")
            for marker in FORBIDDEN_TEXT:
                if marker in text:
                    errors.append(f"forbidden marker {marker!r}: {root.name}/{rel}")
    return errors
