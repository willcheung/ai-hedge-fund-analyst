#!/usr/bin/env python3
"""Write public relative source structure, never external roots or source hashes."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def main():
    files = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob('*')
                   if p.is_file() and p.suffix in {'.py', '.sh'} and '__pycache__' not in p.parts)
    report = {'purpose': 'Public structural inventory; not an operational dependency or live source audit', 'files': files}
    (ROOT / 'source-inventory.json').write_text(json.dumps(report, indent=2) + '\n')

if __name__ == '__main__':
    main()
