"""Run synthetic job tests only through the shared staging isolation wrapper."""
import os
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[2]
    staging = os.environ.get('STAGING_ROOT')
    if not staging:
        raise SystemExit('Set STAGING_ROOT to the disposable checkout')
    return subprocess.call(['env', '-i', 'PATH=' + os.environ.get('PATH', '/usr/bin:/bin'),
        'STAGING_ROOT=' + staging, 'bash', str(root / 'tools/staging/offline.sh'),
        'python3', '-m', 'unittest', 'discover', '-s', 'deploy/jobs', '-p', 'test_*.py', '-v'], cwd=root)

if __name__ == '__main__':
    raise SystemExit(main())
