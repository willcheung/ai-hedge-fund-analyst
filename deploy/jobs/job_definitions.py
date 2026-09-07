"""Declarative export and NONEXECUTING scratch materialization (stdlib only).

No Hermes imports, scheduler calls, shell expansion, credentials or network. The
exporter preserves prompts while externalizing sensitive values and deployment
locations. All jobs remain external/blocked pending independent provisioning.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo

FIELDS = {'name', 'schedule', 'schedule_display', 'repeat', 'skills', 'skill',
          'no_agent', 'enabled_toolsets', 'context_from', 'model', 'provider'}
CONFIG_FIELDS = {'script', 'monitor_script', 'monitor_url', 'workdir', 'deliver',
                 'failure_deliver', 'profile', 'base_url'}
DEFAULTS = dict(name='', prompt='', skills=[], skill=None, no_agent=False,
                enabled_toolsets=None, context_from=None, model=None, provider=None,
                script=None, monitor_script=None, monitor_url=None, workdir=None,
                deliver='local', failure_deliver=None, profile=None, base_url=None,
                schedule_display='')
RUNTIME_FIELDS = {'last_run_at','last_status','last_error','next_run_at','run_claim',
                  'fire_claim','monitor_state','failure_streak','last_dispatch'}
TOKEN = re.compile(r'\$\{([A-Z][A-Z0-9_]*)\}')
SECRET = re.compile(r'(?i)(?:sk-[A-Za-z0-9_-]{12,}|xox[baprs]-[A-Za-z0-9-]+|gh[pousr]_[A-Za-z0-9]+|-----BEGIN .*PRIVATE KEY|(?:api[_-]?key|access[_-]?token|token|password|secret)\s*[=:]\s*[\"\x27]?[A-Za-z0-9_/-]{8,})')
PRIVATE = re.compile(r'(?i)(account|portfolio|持仓|shares|contracts|balance|net worth|buying power|\bqty\b|\bquantity\b)')
CONCRETE = re.compile(r'/root(?:/|\b)|/home/|~[/\\]|https?://|\b[CDUGW](?=[A-Z0-9]*[0-9])[A-Z0-9]{8,}\b|\b\d{9,}\b')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def safe_text(text):
    """Fail closed, with no sensitive value included in diagnostics."""
    if SECRET.search(text) or CONCRETE.search(text):
        raise ValueError('unresolved concrete path, endpoint, identity, or secret pattern')


def export_jobs(source, timezone_name, private_values=None):
    ZoneInfo(timezone_name)
    raw = source['jobs'] if isinstance(source, dict) else source
    if not isinstance(raw, list):
        raise ValueError('jobs must be a list')
    out = {'schemaVersion': 1, 'timezone': timezone_name,
           'timezoneProvenance': 'operator supplied; verify against scheduler configuration before any future activation',
           'sourceCount': len(raw), 'settings': {}, 'jobs': []}
    settings = out['settings']
    for src in raw:
        allowed = FIELDS | CONFIG_FIELDS | RUNTIME_FIELDS | {'id','prompt','enabled','state','paused_at','paused_reason','created_at','last_delivery_error','origin','model_snapshot','provider_snapshot'}
        if set(src) - allowed:
            raise ValueError('unreviewed source fields; export refused')
        ident = src['id']
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', ident):
            raise ValueError('unsafe job identifier')
        def external(field, value, kind='external-config'):
            key = 'JOB_' + ident.upper().replace('-', '_') + '_' + field.upper()
            settings[key] = {'kind': kind, 'requiredForExecution': True,
                             'provisioning': 'Explicit operator review required; source value intentionally not exported; restore this exact value or instruction fragment privately'}
            if private_values is not None:
                # Verification-only in-memory map. Never serialize or log it.
                private_values[key] = copy.deepcopy(value)
            return '${' + key + '}'
        definition = copy.deepcopy(DEFAULTS)
        definition.update({k: copy.deepcopy(src[k]) for k in FIELDS if k in src})
        for field in CONFIG_FIELDS:
            if src.get(field) is not None:
                # Delivery local is intrinsically nonremote and has no identity.
                definition[field] = 'local' if field in {'deliver','failure_deliver'} and src[field] == 'local' else external(field, src[field])
            elif field in src:
                definition[field] = None
        prompt = src.get('prompt') or ''
        serial = [0]
        def replace(match):
            serial[0] += 1
            return external('prompt_config_' + str(serial[0]), match.group())
        # Preserve instructions, including portfolio-blind/privacy guardrails.
        # Externalize concrete values, not generic finance vocabulary.
        prompt = SECRET.sub(replace, prompt)
        prompt = re.sub(r'(?i)(?:--(?:entry-price|max-contracts|contracts)\s+)[0-9.,]+|\$\d[\d,.]*(?:[kKmMbB])?|\b\d+(?:\.\d+)?\s+(?:(?:Micro\s+)?(?:Gold|Silver)\s+(?:futures\s+)?|(?:SIL|MGC)\s+\(Micro\s+(?:Gold|Silver)\)\s+)?(?:contracts|shares)\b|[•●]{2,}\d+', replace, prompt)
        # Account-specific holdings/history or limits stated as prose are retained
        # as a provisionable instruction fragment instead of leaking the value.
        prompt = re.sub(r'(?im)^.*(?:(?:owner|operator) sold|(?:owner|operator).s explicit target|Max contracts:|contracts of room).*(?:\n|$)', replace, prompt)
        pattern = r'(?:/root(?:/[^\s`\"\x27<>]*)?|/home/[^\s`\"\x27<>]+|~/[^\s`\"\x27<>]+|https?://[^\s`\"\x27<>]+|\b[CDUGW](?=[A-Z0-9]*[0-9])[A-Z0-9]{8,}\b|\b\d{9,}\b)'
        definition['prompt'] = re.sub(pattern, replace, prompt)
        safe_text(definition['prompt'])
        withheld = False
        state = src.get('state')
        disposition = 'external-blocked' if src.get('enabled') and state == 'scheduled' else 'deferred-disabled'
        out['jobs'].append({'sourceId': ident, 'intendedEnabled': bool(src.get('enabled')),
                            'sourceState': state, 'disposition': disposition,
                            'blockers': ['Runtime activation not implemented', 'External inputs/capabilities require independent provisioning'] + (['Prompt withheld pending privacy review'] if withheld else []),
                            'definition': definition})
    validate(out)
    out['coverage'] = {'sourceConfigurationDigest': source_configuration_digest(raw), 'sourceIds': sorted(x['id'] for x in raw),
                       'definitionDigest': digest(out['jobs']),
                       'sourceStateCounts': {state: sum(x.get('state') == state for x in raw) for state in sorted({x.get('state') for x in raw})}}
    return out


def source_configuration_digest(jobs):
    rows = []
    for job in jobs:
        row = {k: job.get(k) for k in sorted(FIELDS | CONFIG_FIELDS | {'id','prompt','enabled','state'})}
        row['repeat'] = {'times': job.get('repeat', {}).get('times')}
        rows.append(row)
    return digest(sorted(rows, key=lambda row:row['id']))


def validate_cron(expr):
    """Strict portable numeric five-field subset; unsupported grammar fails closed."""
    if not isinstance(expr, str) or len(expr.split()) != 5:
        raise ValueError('invalid cron expression')
    for token, (low, high) in zip(expr.split(), ((0,59),(0,23),(1,31),(1,12),(0,7))):
        for part in token.split(','):
            match = re.fullmatch(r'(\*|\d+(?:-\d+)?)(?:/(\d+))?', part)
            if not match or (match[2] and not 1 <= int(match[2]) <= high-low+1):
                raise ValueError('invalid cron field')
            if match[1] != '*':
                bounds = [int(x) for x in match[1].split('-')]
                if any(not low <= x <= high for x in bounds) or bounds != sorted(bounds):
                    raise ValueError('cron field out of range')


def validate(manifest):
    if not isinstance(manifest, dict) or type(manifest.get('schemaVersion')) is not int or manifest.get('schemaVersion') != 1:
        raise ValueError('unsupported schema')
    if set(manifest) - {'schemaVersion','timezone','timezoneProvenance','sourceCount','settings','jobs','coverage'} or not {'schemaVersion','timezone','timezoneProvenance','sourceCount','settings','jobs'} <= set(manifest):
        raise ValueError('unknown manifest fields')
    ZoneInfo(manifest['timezone'])
    if not isinstance(manifest['settings'],dict):
        raise ValueError('settings must be a declaration object')
    for name, setting in manifest['settings'].items():
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*',name) or set(setting) != {'kind','requiredForExecution','provisioning'} or setting['requiredForExecution'] is not True:
            raise ValueError('invalid external setting declaration')
        if setting['kind'] not in {'external-config','private-prompt-review'} or not isinstance(setting['provisioning'], str):
            raise ValueError('invalid setting kind or provisioning')
        safe_text(json.dumps(setting))
    jobs = manifest['jobs']
    if not isinstance(jobs, list):
        raise ValueError('jobs must be a list')
    if type(manifest['sourceCount']) is not int or len(jobs) != manifest['sourceCount']:
        raise ValueError('coverage count mismatch')
    ids = [j['sourceId'] for j in jobs]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', i) for i in ids):
        raise ValueError('duplicate or unsafe source IDs')
    for job in jobs:
        if set(job) != {'sourceId','intendedEnabled','sourceState','disposition','blockers','definition'}:
            raise ValueError('unknown job fields')
        if type(job['intendedEnabled']) is not bool or job['sourceState'] not in {'scheduled','paused','completed'}:
            raise ValueError('invalid lifecycle')
        if job['sourceState'] in {'completed','paused'} and job['intendedEnabled']:
            raise ValueError('terminal/paused source cannot be enabled')
        if not isinstance(job['blockers'], list) or any(not isinstance(x,str) for x in job['blockers']):
            raise ValueError('invalid blockers')
        safe_text(json.dumps(job['blockers']))
        if job['disposition'] not in {'external-blocked','deferred-disabled'} or not job['blockers']:
            raise ValueError('execution disposition must remain blocked')
        d = job['definition']
        if set(d) != (FIELDS | CONFIG_FIELDS | {'prompt'}):
            raise ValueError('unknown/runtime definition field')
        s = d['schedule']
        kind = s.get('kind')
        required = {'cron':'expr','once':'run_at','interval':'minutes'}
        if kind not in required or required[kind] not in s:
            raise ValueError('invalid schedule')
        if set(s) - {'kind', required[kind], 'display'}:
            raise ValueError('unknown schedule field')
        if 'display' in s and not isinstance(s['display'], str):
            raise ValueError('invalid schedule display')
        if kind == 'cron':
            validate_cron(s['expr'])
        for field in ('name', 'prompt', 'schedule_display'):
            if not isinstance(d[field], str):
                raise ValueError('invalid text field')
        for field in ('skill', 'model', 'provider'):
            if d[field] is not None and (not isinstance(d[field], str) or not re.fullmatch(r'[A-Za-z0-9_./:-]+', d[field])):
                raise ValueError('invalid named capability')
        for field in ('skills', 'enabled_toolsets', 'context_from'):
            values = d[field]
            if values is None and field != 'skills':
                continue
            if not isinstance(values, list) or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_./:-]+', v) for v in values):
                raise ValueError('invalid capability list')
            if field == 'context_from' and set(values) - set(ids) - {'self'}:
                raise ValueError('unresolved context source ID')
        if type(d['no_agent']) is not bool or (d['no_agent'] and not d['script']):
            raise ValueError('no-agent jobs require declared script')
        for field in CONFIG_FIELDS:
            value = d[field]
            if value is not None and not (isinstance(value, str) and (TOKEN.fullmatch(value) or (field in {'deliver','failure_deliver'} and value == 'local'))):
                raise ValueError('invalid external configuration')
        if kind == 'interval' and (type(s['minutes']) not in (float,int) or not math.isfinite(s['minutes']) or s['minutes'] <= 0):
            raise ValueError('invalid interval')
        if kind == 'once':
            if datetime.fromisoformat(s['run_at'].replace('Z','+00:00')).tzinfo is None:
                raise ValueError('one-shot requires explicit timezone')
        repeat = d['repeat']
        if set(repeat) != {'times','completed'} or type(repeat['completed']) is not int or repeat['completed'] < 0 or (repeat['times'] is not None and (type(repeat['times']) is not int or repeat['times'] < 1)):
            raise ValueError('invalid repeat lifecycle')
        if repeat['times'] is not None:
            if repeat['completed'] > repeat['times'] or (job['sourceState'] == 'completed') != (repeat['completed'] == repeat['times']):
                raise ValueError('exhausted repeat lifecycle mismatch')
        if job['sourceState'] == 'scheduled' and not job['intendedEnabled']:
            raise ValueError('scheduled intent must be enabled')
        text = json.dumps(d, ensure_ascii=False)
        safe_text(text)
        if re.search(r'(?i)\$\d|\b\d+(?:\.\d+)?\s+(?:shares|contracts)\b|[•●]{2,}\d+', d['prompt']):
            raise ValueError('unresolved financial or masked account value')
        if set(TOKEN.findall(text)) - set(manifest['settings']):
            raise ValueError('undeclared setting')
        for field in ('script','monitor_script','monitor_url','workdir','profile','base_url'):
            if d.get(field) is not None and not TOKEN.fullmatch(d[field]):
                raise ValueError('executable/external field must be a declared setting')
    if 'coverage' in manifest:
        coverage = manifest['coverage']
        if set(coverage) != {'sourceIds','definitionDigest','sourceStateCounts','sourceConfigurationDigest'} or coverage['sourceStateCounts'] != {s: sum(j['sourceState']==s for j in jobs) for s in sorted({j['sourceState'] for j in jobs})}:
            raise ValueError('invalid coverage fields or state counts')
        if not isinstance(coverage['sourceConfigurationDigest'], str) or not re.fullmatch(r'[0-9a-f]{64}', coverage['sourceConfigurationDigest']):
            raise ValueError('invalid source configuration digest')
        if coverage['sourceIds'] != sorted(ids) or coverage['definitionDigest'] != digest(jobs):
            raise ValueError('coverage evidence mismatch')
    return {'count': len(jobs), 'enabled': 0, 'valid': True}


def scratch_import(manifest, destination):
    """Create a NEW /tmp/analyst-job-scratch-* directory only; never merge.

    Deliberately no path-resolution/settings API: external code must not become
    executable here. Do not launch Hermes against this archival scratch home.
    """
    validate(manifest)
    p = Path(destination)
    if not p.is_absolute() or p.parent != Path('/tmp') or not re.fullmatch(r'analyst-job-scratch-[A-Za-z0-9_-]{6,80}', p.name):
        raise ValueError('destination must be a new /tmp/analyst-job-scratch-<unique> directory')
    if p.exists() or p.is_symlink() or p.resolve() != p:
        raise ValueError('destination exists or resolves through a symlink')
    # mkdir exclusive avoids replacing an existing home, symlink or scheduler.
    if os.environ.get('HERMES_HOME') and p == Path(os.environ['HERMES_HOME']).expanduser().resolve():
        raise ValueError('refusing configured live Hermes home')
    p.mkdir(mode=0o700)
    runtime = []
    for job in manifest['jobs']:
        definition = copy.deepcopy(job['definition'])
        definition.update(id=job['sourceId'], enabled=False,
                          state='completed' if job['sourceState'] == 'completed' else 'paused',
                          intendedEnabled=job['intendedEnabled'], sourceState=job['sourceState'],
                          next_run_at=None, deliver='local', failure_deliver='local', no_agent=False)
        # Preserve original sanitized definition separately; never attach runnable hooks.
        for key in ('script','monitor_script','monitor_url','origin','profile','workdir','base_url'):
            definition[key] = None
        definition['prompt'] = '[STAGING ARCHIVE ONLY: execution forbidden]'
        runtime.append(definition)
    (p/'cron').mkdir(mode=0o700)
    (p/'cron'/'jobs.json').write_text(json.dumps({'jobs': runtime}, indent=2)+'\n')
    (p/'definitions.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (p/'DO_NOT_START_SCHEDULER').write_text('Nonexecuting definition archive only. No activation supported.\n')
    actual = json.loads((p/'cron'/'jobs.json').read_text())['jobs']
    verify_roundtrip(manifest, p)
    if len(actual) != len(manifest['jobs']) or any(j['enabled'] or j['script'] or j['monitor_script'] for j in actual):
        raise RuntimeError('scratch verification failed')
    return {'path': str(p), 'count': len(actual), 'enabled': 0}


def verify_roundtrip(manifest, destination):
    """Compare every allowed semantic field plus deliberate inert overrides."""
    p = Path(destination)
    restored = json.loads((p/'definitions.json').read_text())
    validate(restored)
    if restored != manifest or not (p/'DO_NOT_START_SCHEDULER').is_file():
        raise ValueError('declaration roundtrip or marker mismatch')
    runtime = json.loads((p/'cron/jobs.json').read_text())
    if set(runtime) != {'jobs'} or len(runtime['jobs']) != len(manifest['jobs']):
        raise ValueError('runtime coverage mismatch')
    for job, actual in zip(manifest['jobs'], runtime['jobs']):
        expected = copy.deepcopy(job['definition'])
        expected.update(id=job['sourceId'], enabled=False,
                        state='completed' if job['sourceState']=='completed' else 'paused',
                        intendedEnabled=job['intendedEnabled'], sourceState=job['sourceState'],
                        next_run_at=None, deliver='local', failure_deliver='local', no_agent=False,
                        prompt='[STAGING ARCHIVE ONLY: execution forbidden]')
        for field in ('script','monitor_script','monitor_url','origin','profile','workdir','base_url'):
            expected[field] = None
        if actual != expected:
            raise ValueError('runtime semantic or inert override mismatch')
    return {'count':len(runtime['jobs']), 'enabled':0, 'semanticRoundtrip':True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    exp = sub.add_parser('export'); exp.add_argument('--source', required=True); exp.add_argument('--timezone', required=True); exp.add_argument('--output', required=True)
    val = sub.add_parser('validate'); val.add_argument('manifest')
    imp = sub.add_parser('scratch-import'); imp.add_argument('manifest'); imp.add_argument('--destination', required=True)
    args = parser.parse_args()
    if args.command == 'export':
        source_path = Path(args.source)
        before = source_path.read_bytes()
        manifest = export_jobs(json.loads(before), args.timezone)
        if before != source_path.read_bytes():
            raise ValueError('source changed during export')
        output = Path(args.output)
        if output.resolve() == source_path.resolve() or output.exists():
            raise ValueError('output must be new and separate from source')
        output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
        print(json.dumps(validate(manifest)))
    else:
        manifest = json.loads(Path(args.manifest).read_text())
        print(json.dumps(validate(manifest) if args.command == 'validate' else scratch_import(manifest, args.destination)))

if __name__ == '__main__':
    main()
