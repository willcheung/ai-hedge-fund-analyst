# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
"""Engineering regression fixtures: retired metadata cannot revive a feature."""
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate_wiki_data as gen
from public_snapshot import build_public_snapshot, project_dto, PrivacyError
from public_content import sanitize_legacy


class RetiredBriefAnnotationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'tickers').mkdir()
        self.path = self.root / 'daily/briefs/2026-09-06.md'
        self.path.parent.mkdir(parents=True)
        self.body = '# Engineering brief\n## Market Setup\nOriginal market coverage.\n## Sources\nOriginal earnings source.\n'
        self.annotation = '\n<!-- conviction-change:v1 -->\n{"symbol":"TEST","now":"RETIRED_SENTINEL"}\n<!-- /conviction-change -->\n'
        self.path.write_text(self.body)

    def test_normal_generator_ignores_old_annotation_and_preserves_base(self):
        defaults = {'parse_tickers': [], 'canonical_macro_posture': None,
                    'plain_report': None, 'parse_agentic_trading_reports': [],
                    'load_intraday_equity_watchdog': {}, 'parse_market_graphs': [],
                    'parse_current_asymmetric_shortlist': None,
                    'parse_ai_projection_exhibits': None, 'parse_ai_war_room_complete_data': None,
                    'parse_sources': [], 'parse_cron_timeline': []}
        with ExitStack() as stack:
            stack.enter_context(patch.object(gen, 'WIKI', self.root))
            for name, value in defaults.items():
                stack.enter_context(patch.object(gen, name, return_value=value))
            before = gen.build_legacy_sections()
            self.path.write_text(self.body + self.annotation)
            after = gen.build_legacy_sections()
            self.assertEqual(gen.read(self.path), self.body)
        self.assertTrue(before['dailyJournal'])
        self.assertEqual(before, after)
        self.assertNotIn('convictionChange', after)
        self.assertNotIn('RETIRED_SENTINEL', json.dumps(after))
        self.assertEqual(self.path.read_text(), self.body + self.annotation)
        # Even an old raw payload cannot bypass the public section allowlist.
        after['convictionChange'] = {'status': 'initial', 'reason': 'RETIRED_SENTINEL'}
        public = build_public_snapshot(after, data_as_of='2026-09-06T00:00:00Z', cron_root=self.root / 'cron')
        self.assertNotIn('convictionChange', json.dumps(public))
        self.assertNotIn('RETIRED_SENTINEL', json.dumps(public))
        self.assertEqual(public['dailyJournal'], project_dto(sanitize_legacy(before['dailyJournal']), section='dailyJournal'))
        with self.assertRaises(PrivacyError):
            project_dto(after['convictionChange'], section='convictionChange')

    def test_unclosed_metadata_keeps_later_original_section(self):
        later = '## Later original section\nOriginal historical callout.\n'
        self.path.write_text(self.body + '\n<!-- conviction-change:v1 -->\n{malformed metadata\n' + later)
        with patch.object(gen, 'WIKI', self.root):
            self.assertEqual(gen.read(self.path), self.body + later)

    def test_schema_does_not_advertise_retired_section(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / 'schema/public-snapshot-v1.schema.json').read_text())
        self.assertNotIn('convictionChange', json.dumps(schema))
