# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from public_content import clean_narrative, sanitize_legacy


class EmptyMonitorResearchTests(unittest.TestCase):
    def test_monitor_receipts_do_not_become_research_updates(self):
        fragments = [
            'No new usable MeetKevin .txt transcripts were modified in the 24h lookback, so no evening macro transcript brief was produced.',
            'Appended log entry: log.md',
            'Minority Mindset remained disabled and was not inspected.',
            'Warnings are pre-existing lint debt; this run introduced no failures.',
            'Wiki learning contract completed anyway:',
            '⚪ Verification:',
        ]
        for fragment in fragments:
            self.assertEqual(clean_narrative(fragment), '')
        value = {'cronTimeline': [{'id': 'empty-run', 'summary': fragments[0], 'highlights': fragments[1:]}]}
        self.assertEqual(sanitize_legacy(value)['cronTimeline'], [])

    def test_actual_research_from_the_same_producer_is_preserved(self):
        value = {'cronTimeline': [{'id': 'real-run', 'summary': 'Revenue grew 20%.', 'highlights': ['Appended log entry: log.md', 'Management warned that demand could slow.']}]}
        result = sanitize_legacy(value)['cronTimeline'][0]
        self.assertEqual(result['summary'], 'Revenue grew 20%.')
        self.assertEqual(result['highlights'], ['Management warned that demand could slow.'])


if __name__ == '__main__':
    unittest.main()
