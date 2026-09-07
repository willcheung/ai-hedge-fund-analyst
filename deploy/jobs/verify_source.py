"""Authorized read-only source fidelity proof; private map lives in memory only."""
import argparse
import json
from pathlib import Path
from job_definitions import DEFAULTS, TOKEN, export_jobs, source_configuration_digest


def verify(source, manifest):
    private = {}
    fresh = export_jobs(source, manifest['timezone'], private)

    def restore(value):
        if isinstance(value, str):
            for _ in range(20):
                match = TOKEN.fullmatch(value)
                if match and match[1] in private:
                    value = private[match[1]]
                    if not isinstance(value, str):
                        return value
                new = TOKEN.sub(lambda m: private.get(m[1], m[0]), value)
                if new == value:
                    return value
                value = new
            raise ValueError('recursive settings')
        if isinstance(value, list):
            return [restore(x) for x in value]
        if isinstance(value, dict):
            return {k: restore(v) for k,v in value.items()}
        return value

    for source_job, declaration in zip(source['jobs'], fresh['jobs']):
        for field, value in restore(declaration['definition']).items():
            if value != source_job.get(field, DEFAULTS.get(field)):
                raise ValueError('source semantic mismatch; values not logged')
    if source_configuration_digest(source['jobs']) != manifest['coverage']['sourceConfigurationDigest']:
        raise ValueError('source configuration changed')
    if fresh['settings'] != manifest['settings']:
        raise ValueError('checked-in settings differ from fresh export')
    expected_jobs = {j['sourceId']:j for j in fresh['jobs']}
    if len(expected_jobs) != len(manifest['jobs']):
        raise ValueError('checked-in job coverage differs')
    for job in manifest['jobs']:
        expected = expected_jobs.get(job['sourceId'])
        if expected is None:
            raise ValueError('checked-in source ID differs')
        # Runtime progress may advance, but all declaration text must match.
        expected['definition']['repeat']['completed'] = job['definition']['repeat']['completed']
        if expected != job:
            raise ValueError('checked-in declaration differs from source export')
    private.clear()
    return {'sourceCount':len(source['jobs']), 'losslessAllFieldsReconstruction':True,
            'privateMapPersisted':False, 'configurationUnchanged':True}


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source', required=True)
    p.add_argument('--manifest', required=True)
    a=p.parse_args()
    source_path=Path(a.source)
    before=source_path.read_bytes()
    result=verify(json.loads(before),json.loads(Path(a.manifest).read_text()))
    if before != source_path.read_bytes():
        raise ValueError('concurrent source drift')
    print(json.dumps(result))
