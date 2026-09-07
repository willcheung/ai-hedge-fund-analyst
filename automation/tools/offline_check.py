#!/usr/bin/env python3
"""Compatibility entrypoint; use the shared staging isolation wrapper."""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--venv', required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    root = os.environ.get('STAGING_ROOT')
    if not root:
        parser.error('Set STAGING_ROOT to the disposable source/dependency tree')
    command = ['env', '-i', 'PATH=' + str(args.venv / 'bin') + ':' + os.environ.get('PATH', '/usr/bin:/bin'),
               'STAGING_ROOT=' + root, 'bash', str(repo / 'tools/staging/offline.sh'),
               str(args.venv / 'bin/python'), '-m', 'unittest', 'discover', '-p', 'test_*.py', '-v']
    return subprocess.call(command, cwd=repo / 'automation')

if __name__ == '__main__':
    raise SystemExit(main())
