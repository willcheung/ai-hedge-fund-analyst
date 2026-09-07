#!/usr/bin/env python3
"""Stage test-only data for the synthetic publications dashboard, entirely offline.

From dashboard/ (after installing the declared Python dependencies):
    python3 scripts/stage_demo.py --output-dir /tmp/analyst-demo-data

Existing datasets are refused; asset-only directories are allowed. Copy its
contents into a disposable built site's document root to serve /wiki-data.json,
/market-data/manifest.json and /market-data/snapshots/<hash>.json. For example,
copy dashboard/dist into a new /tmp/analyst-demo-site, overlay the staged data,
then run python3 -m http.server 4173 --bind 127.0.0.1 --directory that site.
Use --scenario missing in another fresh directory for empty-input smoke tests.

Only synthetic constants and checked-in schemas are used. No generator, publisher,
credentials, jobs, wiki, external schema, network calls or live runtime are used.
All demo data URLs are relative local asset URLs; no remote service is contacted.
Do not deploy this fixture or treat its fixed dates as market freshness.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import public_snapshot as ps

SCENARIOS = ("degraded", "missing")
AS_OF = "2000-01-20T00:00:00Z"
STALE_AS_OF = "2000-01-01T00:00:00Z"
SYMBOL = "DEMO-NOTREAL"
NOTICE = "SYNTHETIC DEMO — TEST ONLY. Not market research or investment advice."



def demo_raw(scenario: str) -> dict[str, Any]:
    """Small hand-authored fixture: no quotes, forecasts, trades or real issuers."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown demo scenario: {scenario}")
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/demo-dashboard.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    if scenario == "missing":
        for key in ("tickers", "focusTickers", "publications", "marketPosture", "dailyJournal", "cronTimeline", "marketGraphs", "sources", "topTags"):
            raw[key] = []
        for key in ("currentAsymmetricShortlist", "aiProjectionExhibits", "aiWarRoomCompleteData", "intradayEquityWatchdog"):
            raw[key] = None
        raw["counts"] = dict.fromkeys(raw["counts"], 0)
        raw["actionBuckets"] = dict.fromkeys(raw["actionBuckets"], 0)
        raw["categoryCounts"] = {}
    return raw


def build_demo(scenario: str = "degraded") -> tuple[dict[str, Any], dict[str, Any]]:
    """Build and validate before any destination writes; timestamps are fixed."""
    from jsonschema import Draft202012Validator, FormatChecker

    raw = demo_raw(scenario)
    # Projection can withhold malformed scalars. Reject invalid demo counters
    # first, so a broken fixture cannot stage data the client would reject.
    counts = raw.get("counts")
    required_counts = ("tickers", "researched", "stubs", "reports", "convictionItems", "journalDays")
    if not isinstance(counts, dict) or any(
        type(counts.get(key)) is not int or not 0 <= counts[key] <= 9007199254740991
        for key in required_counts
    ):
        raise ValueError("demo counts must contain nonnegative safe integers for all required counters")
    # The health builder checks both cron_root and its parent for jobs.json.
    # Give it a nested directory in a freshly allocated sandbox, never HOME.
    with tempfile.TemporaryDirectory(prefix="analyst-demo-input-", dir="/tmp") as td:
        cron_root = Path(td) / "empty-cron"
        cron_root.mkdir()
        body = ps.build_public_snapshot(raw, data_as_of=AS_OF, cron_root=cron_root)
    body["privacy"]["note"] = NOTICE + " " + body["privacy"]["note"]
    ps.validate_public_snapshot_schema(body)
    payload = ps.canonical_json_bytes(body)
    identity = ps.snapshot_id(body)
    digest = identity.removeprefix("sha256:")
    snapshot_path = f"marketwiki/snapshots/{digest}.json"
    url = f"./market-data/snapshots/{digest}.json"
    manifest = {
        "schemaVersion": ps.SCHEMA_VERSION, "snapshotId": identity, "snapshotPath": snapshot_path,
        "snapshotUrl": url, "objectSha256": digest, "byteLength": len(payload),
        "builtAt": AS_OF, "publishedAt": AS_OF, "sourceMaxAsOf": AS_OF,
        "sourceHealth": body["sourceHealth"],
        "projectionStatus": {"status": "pass", "note": NOTICE + " Schema validation only; not research health."},
        "currentSnapshotId": identity, "currentSnapshotUrl": url,
        "previousSnapshotId": None, "previousSnapshotUrl": None, "history": [],
    }
    schema = json.loads((Path(__file__).resolve().parents[1] / "schema/demo-manifest-v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)
    return body, manifest


def stage_demo(output_dir: Path, *, scenario: str = "degraded", refresh: bool = False) -> dict[str, Any]:
    """Stage into a local asset root; refuse existing datasets or symlinked paths."""
    output_dir = Path(os.path.abspath(output_dir))
    if any(path.is_symlink() for path in (output_dir, *output_dir.parents)):
        raise ValueError("demo destination must not contain symlinks")
    for relative in ("wiki-data.json", "market-data", "market-data/snapshots"):
        if (output_dir / relative).is_symlink():
            raise ValueError("demo dataset paths must not contain symlinks")
    body, manifest = build_demo(scenario)
    payload = ps.canonical_json_bytes(body)
    manifest_bytes = ps.canonical_json_bytes(manifest)
    expected = {
        "wiki-data.json": payload,
        "market-data/manifest.json": manifest_bytes,
        f"market-data/snapshots/{manifest['objectSha256']}.json": payload,
    }
    if (output_dir / "wiki-data.json").exists() or (output_dir / "market-data").exists():
        existing = list((output_dir / "market-data").rglob("*"))
        if refresh and not any(p.is_symlink() for p in existing) and all(
            not (output_dir / name).is_symlink() and (output_dir / name).is_file()
            and (output_dir / name).read_bytes() == content for name, content in expected.items()
        ) and {str(p.relative_to(output_dir)) for p in existing if p.is_file()} == set(expected) - {"wiki-data.json"}:
            return manifest
        raise FileExistsError("demo dataset already exists and is not an identical synthetic build")
    # Scan generated bytes before exposing the destination. Never scan live assets.
    with tempfile.TemporaryDirectory(prefix="analyst-demo-scan-", dir="/tmp") as td:
        scan_root = Path(td)
        (scan_root / "wiki-data.json").write_bytes(payload)
        (scan_root / "manifest.json").write_bytes(manifest_bytes)
        errors = ps.scan_public_assets([scan_root])
        if errors:
            raise ps.PrivacyError("; ".join(errors))
    output_dir.mkdir(parents=True, exist_ok=True)
    ps.atomic_write_bytes(output_dir / "wiki-data.json", payload)
    ps.atomic_write_bytes(output_dir / "market-data/snapshots" / f"{manifest['objectSha256']}.json", payload)
    # Manifest last: the client cannot discover the snapshot until it exists.
    ps.atomic_write_bytes(output_dir / "market-data/manifest.json", manifest_bytes)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", required=True, type=Path, help="Local asset directory without wiki-data.json or market-data")
    parser.add_argument("--scenario", choices=SCENARIOS, default="degraded")
    parser.add_argument("--refresh", action="store_true", help="Reuse only byte-identical synthetic data; never overwrite another dataset")
    args = parser.parse_args(argv)
    try:
        manifest = stage_demo(args.output_dir, scenario=args.scenario, refresh=args.refresh)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"demo staging failed: {exc}\n")
    print(f"{NOTICE}\nStaged {args.scenario}: {manifest['snapshotId']}\n"
          f"Source health: {manifest['sourceHealth']['status']}; destination: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
