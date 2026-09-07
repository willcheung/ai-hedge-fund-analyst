"""Only invented symbols and amounts; no market, mail, credentials or broker I/O."""
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import private_config
import market_prefetch
import precious_metals_options as options


SYNTHETIC_TOTAL = 70


class PrivateInputTests(unittest.TestCase):
    def test_missing_holdings_empty_and_no_private_read(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'read_text', side_effect=AssertionError('unexpected read')):
            self.assertEqual(private_config.load_holdings(), [])
            self.assertEqual(market_prefetch.earnings_watchlist(), set(market_prefetch.TICKERS))
            self.assertEqual(options.load_metals_options(), {})

    def test_external_holdings_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private.json'
            with patch.dict(os.environ, {'ANALYST_HOLDINGS_FILE': str(path)}, clear=True):
                for bad in [[], {'holdings': 'SYNTH'}, {'holdings': [12]}, {'holdings': ['']}]:
                    path.write_text(json.dumps(bad))
                    with self.assertRaises(ValueError): private_config.load_holdings()
                path.write_text(json.dumps({'holdings': ['SYNTH', 'FAKE', 'SYNTH']}))
                self.assertEqual(private_config.load_holdings(), ['SYNTH', 'FAKE'])
                self.assertIn('SYNTH', market_prefetch.earnings_watchlist())
                path.write_text('invalid JSON')
                with self.assertRaisesRegex(ValueError, '^ANALYST_HOLDINGS_FILE could not be loaded$'):
                    private_config.load_holdings()

    def test_private_path_must_be_explicit_external_and_readable(self):
        for value in ['', 'relative.json', str(Path(__file__).resolve())]:
            with self.assertRaises(ValueError):
                private_config.load_private_json('EXAMPLE_PRIVATE_FILE', path=value)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                options.load_metals_options(str(Path(directory) / 'absent.json'))

    def test_json_rejects_ambiguous_values_and_path_errors_without_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.json'
            for raw in ['{"holdings": [], "holdings": ["SYNTH"]}',
                        '{"value": NaN}', '{"value": Infinity}']:
                path.write_text(raw)
                with self.assertRaisesRegex(ValueError, '^EXAMPLE_PRIVATE_FILE could not be loaded$'):
                    private_config.load_private_json('EXAMPLE_PRIVATE_FILE', path=str(path))
            path.unlink()
            path.symlink_to(path)
            with self.assertRaisesRegex(ValueError, '^EXAMPLE_PRIVATE_FILE could not be loaded$'):
                private_config.load_private_json('EXAMPLE_PRIVATE_FILE', path=str(path))
            with self.assertRaises(ValueError):
                private_config.load_private_json('EXAMPLE_PRIVATE_FILE', path=directory)

    def test_private_input_symlinks_cannot_attach_to_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'alias.json'
            path.symlink_to(Path(__file__).resolve())
            with self.assertRaises(ValueError):
                private_config.load_private_json('EXAMPLE_PRIVATE_FILE', path=str(path))
        # Use a temporary synthetic checkout instead of modifying repository input.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / 'checkout/automation/private_config.py'
            module.parent.mkdir(parents=True)
            external = root / 'private.json'
            external.write_text('{}')
            alias = module.parent / 'alias.json'
            alias.symlink_to(external)
            with patch.object(private_config, '__file__', str(module)), self.assertRaises(ValueError):
                private_config.load_private_json('EXAMPLE_PRIVATE_FILE', path=str(alias))

    def test_option_strike_string_is_supported_in_fragile_leg(self):
        legs = options._summarize_fragile_legs(
            [{'expiration': '2000-01-01', 'strike': '12.5', 'type': 'call'}], None)
        self.assertIn('12.5C', legs[0])

    def test_options_allocation_unknown_or_explicit(self):
        payload = {'summary': {'by_underlying': {'SYNTH': {'market_value': 7}}}}
        lines = options.format_metals_options_section(payload, 'SYNTH')
        self.assertIn('account allocation unavailable', '\n'.join(lines))
        self.assertNotIn('% of', '\n'.join(lines))
        lines = options.format_metals_options_section(payload, 'SYNTH', account_value=SYNTHETIC_TOTAL)
        self.assertIn('10.0% of configured account value', '\n'.join(lines))
        for invalid in [0, -1, True, float('nan'), float('inf'), 'unknown']:
            with self.assertRaises(ValueError):
                options.format_metals_options_section(payload, 'SYNTH', account_value=invalid)

    def test_external_options_cache_without_summary_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'options.json'
            payload = {'positions': [], 'account_value': SYNTHETIC_TOTAL}
            path.write_text(json.dumps(payload))
            with patch.dict(os.environ, {'ANALYST_METALS_OPTIONS_FILE': str(path)}, clear=True):
                self.assertEqual(options.load_metals_options(), payload)

    def test_newsletter_fails_before_optional_imports_or_side_effects(self):
        # Execute only the stdlib/configuration prefix, before optional SDK imports.
        # The full optional media stack is deliberately absent from offline dependencies.
        tree = ast.parse(Path(__file__).with_name('newsletter_summarizer.py').read_text())
        prefix = []
        for node in tree.body:
            if isinstance(node, ast.Import) and any(n.name.startswith('google') for n in node.names): break
            prefix.append(node)
        code = compile(ast.Module(body=prefix, type_ignores=[]), '<newsletter-config>', 'exec')
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'NEWSLETTER_TARGET_EMAIL is required'):
            exec(code, {})
        with patch.dict(os.environ, {'NEWSLETTER_TARGET_EMAIL': 'reader@example.com', 'NEWSLETTER_TOKEN_FILE': '/tmp/synthetic-token', 'NEWSLETTER_CLIENT_SECRETS_FILE': '/tmp/synthetic-client'}, clear=True):
            namespace = {}
            exec(code, namespace)
            self.assertEqual(namespace['TARGET_EMAIL'], 'reader@example.com')

if __name__ == '__main__': unittest.main()
