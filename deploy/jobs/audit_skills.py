"""Read-only metadata audit: explicit default skill root, never wiki contents."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone
from job_definitions import validate


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(manifest, skill_root, source=None):
    validate(manifest)
    root=Path(skill_root).resolve()
    explicit=set()
    source_prompts = {j['id']:j.get('prompt') or '' for j in source['jobs']} if source else {}
    prompts='\n'.join(source_prompts.get(j['sourceId'], j['definition'].get('prompt') or '') for j in manifest['jobs'])
    for job in manifest['jobs']:
        d=job['definition']; explicit.update(d.get('skills') or [])
        if d.get('skill'): explicit.add(d['skill'])
    definitions={}
    for path in root.rglob('SKILL.md'):
        if any(part.startswith('.') for part in path.relative_to(root).parts):
            continue
        if path.parent.name not in explicit and not re.search(r'(?<![\w-])'+re.escape(path.parent.name)+r'(?![\w-])',prompts):
            continue
        # No symlink escapes into another profile, wiki, or external library.
        if not path.resolve().is_relative_to(root):
            continue
        # Read frontmatter only; never interpret skill body or linked assets.
        lines=[]
        with path.open() as stream:
            if stream.readline().strip() == '---':
                for line in stream:
                    if line.strip() == '---': break
                    lines.append(line)
        text=''.join(lines)
        match=re.search(r'^name:\s*[\"\x27]?([^\n\"\x27]+)',text,re.M)
        name=match.group(1).strip() if match else path.parent.name
        definitions.setdefault(name,[]).append((path,text))
    requested={}
    for job in manifest['jobs']:
        d=job['definition']
        names=set(d.get('skills') or []) | ({d['skill']} if d.get('skill') else set())
        # Named inline skill dependencies are additive to scheduler preload fields.
        for name in definitions:
            if re.search(r'(?<![\w-])'+re.escape(name)+r'(?![\w-])',source_prompts.get(job['sourceId'], d.get('prompt') or '')):
                names.add(name)
        for name in names:requested.setdefault(name,[]).append(job['sourceId'])
    skills=[]
    for name, jobs in sorted(requested.items()):
        matches=definitions.get(name,[])
        skills.append({'name':name,'requiredBy':sorted(jobs),
                       'schedulerPreloadRequiredBy':sorted(j['sourceId'] for j in manifest['jobs'] if name in (j['definition']['skills'] or []) or name == j['definition']['skill']),
                       'disposition':'external-dependency' if matches else 'external-missing-blocked',
                       'definitions':[{'pathRelativeToDefaultSkills':str(p.relative_to(root)),'sha256':file_hash(p)} for p,text in matches],
                       'status':'definition-resolved-not-vendored' if len(matches)==1 else ('ambiguous-blocked' if matches else 'missing-blocked'),
                       'executionGate':'Provision reviewed skill plus its transitive assets/tools independently; no library copied and no skill executed'})
    return {'generatedAt':datetime.now(timezone.utc).isoformat(),'scope':'Default-profile local SKILL.md metadata only; symlink escapes excluded; no wiki/profile/runtime contents copied',
            'limitation':'Inline discovery uses all authorized source prompts when source supplied; only recognized installed skill names are discovered. Unrecognized prose dependencies and transitive assets remain unverified and execution-blocked.',
            'skills':skills,'counts':{'requested':len(skills),'resolved':sum(bool(x['definitions']) for x in skills),'missing':sum(not x['definitions'] for x in skills)}}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source');p.add_argument('--manifest',required=True);p.add_argument('--skill-root',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=inventory(json.loads(Path(a.manifest).read_text()),a.skill_root, json.loads(Path(a.source).read_text()) if a.source else None)
    Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['counts']))
