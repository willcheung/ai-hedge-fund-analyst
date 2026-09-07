#!/usr/bin/env python3
"""Failure-only wrapper for wiki-market Phase 1 graph workflows.

Cron/no-agent behavior:
- Always writes graph artifacts under ${ANALYST_WIKI_ROOT}/data/automation/graph_runs/.
- Prints nothing when all workflow gates pass (silent success).
- Prints a concise alert when a workflow is degraded/fail or an exception occurs.
"""
from __future__ import annotations
from automation_paths import configured_text

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(configured_text("${ANALYST_WIKI_ROOT}"))
RUNNER = ROOT / "_tools/graph_phase1_runner.py"
WORKFLOWS = ["market_research_cio_dashboard", "earnings_proof_gate"]


def load_runner():
    tools_dir = str(RUNNER.parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    spec = importlib.util.spec_from_file_location("graph_phase1_runner", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["graph_phase1_runner"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    run_id = dt.datetime.now(dt.timezone.utc).strftime("cron_%Y-%m-%d_%H%M%SZ")
    try:
        runner = load_runner()
        summaries = []
        for wf in WORKFLOWS:
            path = ROOT / "docs/graph-engineering-phase1/workflows" / f"{wf}.yaml"
            summaries.append(runner.run_workflow(ROOT, path, run_id=run_id))
    except Exception as exc:
        print("🚨 Market Graph Phase 1 runner crashed")
        print(f"run_id: {run_id}")
        print(f"error: {type(exc).__name__}: {exc}")
        return 2

    slack_events = []
    for s in summaries:
        for event in s.get("decision_events", []) or []:
            if event.get("slackWorthy"):
                slack_events.append((s, event))
    if slack_events:
        print("🚨 Market Graph checker found Slack-worthy failure events")
        print(f"run_id: {run_id}")
        for s, event in slack_events[:8]:
            print(f"- {s['workflow_id']}: gate={event.get('gate')} scope={event.get('scope')} decision={event.get('decision')}")
        print("All graph artifacts were written locally; inspect decision_events.json and checker_report.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
