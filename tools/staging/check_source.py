#!/usr/bin/env python3
"""Check current source boundaries and syntax without importing applications."""
import ast
import json
from pathlib import Path
import subprocess
import privacy_scan

FORBIDDEN_PARTS = {'.hermes', '.vercel', 'node_modules', '.venv', 'venv', '__pycache__',
                   'state', 'learning', 'incidents', 'conf', 'profiles', 'wiki-market',
                   'wiki-ai', 'dist', 'artifacts'}

def path_violation(name):
    path=Path(name)
    if path.is_absolute() or '..' in path.parts or FORBIDDEN_PARTS.intersection(path.parts):
        return 'private_runtime_or_external_path'
    if path.name.startswith('.env') and path.name != '.env.example':
        return 'credential_file'
    if path.name in {'auth.json', 'token.txt', 'settings.local.json', 'buy_zone_alerts.json'}:
        return 'credential_or_private_configuration'
    if path.suffix in {'.pem', '.key', '.db', '.sqlite', '.sqlite3', '.log', '.pyc'}:
        return 'credential_or_runtime_extension'
    if path.parts[:2] == ('trading-execution', 'build'):
        return 'generated_execution_build'
    if name.startswith('dashboard/public/') and path.suffix=='.json':
        return 'generated_public_payload'
    return None

def inspect_files(root, names):
    failures=[]
    for name in names:
        path=root/name
        reason=path_violation(name)
        if reason:
            failures.append({'path':name,'reason':reason});continue
        if path.is_symlink() or not path.is_file():
            failures.append({'path':name,'reason':'symlink_or_missing_file'});continue
        if path.suffix=='.py':
            try:ast.parse(path.read_text(),filename=name)
            except (SyntaxError,UnicodeError):failures.append({'path':name,'reason':'python_syntax'})
        elif path.suffix=='.json':
            try:
                json.loads(path.read_text(), parse_constant=reject_constant, object_pairs_hook=unique_keys)
            except (ValueError, UnicodeError):
                failures.append({'path':name,'reason':'invalid_json'})
        elif path.suffix=='.sh':
            p=subprocess.run(['bash','-n',str(path)],capture_output=True)
            if p.returncode:failures.append({'path':name,'reason':'shell_syntax'})
    return failures

def reject_constant(_):
    raise ValueError('non-finite JSON constant')


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def inspect_manifest(root, names):
    try:
        manifest = json.loads((root / 'SOURCE-MANIFEST.json').read_text())
        if manifest['format_version'] != 2 or manifest['files'] != sorted(set(names)):
            return [{'path': 'SOURCE-MANIFEST.json', 'reason': 'source_inventory_mismatch'}]
    except (OSError, ValueError, KeyError, TypeError):
        return [{'path': 'SOURCE-MANIFEST.json', 'reason': 'invalid_source_inventory'}]
    return []


def main():
    root=Path(__file__).resolve().parents[2]
    files=privacy_scan.source_names(root)
    failures=inspect_files(root,files)
    failures.extend(inspect_manifest(root,files))
    failures.extend(privacy_scan.inspect(root, files))
    print(json.dumps({'source_files':len(files),'failures':failures,'pass':bool(files) and not failures},indent=2))
    return 0 if files and not failures else 1

if __name__=='__main__':raise SystemExit(main())
