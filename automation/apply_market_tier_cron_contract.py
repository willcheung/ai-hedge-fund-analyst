#!/usr/bin/env python3
"""Idempotently add the canonical research-tier contract to market cron prompts."""
from __future__ import annotations
from automation_paths import configured_text

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

JOBS_PATH = Path(configured_text("${ANALYST_JOBS_FILE}"))
MARKER = "## CANONICAL RESEARCH TIER CONTRACT"
CONTRACT = """
## CANONICAL RESEARCH TIER CONTRACT
Whenever this job evaluates, ranks, sizes, or updates an individual ticker:
1. Read `tickers/<TICKER>.md` and preserve the three separate axes: `research_tier` (`core-long`, `speculative`, or `highly-speculative`), action state (Scout/Add/Hold/Wait/Trim/Kill), and instrument risk (common/ETF/option/margin/hedge).
2. Include the current tier in capital-decision output and state `unchanged` or the evidence-backed old -> new transition.
3. Change tier only on business/thesis proof (orders/backlog/revenue, margins/FCF, customer breadth, financing durability, catalyst completion, or thesis failure), never on price/social momentum alone.
4. If tier changes, update `research_tier`, current `tier_reviewed`, and concise `tier_reason` in ticker frontmatter in the same run; run `_tools/apply_research_tiers.py --rollup --check`, `_tools/propagate_research_tiers.py --apply --json`, `_tools/build_index.py`, and `_tools/wiki_lint.py` where the job has file/terminal access; then verify both ticker page and rollup.
5. If this job creates ticker-specific child or one-shot jobs, copy this tier contract into their prompts.
If this run has no individual ticker decision, no tier mutation is required. Never expose private account values in public artifacts.
""".strip()

MARKET_SKILL_PARTS = (
    "market", "trading", "earnings", "research", "stock", "ticker",
    "proof-gate", "deep-research", "morning-market", "gold-futures",
)


def job_id(job: dict) -> str:
    return str(job.get("id") or job.get("job_id") or "")


def is_market_agent(job: dict) -> bool:
    if job.get("no_agent") or job.get("state") == "completed":
        return False
    prompt = str(job.get("prompt") or "")
    skills = job.get("skills") or ([job.get("skill")] if job.get("skill") else [])
    return bool(
        job.get("workdir") == configured_text("${ANALYST_WIKI_ROOT}")
        or configured_text("${ANALYST_WIKI_ROOT}") in prompt
        or any(any(part in str(skill) for part in MARKET_SKILL_PARTS) for skill in skills)
    )


def load() -> tuple[dict, list[dict]]:
    data = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise SystemExit("Unexpected jobs.json schema")
    return data, jobs


def atomic_write(data: dict) -> None:
    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="jobs.tier.", suffix=".json", dir=JOBS_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, JOBS_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data, jobs = load()
    scoped = [job for job in jobs if is_market_agent(job)]
    missing = [job for job in scoped if MARKER not in str(job.get("prompt") or "")]
    changed = 0
    if args.apply:
        for job in missing:
            job["prompt"] = str(job.get("prompt") or "").rstrip() + "\n\n" + CONTRACT + "\n"
            changed += 1
        if changed:
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            atomic_write(data)
        data, jobs = load()
        scoped = [job for job in jobs if is_market_agent(job)]
        missing = [job for job in scoped if MARKER not in str(job.get("prompt") or "")]
    payload = {
        "jobs_total": len(jobs),
        "market_agent_jobs": len(scoped),
        "changed": changed,
        "covered": len(scoped) - len(missing),
        "missing": [{"id": job_id(j), "name": j.get("name")} for j in missing],
        "covered_jobs": [{"id": job_id(j), "name": j.get("name"), "enabled": bool(j.get("enabled"))} for j in scoped if MARKER in str(j.get("prompt") or "")],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"market tier cron contract: {payload['covered']}/{payload['market_agent_jobs']} covered; {changed} changed")
        for row in payload["missing"]:
            print(f"MISSING {row['id']} {row['name']}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
