from unittest.mock import patch
# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import copy
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from weekly_stock_analysis import retain_verified_weekly_history

class RetainedWeeklyHistoryTest(unittest.TestCase):
    def setUp(self):
        scope = patch("weekly_stock_analysis.HISTORICAL_REPORTS", {('synthetic-job-08', '2026-09-06_23-20-25'): ('SYNTHC', 'raw/papers/SYNTHC_hybrid_deep_dive_2026-09-06.md')})
        scope.start()
        self.addCleanup(scope.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paper = self.root / 'raw/papers/SYNTHC_hybrid_deep_dive_2026-09-06.md'
        self.paper.parent.mkdir(parents=True)
        self.paper.write_text('# SYNTHC — Hybrid War Room — 2026-09-06\n\n## Candidate Selection\nA future synthetic update can clarify margins.\n\n## Decision\nWAIT.\n')
        self.row = {'id':'synthetic-job-08-2026-09-06_23-20-25','jobId':'synthetic-job-08','runTime':'2026-09-06 23:20:25','jobName':'$SYNTHC — Synthetic Optics: valuation needs repair','category':'Other research job','summary':'Decision: WAIT.','highlights':['Confirmed orders.']}
    def tearDown(self):
        self.tmp.cleanup()
    def test_retains_exact_published_run_without_mutating_evidence(self):
        prior = copy.deepcopy(self.row)
        out = retain_verified_weekly_history([], [self.row], self.root)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['category'], 'Weekly Stock Analysis')
        self.assertIn('A future synthetic update', out[0]['articleBody'])
        for key in ['id','jobId','runTime','jobName','summary','highlights']:
            self.assertEqual(out[0][key], prior[key])
        self.assertEqual(self.row, prior)
        self.assertEqual(retain_verified_weekly_history(out,[self.row],self.root),out)
    def test_selection_reaches_retained_publication_without_clock_changes(self):
        from public_content import adapt_legacy
        old = adapt_legacy({'cronTimeline':[self.row]})
        row = retain_verified_weekly_history([], [self.row], self.root)[0]
        row['articleBody'] += '\n\nFirst complete selection sentence. Second complete selection sentence.'
        row['highlights'] = ['Confirmed orders and cash flow need verification.'] * 15
        updated = adapt_legacy({'cronTimeline':[row]}, previous=old)
        self.assertIn('Why selected this week', str(updated))
        self.assertEqual(updated[0]['publishedDate'], old[0]['publishedDate'])
        self.assertEqual(updated[0]['informationAt'], old[0]['informationAt'])
        unsafe = {**row, 'articleBody': row['articleBody'] + '\nAPI key: secret internal value /root/private'}
        self.assertEqual(adapt_legacy({'cronTimeline':[unsafe]}, previous=updated),updated)
    def test_no_source_no_row_no_invented_receipt(self):
        self.assertEqual(retain_verified_weekly_history([],[],self.root),[])
        self.paper.unlink()
        self.assertEqual(retain_verified_weekly_history([],[self.row],self.root),[])
    def test_identity_timestamp_title_mismatches_fail_closed(self):
        for key,value in [('id','wrong'),('jobId','synthetic-job-0c'),('runTime','2026-09-07 23:20:25'),('jobName','$SYNTHB — wrong company')]:
            row={**self.row,key:value}
            self.assertEqual(retain_verified_weekly_history([],[row],self.root),[])
        self.paper.write_text('# SYNTHB — Wrong company\n## Candidate Selection\nA future synthetic update matter.\n')
        self.assertEqual(retain_verified_weekly_history([],[self.row],self.root),[])
