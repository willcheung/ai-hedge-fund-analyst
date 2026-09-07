#!/usr/bin/env python3
"""
Gold Sentiment Scanner — thin wrapper around gold_trader.py.

The original gold_sentiment.py was a prototype scanner with a buggy
options put/call parser and duplicated logic. The full functionality
(plus correct options parsing, ATR, news LLM classification, ladder
generation, etc.) now lives in gold_trader.py — this file is kept for
backwards-compat with cron jobs that invoke it directly.

Usage (same as before):
    python3 gold_sentiment.py --brief
    python3 gold_sentiment.py --json
    python3 gold_sentiment.py
"""

import os
import sys

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(here, "gold_trader.py")
    if not os.path.exists(target):
        sys.stderr.write(f"gold_trader.py not found at {target}\n")
        sys.exit(1)
    os.execv(sys.executable, [sys.executable, target] + sys.argv[1:])
