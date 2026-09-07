# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from public_content import sanitize_legacy, UNAVAILABLE


class WorkflowOperationalStatusTests(unittest.TestCase):
    def test_operational_status_enums_survive_at_exact_paths(self):
        paths = [
            '$.sourceHealth.status',
            '$.sourceHealth.sections.marketGraphs.status',
            '$.sourceHealth.sections.tickers.validation',
            '$.sourceHealth.sections.aiProjectionExhibits.producer.latestStatus',
            '$.marketGraphs[0].finalGate',
            '$.marketGraphs[0].graphNodes[1].status',
            '$.marketGraphs[0].decisionEvents[0].gate',
        ]
        for pointer in paths:
            for status in ['pass', 'failed', 'error', 'stale', 'blocked', 'missing', 'paused', 'unknown']:
                with self.subTest(pointer=pointer, status=status):
                    self.assertEqual(sanitize_legacy(status, key=pointer.rsplit('.', 1)[-1], pointer=pointer), status)

    def test_unknown_operational_status_does_not_become_pass_or_raw_text(self):
        for value in ['configured', 'custom_internal_state', '/root/private', 'BUY', '']:
            self.assertEqual(sanitize_legacy(value, key='status', pointer='$.marketGraphs[0].graphNodes[1].status'), 'unknown')

    def test_investment_assessment_is_not_relaxed(self):
        self.assertEqual(sanitize_legacy('stale', key='status', pointer='$.tickers[0].status'), UNAVAILABLE)
        self.assertEqual(sanitize_legacy('failed', key='action', pointer='$.marketGraphs[0].action'), UNAVAILABLE)

    def test_known_workflow_names_survive_without_relaxing_private_or_unknown_labels(self):
        value = {'marketGraphs': [
            {'label': 'Market research checks', 'finalGate': 'pass'},
            {'label': 'Earnings proof gate', 'finalGate': 'degraded'},
            {'label': 'Earnings proof gate', 'privacy_class': 'private_local_only'},
            {'label': '/root/private/account'},
        ]}
        graphs = sanitize_legacy(value)['marketGraphs']
        self.assertEqual([g['label'] for g in graphs[:2]], ['Market research checks', 'Earnings proof gate'])
        self.assertEqual([g['finalGate'] for g in graphs[:2]], ['pass', 'degraded'])
        self.assertFalse(any(g and g.get('privacy_class') == 'private_local_only' for g in graphs))
        self.assertNotIn('/root/private', str(graphs))

    def test_producer_not_applicable_is_not_a_success(self):
        self.assertEqual(sanitize_legacy('not_applicable', key='latestStatus', pointer='$.sourceHealth.sections.tickers.producer.latestStatus'), 'not_applicable')


if __name__ == '__main__':
    unittest.main()
