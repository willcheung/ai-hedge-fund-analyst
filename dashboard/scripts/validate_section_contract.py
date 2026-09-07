#!/usr/bin/env python3
"""Fail fast when MarketWiki dataset registration drifts across backend contracts."""
from __future__ import annotations

import json
import argparse
import os
from pathlib import Path
from typing import Any

from public_snapshot import (
    CRITICAL_SECTIONS,
    PUBLIC_SECTIONS,
    SECTION_PRODUCERS,
    SECTION_SPECS,
    SECTION_THRESHOLDS_SECONDS,
)

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_SCHEMA = ROOT / "schema" / "public-snapshot-v1.schema.json"
WIKI_SNAPSHOT_SCHEMA = ROOT / "schema" / "staged-wiki-public-snapshot-v1.schema.json"
SNAPSHOT_ENVELOPE_FIELDS = {
    "schemaVersion",
    "dataAsOf",
    "refreshMode",
    "focusTickers",
    "sourceHealth",
    "privacy",
    "publications",
}


def section_contract_errors(schema: dict[str, Any]) -> list[str]:
    """Return actionable errors for every duplicated section boundary."""
    errors: list[str] = []
    registered = set(PUBLIC_SECTIONS)
    projected = set(SECTION_SPECS)
    root_properties = set(schema.get("properties", {}))
    schema_sections = root_properties - SNAPSHOT_ENVELOPE_FIELDS
    root_required = set(schema.get("required", []))

    source_health = schema.get("properties", {}).get("sourceHealth", {})
    health_sections_schema = source_health.get("properties", {}).get("sections", {})
    health_properties = set(health_sections_schema.get("properties", {}))
    health_required = set(health_sections_schema.get("required", []))

    comparisons = (
        ("PUBLIC_SECTIONS vs SECTION_SPECS", registered, projected),
        ("PUBLIC_SECTIONS vs snapshot schema dataset properties", registered, schema_sections),
        ("PUBLIC_SECTIONS vs sourceHealth.sections properties", registered, health_properties),
        ("PUBLIC_SECTIONS vs sourceHealth.sections required", registered, health_required),
    )
    for label, expected, actual in comparisons:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            errors.append(f"{label}: missing={missing}, extra={extra}")

    not_required = sorted(registered - root_required)
    if not_required:
        errors.append(f"snapshot schema root required is missing registered sections: {not_required}")

    for label, configured in (
        ("CRITICAL_SECTIONS", set(CRITICAL_SECTIONS)),
        ("SECTION_THRESHOLDS_SECONDS", set(SECTION_THRESHOLDS_SECONDS)),
        ("SECTION_PRODUCERS", set(SECTION_PRODUCERS)),
    ):
        unknown = sorted(configured - registered)
        if unknown:
            errors.append(f"{label} contains unregistered sections: {unknown}")

    duplicates = sorted({name for name in PUBLIC_SECTIONS if PUBLIC_SECTIONS.count(name) > 1})
    if duplicates:
        errors.append(f"PUBLIC_SECTIONS contains duplicates: {duplicates}")
    return errors


def mirror_schema_errors(primary: dict[str, Any], mirror: dict[str, Any]) -> list[str]:
    """Require the dashboard and Wiki copies of the public contract to stay identical."""
    if primary == mirror:
        return []
    return [
        "dashboard and Wiki public snapshot schemas differ; update both copies in the same dataset change"
    ]


def validate_section_contract(schema_path: Path = SNAPSHOT_SCHEMA) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = section_contract_errors(schema)
    if errors:
        detail = "\n - ".join(errors)
        raise ValueError(
            "MarketWiki section contract drift detected. Update the local section registry and both snapshot schemas:\n"
            f" - {detail}"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-schema", default=os.environ.get("MARKETS_WIKI_SCHEMA"),
                        help="Explicit integration schema (or MARKETS_WIKI_SCHEMA); defaults to the checked-in mirror")
    parser.add_argument("--integration", action="store_true",
                        help="Require an explicit --wiki-schema or MARKETS_WIKI_SCHEMA")
    args = parser.parse_args(argv)
    if args.integration and args.wiki_schema is None:
        parser.error("integration check requires --wiki-schema or MARKETS_WIKI_SCHEMA")
    try:
        validate_section_contract()
        # Always validate both checked-in contracts, even during integration checks.
        mirrors = [WIKI_SNAPSHOT_SCHEMA]
        if args.wiki_schema is not None:
            if not args.wiki_schema.strip():
                raise ValueError("explicit integration schema path is empty")
            mirrors.append(Path(args.wiki_schema))
        for mirror_path in mirrors:
            primary = json.loads(SNAPSHOT_SCHEMA.read_text(encoding="utf-8"))
            mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
            errors = mirror_schema_errors(primary, mirror)
            if errors:
                raise ValueError(f"{mirror_path}: {errors[0]}")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc))
        return 1
    print(f"MarketWiki section contract valid ({len(PUBLIC_SECTIONS)} datasets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
