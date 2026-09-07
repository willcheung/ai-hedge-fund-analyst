#!/usr/bin/env python3
"""Hermes cron wrapper for wiki-market AI projection exhibits."""
from __future__ import annotations
from automation_paths import configured_text

import json
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(configured_text("${ANALYST_WIKI_ROOT}"))
REQUIRED_MODULES = ("yfinance",)


def missing_dependencies() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def dependency_error(missing: list[str]) -> str:
    modules = " ".join(missing)
    return (
        f"Missing required Python module(s): {', '.join(missing)}. "
        f"Install into this interpreter with: uv pip install --python {sys.executable} {modules}"
    )


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        print(proc.stdout, end="")
        raise SystemExit(proc.returncode)
    return proc.stdout


def main() -> int:
    missing = missing_dependencies()
    if missing:
        print(json.dumps({"status": "error", "stage": "dependency_preflight", "error": dependency_error(missing)}, indent=2))
        return 2
    fundamentals_output = run(["python3", "_tools/research_ai_projection_fundamentals.py", "--write"])
    output = run(["python3", "_tools/ai_projection_exhibits.py", "--write"])
    run(["python3", "_tools/build_index.py"])
    run(["python3", "_tools/wiki_lint.py"])
    try:
        summary = json.loads(output)
    except Exception:
        summary = {"raw": output.strip()}
    try:
        fundamentals_summary = json.loads(fundamentals_output)
    except Exception:
        fundamentals_summary = {"raw": fundamentals_output.strip()}
    print(json.dumps({"status": "ok", "job": "AI Projection Exhibits Builder", "fundamentals": fundamentals_summary, "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
