#!/usr/bin/env python3
"""Fail when deployable dashboard assets violate the public privacy boundary."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from public_snapshot import scan_public_assets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="*", default=["public", "dist"])
    args = parser.parse_args(argv)
    errors = scan_public_assets(Path(root).resolve() for root in args.roots)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"public asset privacy scan passed ({', '.join(args.roots)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
