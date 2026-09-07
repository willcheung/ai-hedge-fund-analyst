# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
"""Macro presentation fixtures: no source-record writes or snapshot generation."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate_wiki_data as gen
from public_content import clean_narrative, sanitize_legacy, adapt_legacy

NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


class MacroReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wiki = Path(self.tmp.name)
        self.scope = patch.object(gen, 'WIKI', self.wiki)
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def note(self, lane, day, body):
        path = self.wiki / 'daily' / lane / f'{lane}_{day}.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'---\ncreated: {day}\n---\n{body}')
        return path

    def test_available_views_remain_opinions_not_consensus(self):
        a = self.note('meetkevin', '2026-09-06', '## Creator Recommendations / Opinions\n- Bullish: AI can reduce costs; Synthetic Devices revenue remains strong.\n- Bearish: Oil pressure may keep yields high.\n')
        b = self.note('fastmoney', '2026-09-06', '## Macro Themes\n### Rates\n- [01:00-01:04] Lower oil prices may ease inflation. ^[raw/transcripts/example.json]\n')
        original = {p: p.read_bytes() for p in (a,b)}
        read = gen.macro_opinion_read(now=NOW)
        text = ' '.join(read)
        for fact in ('AI can reduce costs', 'Synthetic Devices revenue', 'yields high', 'Lower oil prices'):
            self.assertIn(fact, text)
        for word in ('MeetKevin', 'Fast Money', 'YouTube', 'consensus', 'confidence', 'agree'):
            self.assertNotIn(word, text)
        self.assertIn('2 available commentary notes', text)
        for p, raw in original.items(): self.assertEqual(p.read_bytes(), raw)

    def test_degraded_latest_never_resurrects_older_opinion(self):
        self.note('meetkevin', '2026-09-06', '## Creator Recommendations / Opinions\n- Bullish: AI can reduce costs.\n')
        self.note('fastmoney', '2026-09-05', '## Macro Themes\n- Stocks may rally.\n')
        self.note('fastmoney', '2026-09-06', '# Fast Money degraded transcript\nTreat this source as degraded/no-signal for today.\n')
        text = ' '.join(gen.macro_opinion_read(now=NOW))
        self.assertIn('1 available commentary note', text)
        self.assertIn('unavailable', text)
        self.assertNotIn('Stocks may rally', text)
        self.assertNotIn('mixed', text.lower())

    def test_stale_empty_future_and_private_are_not_opinions(self):
        cases = [('2026-09-01', '## Macro Themes\n- Stocks may rally.\n'),
                 ('2026-09-06', '## Macro Themes\n- Stocks may rally…\n'),
                 ('2026-09-09', '## Macro Themes\n- Stocks may rally.\n'),
                 ('2026-09-06', '## Macro Themes\n- Our portfolio value is $100000.\n')]
        for day, body in cases:
            with self.subTest(day=day, body=body):
                for p in self.wiki.glob('daily/*/*.md'): p.unlink()
                self.note('fastmoney', day, body)
                text = ' '.join(gen.macro_opinion_read(now=NOW))
                self.assertIn('No current publishable commentary', text)
                self.assertNotIn('Stocks may rally', text)
                self.assertNotIn('$100000', text)

    def test_named_attribution_is_withheld_only_in_macro_projection(self):
        self.note('meetkevin', '2026-09-06', '## Creator Recommendations / Opinions\n- Bullish: Kevin says stocks will rise.\n- Bearish: Synthetic Devices demand may slow.\n')
        text = ' '.join(gen.macro_opinion_read(now=NOW))
        self.assertNotIn('Kevin', text)
        self.assertIn('Synthetic Devices demand may slow', text)
        self.assertEqual(clean_narrative('Kevin says Synthetic Devices revenue grew.'), 'Kevin says Synthetic Devices revenue grew.')

    def test_explicit_private_note_is_not_projected(self):
        self.note('meetkevin', '2026-09-06', 'privacy_class: private\n## Creator Recommendations / Opinions\n- Bullish: Secret analysis suggests stocks may rise.\n')
        text = ' '.join(gen.macro_opinion_read(now=NOW))
        self.assertIn('No current publishable commentary', text)
        self.assertNotIn('Secret', text)


class OpsProseTests(unittest.TestCase):
    def test_exact_ops_receipts_removed_without_losing_evidence_gaps(self):
        text = ('⚠️ Skills not found and skipped: macro-regime-detector, market-breadth-analyzer, exposure-coach. '
                'Upstream TraderMonty scripts supplied a degraded-data fallback. '
                'Six secondary inputs are missing. Synthetic Devices revenue grew 10%.')
        clean = clean_narrative(text)
        self.assertNotIn('Skills not found', clean)
        self.assertNotIn('TraderMonty scripts', clean)
        self.assertIn('incomplete data', clean)
        self.assertIn('Six secondary inputs are missing.', clean)
        self.assertIn('Synthetic Devices revenue grew 10%.', clean)
        self.assertEqual(clean_narrative(clean), clean)

    def test_company_names_and_privacy_boundary_unchanged(self):
        self.assertEqual(clean_narrative('Synthetic Search and Synthetic Retail revenue improved.'), 'Synthetic Search and Synthetic Retail revenue improved.')
        self.assertEqual(clean_narrative('Our portfolio value is $50000.'), '')


if __name__ == '__main__': unittest.main()
