"""Exercise the same closed observations at the Python publication boundary."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import public_snapshot as ps
from stage_demo import build_demo


class MacroMeterContractTests(unittest.TestCase):
    def test_shared_observation_cases(self):
        snapshot, _ = build_demo()
        cases = json.loads((ROOT / 'tests/fixtures/meter-observation-cases.json').read_text())
        for case in cases:
            with self.subTest(case=case['name']):
                candidate = {**snapshot, 'macroRegimeMeter': case['value']}
                if case['valid']:
                    ps.validate_public_snapshot_schema(candidate)
                else:
                    with self.assertRaises((ValueError, ps.PrivacyError)):
                        ps.validate_public_snapshot_schema(candidate)

    def test_shared_invalid_mutations(self):
        snapshot, _ = build_demo()
        mutations = json.loads((ROOT / 'tests/fixtures/meter-invalid-cases.json').read_text())
        for mutation in mutations:
            with self.subTest(case=mutation['name']):
                candidate = copy.deepcopy(snapshot)
                target = candidate['macroRegimeMeter']
                for key in mutation['path'][:-1]:
                    target = target[int(key) if isinstance(target, list) else key]
                key = mutation['path'][-1]
                target[int(key) if isinstance(target, list) else key] = mutation['value']
                with self.assertRaises((ValueError, ps.PrivacyError)):
                    ps.validate_public_snapshot_schema(candidate)

    def test_synthetic_snapshot_is_accepted_without_mutation(self):
        snapshot, _ = build_demo()
        before = copy.deepcopy(snapshot)
        ps.validate_public_snapshot_schema(snapshot)
        self.assertEqual(snapshot, before)

    def test_offline_generator_serializes_supplied_meter_without_prose_cleaning(self):
        """Run the real CLI pipeline on temporary sources, never the live producer."""
        import contextlib
        import io
        import tempfile
        from unittest.mock import patch
        import generate_wiki_data as gen
        import publish_wiki_data as publisher

        meter = json.loads((ROOT / 'tests/fixtures/demo-dashboard.json').read_text())['macroRegimeMeter']
        posture = {'name': 'Macro Regime', 'artifactDate': '2000-01-01'}
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            wiki, cron = root / 'wiki', root / 'cron'
            (wiki / 'tickers').mkdir(parents=True)
            cron.mkdir()
            artifact = wiki / 'data' / 'meter.json'
            artifact.parent.mkdir()
            artifact.write_text(json.dumps(meter))
            output = root / 'snapshot.json'
            # Unrelated parsers are isolated, but builder, inventory, projection,
            # schema validation, canonical serialization and atomic write are real.
            for name, value in {
                'parse_tickers': [], 'canonical_macro_posture': posture, 'plain_report': None,
                'parse_daily_journal': [], 'parse_agentic_trading_reports': [],
                'load_intraday_equity_watchdog': {}, 'parse_market_graphs': [],
                'parse_current_asymmetric_shortlist': None, 'parse_ai_projection_exhibits': None,
                'parse_ai_war_room_complete_data': None, 'parse_sources': [], 'parse_cron_timeline': [],
            }.items():
                stack.enter_context(patch.object(gen, name, return_value=value))
            for name in ('WIKI', 'OUT', 'CRON_ROOT', 'OFFLINE'):
                stack.enter_context(patch.object(gen, name, getattr(gen, name)))
            argv = ['--wiki-root', str(wiki), '--cron-root', str(cron),
                    '--output', str(output), '--offline', '--quiet']
            # An unreferenced artifact on disk cannot make empty sections fresh.
            # The no-meter success case needs its own dated, represented source.
            with patch.object(gen, 'canonical_macro_posture', return_value=None):
                with self.assertRaisesRegex(SystemExit, 'no represented trusted freshness timestamp'):
                    gen.main(argv)
            self.assertFalse(output.exists())
            self.assertEqual(gen.main(argv), 0)
            without_meter = publisher.parse_snapshot(output.read_bytes())
            self.assertIsNone(without_meter['macroRegimeMeter']['score'])
            self.assertEqual(without_meter['marketPosture'], [posture])
            self.assertEqual(without_meter['dataAsOf'], '2000-01-01T00:00:00Z')
            diagnostics = io.StringIO()
            with contextlib.redirect_stderr(diagnostics):
                self.assertEqual(gen.main([*argv, '--macro-meter', str(artifact)]), 0)
            published = publisher.parse_snapshot(output.read_bytes())
            self.assertEqual(published['macroRegimeMeter'], meter)
            self.assertEqual(published['dataAsOf'], meter['generatedAt'])
            self.assertEqual(json.loads(artifact.read_text()), meter)
            self.assertNotIn('$.macroRegimeMeter', diagnostics.getvalue())
            self.assertIn(str(artifact), [entry.path for entry in ps.input_inventory([wiki])])
            previous = output.read_bytes()
            for bad in (None, {}, {**meter, 'score': 1},
                        {**meter, 'postureInterpretation': 'Noncanonical synthetic interpretation'},
                        {**meter, 'unexpectedPrivateField': 'private'}):
                with self.subTest(bad=bad):
                    artifact.write_text(json.dumps(bad))
                    with self.assertRaises(SystemExit):
                        gen.main([*argv, '--macro-meter', str(artifact)])
                    self.assertEqual(output.read_bytes(), previous)
            artifact.unlink()
            with self.assertRaises(SystemExit):
                gen.main([*argv, '--macro-meter', str(artifact)])
            self.assertEqual(output.read_bytes(), previous)
