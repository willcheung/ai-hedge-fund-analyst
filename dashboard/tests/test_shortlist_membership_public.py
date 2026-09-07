# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
"""Membership classification is source data, never an entry recommendation."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate_wiki_data as generator
from public_content import sanitize_legacy, UNAVAILABLE
from public_snapshot import build_public_snapshot

BUCKETS = ['Buy / Scout Now', 'Wait for Trigger', 'Add After Proof',
           'Research Memory / Not Live Action', 'Kill / Do Not Average']


class MembershipPublicTests(unittest.TestCase):
    def project(self, rows, policy=None):
        raw = {'currentAsymmetricShortlist': {
            'generatedAt': '2026-09-06T05:59:42Z', 'rows': rows,
            'membershipPolicy': policy or {'bucketMode': 'mutually_exclusive'}}}
        with tempfile.TemporaryDirectory() as directory:
            return build_public_snapshot(raw, data_as_of='2026-09-06T05:59:42Z',
                                         cron_root=Path(directory))['currentAsymmetricShortlist']

    def test_all_five_memberships_survive_final_projection_without_eligibility(self):
        rows = [{'symbol': f'T{i}', 'bucket': bucket, 'entryEligible': False,
                 'entryStatus': 'stale', 'capitalEligible': True,
                 'bucketReason': 'Demand improved.', 'quoteAsOf': '2026-09-04T20:00:00Z'}
                for i, bucket in enumerate(BUCKETS)]
        out = self.project(rows, {'bucketMode': 'mutually_exclusive', 'bucketOrder': BUCKETS})
        self.assertEqual(out['membershipPolicy']['bucketOrder'], BUCKETS)
        self.assertEqual([r['bucket'] for r in out['rows']], BUCKETS)
        self.assertEqual(out['generatedAt'], '2026-09-06T05:59:42Z')
        for row in out['rows']:
            self.assertFalse(row['entryEligible'])
            self.assertNotIn('capitalEligible', row)
            self.assertEqual(row['quoteAsOf'], '2026-09-04T20:00:00Z')
        self.assertEqual(sanitize_legacy({'currentAsymmetricShortlist': out})['currentAsymmetricShortlist'], out)

    def test_invalid_or_ambiguous_membership_fails_closed_without_normalization(self):
        for bucket in ['SCOUT', 'Buy / Scout Now ', 'BUY / SCOUT NOW', 'Buy / Scout Now / Wait for Trigger',
                       'My portfolio', None, True, 12, ['Wait for Trigger'], {'bucket': 'Wait for Trigger'}]:
            with self.subTest(bucket=bucket):
                self.assertEqual(self.project([{'symbol': 'AAA', 'bucket': bucket}])['rows'][0]['bucket'], UNAVAILABLE)

    def test_generic_labels_and_other_bucket_paths_are_not_relaxed(self):
        for bucket in BUCKETS:
            out = sanitize_legacy({'bucket': bucket, 'action': bucket,
                                   'tickers': [{'symbol': 'AAA', 'bucket': bucket}],
                                   'currentAsymmetricShortlist': {'actionChanges': [{'toBucket': bucket}]}})
            self.assertEqual(out['bucket'], UNAVAILABLE)
            self.assertEqual(out['action'], UNAVAILABLE)
            self.assertEqual(out['tickers'][0]['bucket'], UNAVAILABLE)
            self.assertEqual(out['currentAsymmetricShortlist']['actionChanges'][0]['toBucket'], UNAVAILABLE)

    def test_private_rows_sections_and_incompatible_policy_are_withheld(self):
        row = {'symbol': 'AAA', 'bucket': BUCKETS[0], 'privacyClass': 'private_local_only'}
        self.assertEqual(self.project([row])['rows'], [])
        self.assertIsNone(sanitize_legacy({'currentAsymmetricShortlist': {
            'privacyClass': 'private', 'rows': [row]}})['currentAsymmetricShortlist'])
        self.assertEqual(self.project([{'symbol': 'AAA', 'bucket': BUCKETS[0]}],
                                     {'bucketMode': 'overlapping'})['rows'][0]['bucket'], UNAVAILABLE)

    def test_conflicting_assignments_are_not_resolved_by_reason(self):
        rows = [{'symbol': 'AAA', 'bucket': bucket, 'bucketReason': 'Demand improved.'} for bucket in BUCKETS[:2]]
        self.assertTrue(all(r['bucket'] == UNAVAILABLE for r in self.project(rows)['rows']))

    def test_parser_to_final_output_preserves_exact_values_and_private_boundary(self):
        source = {'generatedAt': '2026-09-06T05:59:42Z', 'all': [
            {'symbol': 'AAA', 'bucket': BUCKETS[1]},
            {'symbol': 'BAD', 'bucket': ' Wait for Trigger '},
            {'symbol': 'PRIVATE', 'bucket': BUCKETS[0], 'privacy_class': 'private_local_only'}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'data/automation/current_asymmetric_shortlist_latest.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(source))
            with patch.multiple(generator, WIKI=root, CRON_ROOT=root / 'cron', OFFLINE=True):
                parsed = generator.parse_current_asymmetric_shortlist()
            out = build_public_snapshot({'currentAsymmetricShortlist': parsed},
                                        data_as_of=source['generatedAt'], cron_root=root)
        rows = {r['symbol']: r for r in out['currentAsymmetricShortlist']['rows']}
        self.assertEqual(set(rows), {'AAA', 'BAD'})
        self.assertEqual(rows['AAA']['bucket'], BUCKETS[1])
        self.assertEqual(rows['BAD']['bucket'], UNAVAILABLE)


if __name__ == '__main__':
    unittest.main()
