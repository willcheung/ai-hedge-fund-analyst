"""Offline stdlib contract tests; no scheduler or production paths read."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from job_definitions import export_jobs, validate, scratch_import


def fixture():
    return {'jobs': [dict(id='synthetic', name='Synthetic test-only job', prompt='Preserve [SILENT] and dedupe rules.', schedule={'kind':'cron','expr':'0 9 * * 1-5','display':'Weekdays'}, repeat={'times':None,'completed':3}, enabled=True, state='scheduled', skills=['example-skill'], script='/home/synthetic-example/script.py', deliver='slack:C123' + '456789', failure_deliver='local')]}


class JobDefinitionTests(unittest.TestCase):
    def test_roundtrip_all_lifecycles_remain_disabled(self):
        src = fixture()
        for state in ('paused','completed'):
            j = copy.deepcopy(src['jobs'][0]); j.update(id=state,enabled=False,state=state)
            j['schedule'] = {'kind':'once','run_at':'2026-01-01T09:00:00+00:00'}
            j['repeat'] = {'times':1,'completed':1 if state=='completed' else 0}
            src['jobs'].append(j)
        manifest = export_jobs(src,'UTC')
        target = Path('/tmp') / ('analyst-job-scratch-' + uuid.uuid4().hex)
        result = scratch_import(manifest,target)
        self.addCleanup(__import__('shutil').rmtree,target)
        actual = json.loads((target/'cron/jobs.json').read_text())['jobs']
        self.assertEqual(result['count'],len(src['jobs']))
        self.assertFalse(any(j['enabled'] or j['script'] or j['monitor_script'] for j in actual))
        self.assertEqual(actual[-1]['state'],'completed')
        self.assertEqual(actual[0]['sourceState'],'scheduled')
        self.assertTrue(actual[0]['intendedEnabled'])
        self.assertEqual(json.loads((target/'definitions.json').read_text()),manifest)
        self.assertEqual(manifest['jobs'][0]['definition']['schedule'],src['jobs'][0]['schedule'])
        self.assertEqual(manifest['jobs'][0]['definition']['repeat'],src['jobs'][0]['repeat'])

    def test_concrete_config_and_private_prompt_never_export(self):
        src = fixture(); src['jobs'][0]['prompt'] = 'Portfolio quantity 456 shares; token=not-public'
        m = export_jobs(src,'UTC'); text=json.dumps(m)
        for private in ('456','not-public','/home/synthetic-example','C123' + '456789'):
            self.assertNotIn(private,text)
        self.assertIn('Portfolio quantity',text)
        self.assertIn('${JOB_',text)
        self.assertNotIn('last_run_at',text)

    def test_private_substitutions_lossless_and_tampering_rejected(self):
        from verify_source import verify
        src=fixture();src['jobs'][0]['prompt']='Portfolio-blind; 27 SIL (Micro Silver) contracts at $123.45; --contracts 27. CANONICAL RESEARCH TIER CONTRACT [SILENT]'
        m=export_jobs(src,'UTC')
        self.assertTrue(verify(src,m)['losslessAllFieldsReconstruction'])
        self.assertIn('CANONICAL RESEARCH TIER CONTRACT',m['jobs'][0]['definition']['prompt'])
        self.assertNotIn('27 SIL',m['jobs'][0]['definition']['prompt'])
        m['jobs'][0]['definition']['prompt']='changed instruction'
        with self.assertRaises(ValueError):verify(src,m)

    def test_generic_account_guardrails_preserved(self):
        src=fixture(); src['jobs'][0]['prompt']='Portfolio-blind analysis; never expose private account values. [SILENT]'
        m=export_jobs(src,'UTC')
        self.assertEqual(src['jobs'][0]['prompt'],m['jobs'][0]['definition']['prompt'])

    def test_safe_prompt_keeps_silence_and_parameterizes_paths(self):
        src=fixture(); src['jobs'][0]['prompt']='Read /home/synthetic-example/data.json then [SILENT]; dedupe once.'
        m=export_jobs(src,'UTC')
        prompt=m['jobs'][0]['definition']['prompt']
        self.assertIn('[SILENT]; dedupe once.',prompt)
        self.assertNotIn('/root',prompt)
        self.assertTrue(validate(m)['valid'])

    def test_refuses_unsafe_or_existing_targets(self):
        m=export_jobs(fixture(),'UTC')
        for path in (str(Path.home() / '.hermes'),'/tmp','relative','/tmp/other-home','/tmp/analyst-job-scratch-../x'):
            with self.subTest(path=path), self.assertRaises(ValueError): scratch_import(m,path)
        with tempfile.TemporaryDirectory(prefix='analyst-job-scratch-') as path:
            with self.assertRaises(ValueError): scratch_import(m,path)
        with tempfile.TemporaryDirectory() as path:
            link=Path('/tmp')/('analyst-job-scratch-'+uuid.uuid4().hex)
            link.symlink_to(path); self.addCleanup(link.unlink)
            with self.assertRaises(ValueError): scratch_import(m,link)

    def test_fail_closed_mutations(self):
        mutations = [lambda m:m.update(sourceCount=2),lambda m:m['jobs'].append(copy.deepcopy(m['jobs'][0])),lambda m:m['jobs'][0]['definition'].update(enabled=True),lambda m:m['jobs'][0]['definition'].update(script='/tmp/run.py'),lambda m:m['jobs'][0]['definition'].update(prompt='${UNDECLARED}'),lambda m:m['jobs'][0].update(sourceState='completed'),lambda m:m['jobs'][0]['definition']['repeat'].update(completed=-1),lambda m:m['jobs'][0]['definition']['schedule'].update(expr='bad')]
        for mutate in mutations:
            m=export_jobs(fixture(),'UTC'); mutate(m)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):validate(m)

    def test_strict_schema_and_configuration(self):
        mutations = [
            lambda m:m['jobs'][0]['definition'].pop('model'),
            lambda m:m['jobs'][0]['definition']['schedule'].update(injected=True),
            lambda m:m['jobs'][0]['definition']['schedule'].update(expr='99 9 * * *'),
            lambda m:m['jobs'][0]['definition'].update(enabled_toolsets='terminal'),
            lambda m:m['jobs'][0]['definition'].update(context_from=['missing']),
            lambda m:m['jobs'][0]['definition'].update(no_agent='false'),
            lambda m:m['jobs'][0]['definition'].update(deliver='slack:private'),
            lambda m:m['jobs'][0]['definition']['repeat'].update(times=3),
            lambda m:m['jobs'][0].update(intendedEnabled=False),
            lambda m:m['coverage']['sourceStateCounts'].update(scheduled=9),
        ]
        for mutate in mutations:
            m=export_jobs(fixture(),'UTC');mutate(m)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):validate(m)

    def test_configured_live_home_refused(self):
        from unittest.mock import patch
        target='/tmp/analyst-job-scratch-'+uuid.uuid4().hex
        with patch.dict('os.environ', {'HERMES_HOME':target}):
            with self.assertRaises(ValueError):scratch_import(export_jobs(fixture(),'UTC'),target)
        self.assertFalse(Path(target).exists())

    def test_synthetic_example_roundtrip_and_tamper_detection(self):
        from job_definitions import verify_roundtrip
        m=json.loads(Path(__file__).with_name('definitions.json').read_text())
        target=Path('/tmp')/('analyst-job-scratch-'+uuid.uuid4().hex)
        scratch_import(m,target);self.addCleanup(__import__('shutil').rmtree,target)
        self.assertEqual(verify_roundtrip(m,target)['count'],m['sourceCount'])
        p=target/'cron/jobs.json';data=json.loads(p.read_text())
        data['jobs'][0]['repeat']['completed']=0;p.write_text(json.dumps(data))
        with self.assertRaises(ValueError):verify_roundtrip(m,target)

    def test_source_digest_detects_redacted_change_not_runtime_ticks(self):
        from job_definitions import source_configuration_digest
        src=fixture()['jobs'];before=source_configuration_digest(src)
        src[0]['repeat']['completed'] += 1;src[0]['last_run_at']='synthetic runtime'
        self.assertEqual(before,source_configuration_digest(src))
        src[0]['script']='/home/synthetic-changed/script.py'
        self.assertNotEqual(before,source_configuration_digest(src))

    def test_checked_in_coverage_and_source_states(self):
        path=Path(__file__).with_name('definitions.json')
        m=json.loads(path.read_text()); validate(m)
        self.assertEqual(m['coverage']['sourceIds'],sorted(j['sourceId'] for j in m['jobs']))
        self.assertEqual(sum(m['coverage']['sourceStateCounts'].values()),m['sourceCount'])
        self.assertTrue(all(j['disposition'] in ('external-blocked','deferred-disabled') for j in m['jobs']))

if __name__=='__main__':unittest.main()
