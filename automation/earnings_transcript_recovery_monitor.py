#!/usr/bin/env python3
"""Stable monitor source for the bounded earnings-transcript recovery pilot.

The graph runner owns the request file. This script emits only canonical state:
unchanged gaps are scheduler-suppressed, so one gap cannot repeatedly launch agents.
"""
from __future__ import annotations
from automation_paths import configured_text

import json
from pathlib import Path

REQUEST = Path(configured_text("${ANALYST_WIKI_ROOT}/data/automation/graph_runs/earnings_proof_gate/transcript_recovery_request.json"))
ALLOWED_KEYS = (
    "schema_version",
    "workflow_id",
    "node_id",
    "needed",
    "actionable",
    "request_id",
    "request_hash",
    "request_fingerprint",
    "event_key",
    "ticker",
    "period",
    "reason",
    "freshness_status",
    "event_source_path",
    "source_paths",
    "expected_transcript_path",
    "expected_verification_path",
    "attempt_budget",
    "max_recovered_transcripts",
    "require_actual_transcript_text",
    "require_material_claim_verification",
)


def main() -> int:
    try:
        payload = json.loads(REQUEST.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        print(json.dumps({"needed": False, "workflow_id": "earnings_proof_gate"}, sort_keys=True))
        return 0
    if not payload.get("needed"):
        print(json.dumps({"needed": False, "workflow_id": "earnings_proof_gate"}, sort_keys=True))
        return 0
    stable = {key: payload[key] for key in ALLOWED_KEYS if key in payload}
    print(json.dumps(stable, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
