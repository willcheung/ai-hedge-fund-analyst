# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate_wiki_data as gen
import public_snapshot as ps
from validate_market_brief import LANE_JOBS, validate_note


class MarketBriefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wiki = self.root / 'wiki'
        self.cron = self.root / 'cron'
        self.briefs = self.wiki / 'daily/briefs'
        self.briefs.mkdir(parents=True)
        self.patcher = patch.multiple(gen, WIKI=self.wiki, CRON_ROOT=self.cron)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def note(self, lane='deep_dive', day='2026-09-06', hour='12'):
        path = self.briefs / f'market_brief_{lane}_{day}.md'
        path.write_text(f'''---
title: "$SYNTHB proof check"
created: {day}T00:00:00Z
updated: {day}T{hour}:00:00Z
type: daily
tags: [daily]
sources: ["tickers/SYNTHB.md", "https://example.com/SYNTHB"]
market_brief_lane: {lane}
job_id: "{LANE_JOBS[lane]}"
tickers: [SYNTHB]
---
# $SYNTHB proof check

$SYNTHB demand supports AI spending, subject to evidence.

## Key points
- $SYNTHB needs margin proof before adding exposure.
- Supply risk remains elevated without new evidence.

## Source trace
- [[tickers/SYNTHB]]
- [Company filing](https://example.com/SYNTHB)
''')
        return path

    def cron_output(self, job_id, name='Macro research', day='2026-09-05', suffix='run'):
        path = self.cron / 'output' / job_id / f'{suffix}.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'# Cron Job: {name}\n**Run Time:** {day}T14:00:00Z\n## Response\nMacro conditions changed materially today.\n- Rates moved and changed the market risk balance.\n')
        return path

    def test_all_lanes_same_day_sort_limit_and_stable_ids(self):
        for i, lane in enumerate(LANE_JOBS):
            self.note(lane, hour=f'{10+i:02}')
        rows = gen.parse_cron_timeline()
        self.assertEqual(len(rows), 6)
        self.assertEqual(len({r['id'] for r in rows}), 6)
        self.assertEqual(rows[0]['jobId'], LANE_JOBS['macro_shift'])
        self.assertEqual(gen.parse_cron_timeline(2), rows[:2])
        self.note('deep_dive', hour='23')
        updated = gen.parse_cron_timeline()
        self.assertEqual(len(updated), 6)
        self.assertEqual(updated[0]['jobId'], LANE_JOBS['deep_dive'])

    def test_migrated_history_status_and_renamed_outputs_excluded(self):
        self.note()
        for job in LANE_JOBS.values():
            self.cron_output(job, name='Macro research', day='2026-09-07')
        self.cron_output('old-publisher', name='Public publishing workflow')
        old = self.cron_output('ordinary', suffix='old')
        new = self.cron_output('ordinary', suffix='new')
        os.utime(old, (1, 1))
        os.utime(new, (2, 2))
        rows = gen.parse_cron_timeline()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['id'], 'ordinary-new')
        self.assertTrue(rows[0]['sourcePath'].startswith('daily/briefs/market_brief_'))

    def test_projection_retains_existing_dto_and_cashtags(self):
        self.note()
        rows = gen.parse_cron_timeline()
        raw = {'cronTimeline': rows, 'dailyJournal': [], 'tickers': [], 'focusTickers': [], 'counts': {}, 'marketPosture': []}
        public = ps.build_public_snapshot(raw, data_as_of='2026-09-06T12:00:00Z', cron_root=self.cron)
        # Research survives; scheduler labels and internal storage paths do not.
        self.assertEqual(public['cronTimeline'][0]['articleBody'], rows[0]['articleBody'])
        self.assertEqual(public['cronTimeline'][0]['summary'], rows[0]['summary'])
        self.assertNotIn('sourcePath', public['cronTimeline'][0])
        self.assertEqual(public['cronTimeline'][0]['jobName'], '$SYNTHB proof check')
        self.assertEqual(public['publications'][0]['title'], '$SYNTHB proof check')
        self.assertEqual(public['publications'][0]['tickers'], ['SYNTHB'])
        self.assertTrue(public['publications'][0]['sources'])
        self.assertIn('$SYNTHB', rows[0]['jobName'])
        self.assertIn('$SYNTHB', rows[0]['summary'])
        self.assertIn('$SYNTHB', rows[0]['highlights'][0])
        self.assertNotIn('$AI', rows[0]['summary'])
        self.assertEqual(rows[0]['articleBody'], validate_note(self.note())[1])
        self.assertIn('https://example.com/SYNTHB', rows[0]['articleBody'])
        self.assertIn('[[tickers/SYNTHB]]', rows[0]['articleBody'])

    def test_validator_allows_urls_paths_and_ordinary_acronyms_unchanged(self):
        path = self.note()
        original = path.read_text()
        validate_note(path)
        self.assertEqual(original, path.read_text())
        result = subprocess.run([sys.executable, str(Path(gen.__file__).with_name('validate_market_brief.py')), str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS', result.stdout)

    def test_invalid_notes_fail_validator_and_generator(self):
        for before, after in [('$SYNTHB demand', 'SYNTHB demand'), ('$SYNTHB demand', '$$SYNTHB demand'), ('$SYNTHB demand', '$SYNTHH demand'), ('tickers: [SYNTHB]', 'tickers: SYNTHB'), ('job_id: "synthetic-job-05"', 'job_id: "wrong"'), ('## Key points', '## Missing')]:
            with self.subTest(after=after):
                path = self.note()
                path.write_text(path.read_text().replace(before, after))
                with self.assertRaises(ValueError):
                    validate_note(path)
                with self.assertRaises(ValueError):
                    gen.parse_cron_timeline()

    def test_sentence_punctuation_class_shares_and_empty_macro_manifest(self):
        path = self.note()
        path.write_text(path.read_text().replace('$SYNTHB demand', 'SYNTHB. Demand'))
        with self.assertRaisesRegex(ValueError, 'bare ticker SYNTHB'):
            validate_note(path)
        path = self.note()
        path.write_text(path.read_text().replace('SYNTHB', 'SYNTH.N'))
        validate_note(path)
        path = self.note('macro_shift')
        path.write_text(path.read_text().replace('tickers: [SYNTHB]', 'tickers: []').replace('$SYNTHB', 'Macro'))
        validate_note(path)

    def test_opt_in_only_and_canonical_brief_untouched(self):
        canonical = self.briefs / '2026-09-06.md'
        canonical.write_text('# Canonical daily brief\nUnchanged sections.')
        (self.briefs / 'publishing_history.md').write_text('Published publicly!')
        self.note()
        self.assertEqual(len(gen.parse_cron_timeline()), 1)
        self.assertEqual(canonical.read_text(), '# Canonical daily brief\nUnchanged sections.')


if __name__ == '__main__':
    unittest.main()
