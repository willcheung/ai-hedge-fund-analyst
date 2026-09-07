"""Fresh all-job coverage without copying live jobs, prompts or private config."""
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from job_definitions import export_jobs, digest, source_configuration_digest


def audit(source, manifest, skills):
    jobs=source['jobs']
    exported={x['sourceId']:x for x in manifest['jobs']}
    ids={j['id'] for j in jobs}
    if ids != set(exported) or len(jobs)!=len(exported):raise ValueError('source coverage drift')
    missing={s['name'] for s in skills['skills'] if s['status'] != 'definition-resolved-not-vendored'}
    rows=[]
    for j in jobs:
        text=json.dumps({k:j.get(k) for k in ('prompt','script','monitor_script','workdir')})
        dependencies=[]
        for token, label in (('wiki-market','external wiki: excluded/uninspected'),('market-dashboard','dashboard source included; runtime/publish integration external gated'),('trading-execution','disabled execution component; never started'),('/.hermes/scripts/','legacy custom automation scripts; see automation/source-inventory.json'),('skills/','external custom skill assets'),('calconviction','social/paid collection capability gated'),('mes_','external MES component; not provisioned')):
            if token in text:dependencies.append(label)
        names={s['name'] for s in skills['skills'] if j['id'] in s['requiredBy']}
        row={'sourceId':j['id'],'name':j['name'],'intendedEnabled':j['enabled'],'sourceState':j['state'],
             'disposition':exported[j['id']]['disposition'],'dependencies':dependencies,
             'directScript':Path(j['script']).name if j.get('script') else None,
             'monitorScript':Path(j['monitor_script']).name if j.get('monitor_script') else None,
             'requiredSkills':sorted(names),'missingSkills':sorted(names & missing),
             'otherProfileReference':bool(j.get('profile')),
             'promptDisposition':'external-private-review' if any(v['kind']=='private-prompt-review' for k,v in manifest['settings'].items() if k.startswith('JOB_'+j['id'].upper()+'_')) else 'sanitized-included',
             'activationAllowed':False}
        rows.append(row)
    fresh=export_jobs(source,manifest['timezone'])
    return {'capturedAt':datetime.now(timezone.utc).isoformat(),'sourceCount':len(jobs),'exportedCount':len(exported),'sourceDefinitionUnchangedSinceExport':source_configuration_digest(jobs)==manifest['coverage']['sourceConfigurationDigest'],
            'repeatProgressUnchangedSinceExport':digest(fresh['jobs'])==digest(manifest['jobs']),
            'runtimeProgressNote':'Source repeat.completed may advance during live scheduling; exported progress is the capture-time lifecycle snapshot. No live writes performed.',
            'states':dict(Counter(j['state'] for j in jobs)), 'dispositions':dict(Counter(r['disposition'] for r in rows)),
            'promptDispositions':dict(Counter(r['promptDisposition'] for r in rows)),
            'skills':skills['counts'],'jobs':rows,
            'limits':'Coverage describes only the explicitly supplied private source; it is not publication-safe deployment evidence. External wiki and other profiles uninspected. Private settings/instruction fragments and transitive skill/tool dependencies require operator review; no execution activation supported.'}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--directory',required=True);a=p.parse_args();d=Path(a.directory)
    before=Path(a.source).read_bytes()
    result=audit(json.loads(before),json.loads((d/'definitions.json').read_text()),json.loads((d/'skill-dispositions.json').read_text()))
    if before != Path(a.source).read_bytes():raise ValueError('concurrent source drift')
    (d/'job-dispositions.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='jobs'}))
