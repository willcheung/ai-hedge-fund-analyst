# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate_wiki_data as g
from weekly_stock_analysis import weekly_selection
from macro_presentation import macro_row, neutral_macro_text
from public_content import sanitize_legacy, adapt_legacy, normalize_publication

class PresentationTest(unittest.TestCase):
    def setUp(self):
        scope = patch("weekly_stock_analysis.HISTORICAL_REPORTS", {('synthetic-job-08', '2026-09-06_23-20-25'): ('SYNTHC', 'raw/papers/SYNTHC_hybrid_deep_dive_2026-09-06.md')})
        scope.start()
        self.addCleanup(scope.stop)

    def test_weekly_new_and_historical_ids(self):
        for job in ('synthetic-job-08', 'synthetic-job-0c'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); p = root / 'output' / job; p.mkdir(parents=True)
                (root / 'tickers').mkdir(); (root / 'tickers/SYNTHC.md').write_text('---\ntitle: SYNTHC — Synthetic Optics\n---\n')
                (p / '2026-09-06_23-20-25.md').write_text('# Cron Job: Weekly Stock Analysis\n**Run Time:** 2026-09-06 23:20:25\n## Response\n# SYNTHC — synthetic demand, with incomplete valuation inputs\n\nDecision: WAIT for September 10 proof.\n\n## Why selected this week\nA future synthetic update can clarify margins. SYNTHD was a runner-up, NOT underwritten.\n')
                with patch.object(g,'WIKI',root), patch.object(g,'CRON_ROOT',root), patch.object(g,'load_cron_jobs',return_value=[]):
                    rows = g.parse_cron_timeline()
                self.assertEqual(rows[0]['category'], 'Weekly Stock Analysis')
                self.assertIn('Synthetic Optics', rows[0]['jobName'])
                raw = {'cronTimeline':rows}
                self.assertIn('A future synthetic update', str(sanitize_legacy(raw)))
                self.assertIn('NOT underwritten', str(adapt_legacy(raw)))

    def test_exact_report_only_no_cross_run_or_financial_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p=root/'raw/papers/SYNTHC_hybrid_deep_dive_2026-09-06.md';p.parent.mkdir(parents=True)
            p.write_text('# SYNTHC — Hybrid War Room\n## Candidate Selection\nA future synthetic update clarify order conversion.\n## Decision\nWAIT.\n')
            response='## SYNTHC — synthetic demand, with incomplete valuation inputs'
            self.assertEqual(weekly_selection('synthetic-job-08','2026-09-06_23-20-25',response,root),'A future synthetic update clarify order conversion.')
            self.assertEqual(weekly_selection('synthetic-job-08','2026-09-05_23-20-25',response,root),'')
            self.assertEqual(weekly_selection('synthetic-job-08','2026-09-06_23-20-25','Revenue $8.25M. SYNTHC.',root),'')

    def test_macro_keeps_authored_stance_confidence_without_inventory(self):
        old={'jobId':'synthetic-job-0d','jobName':'Macro Transcript Read','summary':'Macro transcript source stance: cautious/selective — AI demand is real, but not enough to justify more risk.','highlights':['Public presenter warning — https://media.example.com/watch/abc — stance: neutral/cautious — confidence: medium after primary-source cross-check']}
        original=copy.deepcopy(old); row=macro_row(old); text=json.dumps(row)
        self.assertEqual(old, original)
        for bad in ('Public presenter','media.example.com','primary-source'): self.assertNotIn(bad,text)
        for good in ('cautious/selective','not enough','neutral/cautious','evidence confidence: medium'): self.assertIn(good,text)
        self.assertEqual(neutral_macro_text(neutral_macro_text(row['summary'])),row['summary'])
        self.assertEqual(macro_row({'jobId':'company','summary':'CNBC reported Synthetic Devices revenue rose.'})['summary'],'CNBC reported Synthetic Devices revenue rose.')

    def test_empty_macro_receipt_does_not_resurrect_prior_commentary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/'output/synthetic-job-0d'; p.mkdir(parents=True)
            (p/'2026-09-07_02-05-57.md').write_text('# Cron Job: Daily Macro Transcript Analysis\n**Run Time:** 2026-09-07 02:05:57\n## Response\n# Macro transcript monitor\nNo new usable macro-source .txt transcripts were modified in the 24h lookback, so no evening macro transcript brief was produced.\n')
            with patch.object(g,'WIKI',root), patch.object(g,'CRON_ROOT',root), patch.object(g,'load_cron_jobs',return_value=[]):
                self.assertEqual(g.parse_cron_timeline(), [])

    def test_retained_macro_publication_cannot_resurrect_names_urls(self):
        record={'schemaVersion':1,'id':'brief:macro','jobId':'synthetic-job-0d','type':'brief','title':'Evening Macro Transcript Read','summary':'Macro transcript source stance: cautious.','publishedAt':None,'informationAt':None,'tickers':[], 'sections':[{'heading':'Research','markdown':'Public presenter — synthetic title — https://media.example.com/watch/abc — stance: neutral — confidence: medium','sourceIds':['a']}], 'sources':[{'id':'a','title':'media.example.com','url':'https://media.example.com/watch/abc'}]}
        out=normalize_publication(record)
        self.assertEqual(out['title'],'Macro Read')
        self.assertEqual(out['sources'],[])
        self.assertNotIn('media.example.com',json.dumps(out))
        self.assertEqual(normalize_publication(out),out)

if __name__=='__main__': unittest.main()
