# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from brief_titles import bounded_research_title, source_brief_title, explicit_title_tickers


class BriefTitlesTest(unittest.TestCase):
    titles = {'SYNTHC': 'SYNTHC — Synthetic Optics', 'AI': 'AI — Synthetic Models', 'SYNTHM': 'SYNTHM — Synthetic Security', 'SYNTHJ': 'SYNTHJ — Synthetic Database'}

    def test_company_identity_comes_from_heading_and_canonical_title(self):
        title = source_brief_title('## SYNTHC — synthetic demand, with incomplete valuation inputs\n\nDecision: NO TRADE / WAIT.', self.titles)
        self.assertEqual(title, '$SYNTHC — Synthetic Optics: synthetic demand, with incomplete valuation inputs')
        self.assertEqual(explicit_title_tickers(title), ['SYNTHC'])

    def test_does_not_mine_financials_or_body_tickers(self):
        self.assertEqual(source_brief_title('Decision: WAIT. $8.25M revenue. SYNTHC\n## SYNTHC — findings', self.titles), '')
        self.assertEqual(source_brief_title('## Market Setup\n$SYNTHC', self.titles), '')
        self.assertEqual(source_brief_title('### SYNTHC — subsection only', self.titles), '')

    def test_macro_and_multi_company_do_not_acquire_single_ticker(self):
        for heading in ['Evening Macro Transcript Read — 2026-09-06', 'AI infrastructure demand', 'SYNTHC — orders versus SYNTHJ demand']:
            self.assertEqual(source_brief_title('## ' + heading, self.titles), heading)
            self.assertEqual(explicit_title_tickers(heading), [])

    def test_private_machine_and_overlong_titles_fail_closed(self):
        for title in ['Cron Job: Weekly Hybrid Stock Deep Dive', 'earnings-proof-gateway', 'My account buying power is $100000', 'Research /root/private/output.md', 'x' * 171]:
            self.assertEqual(bounded_research_title(title), '')

    def test_condition_and_negation_are_not_rewritten(self):
        title = source_brief_title('## $AI — No buy until revenue proof', self.titles)
        self.assertIn('No buy until revenue proof', title)
        # Existing narrative policy withholds internal proof-gate terminology;
        # title recovery must not bypass that policy or erase a negative verdict.
        self.assertEqual(source_brief_title('## SYNTHM — Headline Beat, Proof Gate Failed', self.titles), '')

    def test_generator_uses_sourced_title_not_scheduler_name(self):
        import generate_wiki_data as g
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        with TemporaryDirectory() as root:
            root = Path(root)
            (root / 'tickers').mkdir()
            (root / 'tickers/SYNTHC.md').write_text('---\ntitle: SYNTHC — Synthetic Optics\n---\n')
            output = root / 'output/job123'
            output.mkdir(parents=True)
            (output / '2026-09-06_23-20-25.md').write_text('# Cron Job: Weekly Hybrid Stock Deep Dive\n**Run Time:** 2026-09-06 23:20:25\n## Response\n## SYNTHC — synthetic demand, with incomplete valuation inputs\n\nDecision: NO TRADE / WAIT for September 10 proof.\n')
            with patch.object(g, 'WIKI', root), patch.object(g, 'CRON_ROOT', root), patch.object(g, 'load_cron_jobs', return_value=[]):
                row = g.parse_cron_timeline()[0]
            self.assertEqual(row['jobName'], '$SYNTHC — Synthetic Optics: synthetic demand, with incomplete valuation inputs')
            self.assertEqual(row['jobId'], 'job123')
            self.assertEqual(row['id'], 'job123-2026-09-06_23-20-25')
            self.assertIn('NO TRADE / WAIT', row['summary'])


if __name__ == '__main__':
    unittest.main()
