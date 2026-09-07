#!/usr/bin/env python3
"""One local validation entry point; no network, cron, research or deployment."""
import argparse
import json
import tempfile
from pathlib import Path
from public_content import merge_publications
from public_snapshot import atomic_write_bytes, canonical_json_bytes, build_public_snapshot, validate_public_snapshot_schema


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--previous',type=Path)
    p.add_argument('--diagnostics',type=Path,required=True,help='Private owner file, outside public and dist')
    p.add_argument('--snapshot',action='store_true',help='Adapt a previously generated legacy snapshot; never run live generators')
    args=p.parse_args(argv)
    root=Path(__file__).resolve().parents[1]
    if any(folder in args.diagnostics.resolve().parents for folder in (root/'public',root/'dist')):
        p.error('diagnostics must remain outside public/dist')
    raw=json.loads(args.input.read_text())
    previous=json.loads(args.previous.read_text()) if args.previous and args.previous.exists() else []
    if isinstance(previous,dict): previous=previous.get('publications',[])
    diagnostics=[]
    if args.snapshot:
        with tempfile.TemporaryDirectory(prefix='publication-validation-') as directory:
            cron = Path(directory) / 'empty-cron'
            cron.mkdir()
            result=build_public_snapshot(raw,data_as_of=raw['dataAsOf'],cron_root=cron,previous_publications=previous,diagnostics=diagnostics)
        validate_public_snapshot_schema(result)
        count=len(result['publications'])
    else:
        rows=raw if isinstance(raw,list) else [raw]
        result=merge_publications(rows,previous,diagnostics)
        count=len(result)
    atomic_write_bytes(args.diagnostics,canonical_json_bytes(diagnostics))
    atomic_write_bytes(args.output,canonical_json_bytes(result))
    print(json.dumps({'accepted':count,'diagnostics':len(diagnostics),'output':str(args.output)}))
    return 1 if not args.snapshot and diagnostics else 0

if __name__=='__main__': raise SystemExit(main())
