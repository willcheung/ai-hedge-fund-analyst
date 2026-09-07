#!/usr/bin/env python3
"""Stop CalConviction pilot-only posting lanes at the pilot boundary."""

from __future__ import annotations
from automation_paths import configured_text

import argparse
import json
import subprocess
from pathlib import Path

JOBS_PATH = Path(configured_text("${ANALYST_HERMES_HOME}")) / "cron" / "jobs.json"
from private_config import load_private_json
TARGETS = load_private_json("ANALYST_JOB_TARGETS_FILE")
if not TARGETS or any(not isinstance(k, str) or not isinstance(v, str) for k, v in TARGETS.items()):
    raise ValueError("ANALYST_JOB_TARGETS_FILE requires an explicit job ID to label mapping")



def load_jobs() -> dict[str, dict]:
    payload = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    jobs = payload.get("jobs", payload) if isinstance(payload, dict) else payload
    if isinstance(jobs, list):
        return {
            str(job.get("id") or job.get("job_id")): job
            for job in jobs
            if job.get("id") or job.get("job_id")
        }
    if isinstance(jobs, dict):
        return {str(job_id): job for job_id, job in jobs.items()}
    raise ValueError("Unsupported jobs.json structure")


def is_enabled(job: dict) -> bool:
    return bool(job.get("enabled", False)) and job.get("state") != "paused"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate targets without changing cron state.",
    )
    args = parser.parse_args()

    before = load_jobs()
    missing = [job_id for job_id in TARGETS if job_id not in before]
    if missing:
        print(json.dumps({"status": "error", "missing_job_ids": missing}))
        return 1

    if args.check:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "mode": "check",
                    "targets": [
                        {
                            "job_id": job_id,
                            "lane": lane,
                            "enabled": is_enabled(before[job_id]),
                        }
                        for job_id, lane in TARGETS.items()
                    ],
                },
                sort_keys=True,
            )
        )
        return 0

    results = []
    for job_id, lane in TARGETS.items():
        if not is_enabled(before[job_id]):
            results.append({"job_id": job_id, "lane": lane, "action": "already_paused"})
            continue
        result = subprocess.run(
            ["hermes", "cron", "pause", job_id],
            text=True,
            capture_output=True,
            check=False,
        )
        results.append(
            {
                "job_id": job_id,
                "lane": lane,
                "action": "pause",
                "returncode": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
        )

    after = load_jobs()
    still_enabled = [job_id for job_id in TARGETS if is_enabled(after[job_id])]
    status = "ok" if not still_enabled else "error"
    print(
        json.dumps(
            {
                "status": status,
                "pilot_only_lanes_paused": not still_enabled,
                "still_enabled": still_enabled,
                "results": results,
            },
            sort_keys=True,
        )
    )
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
