#!/usr/bin/env python3
"""Hermes monitor_script entrypoint for the shared ticker event-trigger fleet."""
from __future__ import annotations
from automation_paths import configured_text

import subprocess
import sys

COLLECTOR = configured_text("${ANALYST_WIKI_ROOT}/_tools/ticker_event_monitor.py")
CONTRACTS_DIR = configured_text("${ANALYST_WIKI_ROOT}/data/automation/event_triggers")


def main() -> int:
    completed = subprocess.run(
        [sys.executable, COLLECTOR, "--contracts-dir", CONTRACTS_DIR],
        check=False,
        text=True,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
