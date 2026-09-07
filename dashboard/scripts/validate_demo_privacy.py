#!/usr/bin/env python3
"""Validate public source boundaries and byte-identical synthetic static output."""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', 'node_modules', '.venv', '.wheelhouse', '.install-home', '__pycache__', 'dist', 'public', '.cache'}
TEXT = {'.py', '.ts', '.tsx', '.js', '.mjs', '.json', '.html', '.css', '.md', '.yml'}
# Real deployment hosts, absolute owner defaults, and opaque production job IDs
# must never be inherited. Synthetic paths in adversarial tests are intentional.
SOURCE_DENY = (
    re.compile(r'https://[a-z0-9-]+\.vercel\.app', re.I),
    re.compile(r'(?<![a-f0-9])(?!0{8})[a-f0-9]{12}(?![a-f0-9])'),
    re.compile(r'(?:Path\(|default=)[\'\"]/(?:root|home)/'),
)


# The optional SDK is source capability only; emitted demo bytes may contain no
# transport. Runtime gating and the sanitizer are also exercised by mocked JS tests.
ANALYTICS_GUARD = "{import.meta.env.PROD && import.meta.env.VITE_ENABLE_ANALYTICS === 'true' && !isStagedPreviewBuild && <Analytics beforeSend={sanitizeAnalyticsEvent} />}"
ANALYTICS_TRANSPORT = re.compile(r'/_vercel/(?:insights|speed-insights)|va\.vercel-scripts\.com')


def analytics_source_errors(root):
    errors = []
    if (root / 'src').is_symlink():
        return ['src: symlink']
    main = root / 'src/main.tsx'
    if main.is_symlink() or not main.is_file() or ANALYTICS_GUARD not in main.read_text():
        errors.append('src/main.tsx: missing explicit analytics privacy gate')
    mode = root / 'src/useMarketData.ts'
    if mode.is_symlink() or not mode.is_file() or "export const isStagedPreviewBuild = import.meta.env.VITE_MARKETS_DATA_MODE !== 'production'" not in mode.read_text():
        errors.append('src/useMarketData.ts: missing explicit production data gate')
    for path in (root / 'src').rglob('*'):
        if path.is_symlink():
            errors.append(f'{path.relative_to(root)}: symlink')
            continue
        if not path.is_file() or path.suffix not in {'.ts', '.tsx', '.js', '.jsx'}:
            continue
        if path.name.endswith(('.test.ts', '.test.tsx')):
            continue
        for line in path.read_text().splitlines():
            if '@vercel/analytics' in line and not (
                (path == main and line == "import { Analytics } from '@vercel/analytics/react'") or
                (path == root / 'src/analytics.ts' and line == "import type { BeforeSendEvent } from '@vercel/analytics'")
            ):
                errors.append(f'{path.relative_to(root)}: unreviewed analytics entry')
            if '<Analytics' in line and (path != main or line.strip() != ANALYTICS_GUARD):
                errors.append(f'{path.relative_to(root)}: unguarded analytics mount')
            if ANALYTICS_TRANSPORT.search(line):
                errors.append(f'{path.relative_to(root)}: direct analytics transport')
    return errors


def source_errors(root=ROOT):
    errors=analytics_source_errors(root)
    for path in sorted(root.rglob('*')):
        relative=path.relative_to(root)
        if SKIP.intersection(relative.parts): continue
        if path.is_symlink(): errors.append(f'{relative}: symlink'); continue
        if not path.is_file(): continue
        if path.suffix not in TEXT or path.name == 'package-lock.json': continue
        text=path.read_text(encoding='utf-8')
        if path.suffix=='.py':
            try: ast.parse(text,filename=str(relative))
            except SyntaxError: errors.append(f'{relative}: syntax')
        for pattern in SOURCE_DENY:
            if pattern.search(text): errors.append(f'{relative}: owner/deployment default')
        if path.name.endswith(('.test.ts','.test.tsx')) and '../public/wiki-data.json' in text:
            errors.append(f'{relative}: test depends on public dataset')
    return errors


def artifact_errors(root=ROOT):
    from stage_demo import build_demo
    from public_snapshot import canonical_json_bytes, scan_public_assets
    body, manifest=build_demo()
    expected={
        'wiki-data.json':canonical_json_bytes(body),
        'market-data/manifest.json':canonical_json_bytes(manifest),
        f"market-data/snapshots/{manifest['objectSha256']}.json":canonical_json_bytes(body),
    }
    links = [path for directory in (root/'public', root/'dist')
             for path in (directory, *directory.rglob('*')) if path.is_symlink()]
    if links:
        return [f'{path.relative_to(root)}: symlink' for path in links]
    errors=scan_public_assets([root/'public',root/'dist'])
    for directory in (root/'public',root/'dist'):
        for relative,payload in expected.items():
            path=directory/relative
            if not path.is_file() or path.is_symlink() or path.read_bytes()!=payload:
                errors.append(f'{path.relative_to(root)}: missing or non-synthetic bytes')
        for path in directory.rglob('*'):
            if path.is_symlink(): errors.append(f'{path.relative_to(root)}: symlink')
            if path.suffix=='.map': errors.append(f'{path.relative_to(root)}: source map')
            if path.suffix=='.json' and str(path.relative_to(directory)) not in expected:
                errors.append(f'{path.relative_to(root)}: unexpected dataset')
    html=root/'dist/index.html'
    if not html.is_file(): errors.append('dist/index.html: missing build')
    elif "connect-src 'self'" not in html.read_text() or "frame-src 'none'" not in html.read_text():
        errors.append('dist/index.html: missing demo network isolation policy')
    for path in (root/'dist').rglob('*'):
        if path.suffix not in {'.js', '.html'}: continue
        text=path.read_text()
        if ANALYTICS_TRANSPORT.search(text):
            errors.append(f'{path.relative_to(root)}: analytics transport')
    return errors


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only',action='store_true')
    args=parser.parse_args(argv)
    errors=source_errors()
    if not args.source_only: errors.extend(artifact_errors())
    print(json.dumps({'pass':not errors,'failures':errors},indent=2))
    return int(bool(errors))

if __name__=='__main__': raise SystemExit(main())
