"""Synthetic privacy regressions; no original private values or fingerprints."""
import json
from pathlib import Path
import tempfile
import unittest
from privacy_scan import categories, inspect

class PrivacyTests(unittest.TestCase):

    def test_forbidden_synthetic_inputs(self):
        cases = [
            ('personal_email', 'notify = "synthetic-person@mail.invalid.test"'),
            ('private_absolute_root', 'path = "/root/synthetic-private/runtime"'),
            ('private_absolute_root', 'path = "/home/synthetic-person/runtime"'),
            ('deployment_identifier', 'deployment = "dpl_SYNTHETIC123456789"'),
            ('deployment_identifier', 'channel = "C1234567890"'),
            ('deployment_identifier', 'job = "abcd1234ef56"'),
            ('operational_endpoint', 'target = "https://synthetic-target.vercel.app"'),
            ('private_account_identifier', 'account = "DU987654"'),
            ('owner_financial_association', "# Owner's holdings: SYNTH"),
            ('owner_financial_association', "# Will's owned symbol: SYNTH"),
            ('private_financial_setting', 'account_value = 731.25'),
            ('private_financial_setting', 'DEFAULT_PORTFOLIO_DENOMINATOR = 731.25'),
            ('private_financial_setting', 'account_equity = os.environ.get("EQUITY", 731.25)'),
            ('hardcoded_private_account_configuration', 'HOLDINGS = ["SYNTH"]'),
            ('hardcoded_private_account_configuration', 'BROKER_ACCOUNT = "synthetic-but-hardcoded"'),
        ]
        for expected, sample in cases:
            with self.subTest(category=expected):
                self.assertIn(expected, categories('sample.py', sample))

    def test_public_and_explicit_config_inputs(self):
        for sample in [
            '# Copyright Will Cheung; https://github.com/willcheung/example',
            'email = "research@example.com"',
            'HOLDINGS = []',
            'account_value = None',
            'account_value = os.environ.get("PRIVATE_VALUE")',
            'BROKER_ACCOUNT = required_value("PRIVATE_ACCOUNT")',
            'benchmark_price = 731.25',
            '# Generic privacy guardrail: never expose private account values.',
        ]:
            self.assertEqual(categories('sample.py', sample), [])

    def test_no_filewide_or_comment_bypass(self):
        sample = '# synthetic fixture; privacy-ignore\nemail="synthetic@mail.invalid.test"'
        for path in ['README.md', 'LICENSE', 'tools/staging/test_privacy.py', 'dashboard/test_example.py']:
            self.assertIn('personal_email', categories(path, sample))

    def test_diagnostics_do_not_contain_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = 'synthetic-recipient@mail.invalid.test'
            (root / 'example.txt').write_text(sample)
            findings = inspect(root, ['example.txt'])
            self.assertEqual(findings, [{'path': 'example.txt', 'category': 'personal_email'}])
            self.assertNotIn(sample, json.dumps(findings))

class ExactPolicyTests(unittest.TestCase):
    def test_receipts_are_current_source_bound_and_fail_on_changes(self):
        import hashlib
        from privacy_scan import LINE_POLICY, PATTERNS, EMAIL
        root = Path(__file__).resolve().parents[2]
        for entry in LINE_POLICY:
            with self.subTest(path=entry['path'], category=entry['category']):
                lines = (root / entry['path']).read_text().splitlines()
                matching = [line for line in lines if hashlib.sha256(line.encode()).hexdigest() == entry['line_sha256']]
                self.assertTrue(matching, 'stale exception')
                line = matching[0]
                pattern = EMAIL if entry['category'] == 'personal_email' else PATTERNS[entry['category']]
                self.assertIsNotNone(pattern.search(line), 'unnecessary exception')
                self.assertNotIn(entry['category'], categories(entry['path'], line))
                self.assertIn(entry['category'], categories('unapproved.txt', line))
                self.assertIn(entry['category'], categories(entry['path'], line + ' changed'))
                # A real-shaped value on the same line or a new line cannot ride
                # a synthetic receipt. Tests reuse literal negatives, never secrets.
                negative = pattern.search(line)[0]
                self.assertIn(entry['category'], categories(entry['path'], line + ' ' + negative))
                self.assertIn(entry['category'], categories(entry['path'], line + '\n' + negative))

    def test_every_exception_path_still_detects_private_inputs(self):
        from privacy_scan import LINE_POLICY
        samples = {
            'personal_email': 'contact@synthetic-mail.test',
            'private_absolute_root': '/home/invented-person/data',
            'private_account_identifier': 'DU87654321',
            'owner_financial_association': "Owner's holdings: SYNTH",
            'deployment_identifier': 'dpl_INVENTED987654321',
            'operational_endpoint': 'https://invented-site.vercel.app',
        }
        for path in {entry['path'] for entry in LINE_POLICY}:
            for category, value in samples.items():
                self.assertIn(category, categories(path, '# ' + value))
