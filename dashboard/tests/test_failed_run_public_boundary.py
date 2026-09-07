# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from generate_wiki_data import cron_response_from_output
from public_content import clean_narrative, normalize_publication, PublicationError

class FailedRunBoundaryTests(unittest.TestCase):
    def test_prompt_without_response_is_never_research(self):
        text='# Cron Job: Earnings\n**Run Time:** 2026-09-06\n\n## Prompt\n[IMPORTANT: The user has invoked a skill.]\nRevenue $19M.\n## Error\nFailed.'
        self.assertEqual(cron_response_from_output(text),'')
    def test_actual_response_and_headless_output_survive(self):
        self.assertEqual(cron_response_from_output('# Cron Job: Earnings\n## Prompt\nInstructions\n## Response\nRevenue rose 12%.'),'Revenue rose 12%.')
        self.assertIn('Revenue',cron_response_from_output('# Cron Job: Scan\n\n**Run Time:** yesterday\n\n# Result\nRevenue rose 12%.'))
    def test_operational_fallback_and_retained_prompt_are_withheld(self):
        for value in ['The last tool result explains the blocker; the next step is to change strategy instead of repeating the same call.', '[IMPORTANT: The user has invoked the "earnings-proof-gateway" skill, indicating they want you to follow its instructions. The full skill content is loaded below.]','Verification: index rebuilt; 0 lint failures.']:
            self.assertEqual(clean_narrative(value),'')
        self.assertEqual(clean_narrative('Revenue grew 12%. The evidence remains mixed.'),'Revenue grew 12%. The evidence remains mixed.')
