#!/usr/bin/env python3
"""Static capability gate: package metadata only, no application imports or jobs."""
import argparse
import importlib.metadata
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'capabilities.json').read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capability', choices=sorted(config['capabilities']), nargs='?', default=config['default'])
    args = parser.parse_args()
    cap = config['capabilities'][args.capability]
    if not cap['enabled']:
        print(json.dumps({'capability': args.capability, 'status': 'disabled', 'reason': cap['reason']}))
        return 2
    mismatches = []
    for line in (root / cap['requirements']).read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        package, expected = line.split('==')
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        if actual != expected:
            mismatches.append({'package': package, 'expected': expected, 'actual': actual})
    print(json.dumps({'capability': args.capability, 'status': 'fail' if mismatches else 'pass', 'mismatches': mismatches}))
    return int(bool(mismatches))


if __name__ == '__main__':
    raise SystemExit(main())
