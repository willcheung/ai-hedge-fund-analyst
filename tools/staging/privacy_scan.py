#!/usr/bin/env python3
"""Deterministic public-source checks. Diagnostics contain paths/categories only.

This is a regression guard, not proof that arbitrary financial prose is public.
No application imports, credentials, network or private filesystem reads.
"""
import argparse
import ast
import json
from pathlib import Path
import re
import hashlib
import os

EMAIL = re.compile(r'(?i)\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b')
PATTERNS = {
    'private_absolute_root': re.compile(r'/(?:root|home|Users)/[A-Za-z0-9_.-]+'),
    'deployment_identifier': re.compile(r'''["'][0-9a-f]{12}["']|\b(?:dpl_|prj_|team_)[A-Za-z0-9]{8,}\b|\b[CDGW](?=[A-Z0-9]*[0-9])[A-Z0-9]{9,}\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b'''),
    'operational_endpoint': re.compile(r'https://[A-Za-z0-9.-]+\.(?:vercel\.app|blob\.vercel-storage\.com)|https://x\.com/i/lists/\d+'),
    'owner_financial_association': re.compile(r"(?i)\b(?:will|owner|operator|my)[’']?s?\s+(?:owned|holdings|sold|portfolio|account|standing.*mandate|explicit target)|\breviewer[\"']?\s*[:=]\s*[\"'](?:will|owner)[\"']"),
    'private_account_identifier': re.compile(r'\b(?:DU|U)\d{5,}\b|[•●]{2,}\d+'),
    'private_financial_setting': re.compile(r'''(?ix)
        ["']?(?:DEFAULT_PORTFOLIO_DENOMINATOR|(?:default_)?account_(?:value|equity|balance)|portfolio_(?:value|denominator)|net_worth)["']?
        \s*(?::\s*(?:float|int)\s*)?[:=]\s*["']?\d[\d_,.]*(?:[eE][+-]?\d+)?
        | \b["']?(?:TARGET_EMAIL|SLACK_CHANNEL|SOURCE_LIST_ID|BROKER_ACCOUNT)["']?\s*[:=]\s*["'][^"'\n$]+["']
    '''),
}
FINANCIAL_NAMES = re.compile(r'(?i)^(?:AI_PORTFOLIO_EARNINGS|HOLDINGS|OWNED_TICKERS|BROKER_ACCOUNT|ACCOUNT_NUMBER|ACCOUNT_ID)$')


# Exact path + category + full-line SHA-256 receipts for reviewed synthetic
# adversarial fixtures and detection literals. No file/category/regex exemption.
# A changed line (including appended text) loses its exception. Receipts contain
# no matched values; additions require source review and negative regression tests.
LINE_POLICY = json.loads(Path(__file__).with_name('privacy-policy.json').read_text())


def permitted_line(name, category, text, match):
    start = text.rfind('\n', 0, match.start()) + 1
    end = text.find('\n', match.end())
    line = text[start:end if end >= 0 else len(text)]
    digest = hashlib.sha256(line.encode()).hexdigest()
    return any(entry['path'] == name and entry['category'] == category
               and entry['line_sha256'] == digest for entry in LINE_POLICY)


def categories(name, text):
    found = set()
    for match in EMAIL.finditer(text):
        domain = match[1].lower()
        if domain in {'example.com', 'example.org', 'example.net', 'example.invalid'} or domain.endswith('.invalid'):
            continue
        if not permitted_line(name, 'personal_email', text, match):
            found.add('personal_email')
    for category, pattern in PATTERNS.items():
        matches = [m for m in pattern.finditer(text) if not permitted_line(name, category, text, m)]
        if matches:
            found.add(category)
    if name.endswith('.py'):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return sorted(found | {'python_syntax'})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get' and len(node.args) > 1:
                key = node.args[0]
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and re.search(r'(?i)(account|equity|portfolio|balance|holdings)', key.value):
                    try:
                        default = ast.literal_eval(node.args[1])
                    except (ValueError, TypeError):
                        default = None
                    if default:
                        found.add('private_financial_setting')
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and FINANCIAL_NAMES.fullmatch(t.id) for t in targets):
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        continue
                    if value:
                        found.add('hardcoded_private_account_configuration')
    return sorted(found)


# Only tool metadata/dependencies and generated build output are outside source.
# Unlike Git ignore rules, this does not hide credentials or runtime directories.
SOURCE_EXCLUDED_DIRS = {'.git', '.agents', '.codex', 'node_modules', '.venv', 'venv',
                        '.wheelhouse', '__pycache__', '.pytest_cache', '.cache', 'dist',
                        'install-home', '.install-home'}


def source_names(root):
    """Enumerate current files without consulting Git, its index or history."""
    names = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(dirs):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                names.append(relative)
                dirs.remove(name)
            elif name in SOURCE_EXCLUDED_DIRS or name.endswith('.egg-info') or relative == 'dashboard/public/market-data':
                dirs.remove(name)
        for name in files:
            relative = (base / name).relative_to(root).as_posix()
            if relative == 'dashboard/public/wiki-data.json' and not (base / name).is_symlink():
                continue  # Generated assets have a separate byte-exact demo gate.
            names.append(relative)
    return sorted(names)


def inspect(root, names):
    findings = []
    for name in sorted(set(names)):
        path = root / name
        if path.is_symlink():
            findings.append({'path': name, 'category': 'symlink'})
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeError:
            continue
        except OSError:
            findings.append({'path': name, 'category': 'unreadable_source'})
            continue
        findings.extend({'path': name, 'category': c} for c in categories(name, text))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    names = source_names(root)
    findings = inspect(root, names)
    print(json.dumps(findings, indent=2))
    return bool(findings)

if __name__ == '__main__':
    raise SystemExit(main())
