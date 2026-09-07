"""Synthetic-only path and import regressions; run via tools/offline_check.py."""
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import automation_paths as paths


class PathTests(unittest.TestCase):
    def test_optional_operational_inputs_fail_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'ANALYST_WIKI_ROOT is required'):
                paths.configured_text('${ANALYST_WIKI_ROOT}/input.json')
        with mock.patch.dict(os.environ, {'ANALYST_WIKI_ROOT': '/tmp/synthetic-wiki'}, clear=True):
            self.assertEqual(paths.configured_text('${ANALYST_WIKI_ROOT}/input.json'), '/tmp/synthetic-wiki/input.json')

    def test_default_home(self):
        with mock.patch.dict(os.environ, {'HOME': '/tmp/synthetic-home'}, clear=True):
            self.assertEqual(paths.hermes_home(), Path('/tmp/synthetic-home/.hermes'))
            self.assertEqual(paths.state_path('x.json'), Path('/tmp/synthetic-home/.hermes/state/x.json'))
            self.assertEqual(paths.secret_path('.env'), Path('/tmp/synthetic-home/.hermes/.env'))

    def test_configured_home_controls_defaults(self):
        with mock.patch.dict(os.environ, {'ANALYST_HERMES_HOME': '/tmp/synthetic-install'}, clear=True):
            self.assertEqual(paths.state_path('x.json'), Path('/tmp/synthetic-install/state/x.json'))
            self.assertEqual(paths.secret_path('.env'), Path('/tmp/synthetic-install/.env'))

    def test_independent_overrides_and_no_directory_creation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.dict(os.environ, {'ANALYST_STATE_DIR': str(root/'state'), 'ANALYST_SECRETS_DIR': str(root/'secret')}, clear=True):
                self.assertEqual(paths.state_path('x.json'), root/'state/x.json')
                self.assertEqual(paths.secret_path('.env'), root/'secret/.env')
                self.assertEqual(list(root.iterdir()), [])

    def test_empty_and_relative_overrides_rejected(self):
        for key in ('ANALYST_HERMES_HOME', 'ANALYST_STATE_DIR', 'ANALYST_SECRETS_DIR'):
            for value in ('', ' ', 'relative/path', '~/implicit-expansion'):
                with self.subTest(key=key, value=value), mock.patch.dict(os.environ, {key: value}, clear=True):
                    with self.assertRaises(ValueError):
                        (paths.state_path if key != 'ANALYST_SECRETS_DIR' else paths.secret_path)('x.json')

    def test_path_traversal_rejected(self):
        for value in ('../escape', '/absolute', 'nested/file', '', '.'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                paths.state_path(value)

    def test_missing_configured_secrets_never_fall_back(self):
        import calconviction
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root/'home'
            legacy = home/'.hermes'
            legacy.mkdir(parents=True)
            (legacy/'calconviction_tokens.json').write_text('{"access_token":"SYNTHETIC-DO-NOT-USE"}')
            (legacy/'.env').write_text('SYNTHETIC=DO-NOT-USE\n')
            with mock.patch.dict(os.environ, {'HOME': str(home), 'ANALYST_SECRETS_DIR': str(root/'missing')}, clear=True):
                importlib.reload(calconviction)
                self.assertIsNone(calconviction.load_tokens())
                self.assertEqual(calconviction.load_env(), {})
            importlib.reload(calconviction)

    def test_scanner_import_never_loads_credentials(self):
        import calconviction
        import fetch_x_signals
        with mock.patch.object(calconviction, 'get_access_token', side_effect=AssertionError('credential access during import')) as getter:
            importlib.reload(fetch_x_signals)
            getter.assert_not_called()
            self.assertEqual(fetch_x_signals.BEARER_TOKEN, '')

    def test_modules_use_configured_state_and_secrets(self):
        import calconviction
        import fetch_x_signals
        import calconviction_growth_metrics
        modules = (calconviction, fetch_x_signals, calconviction_growth_metrics)
        with mock.patch.dict(os.environ, {'ANALYST_STATE_DIR': '/tmp/test-state', 'ANALYST_SECRETS_DIR': '/tmp/test-secrets'}, clear=True):
            for module in modules:
                importlib.reload(module)
            self.assertEqual(Path(calconviction.CONFIG_PATH), Path('/tmp/test-secrets/.env'))
            self.assertEqual(fetch_x_signals.STATE_PATH, Path('/tmp/test-state/x_signal_scanner_state.json'))
            self.assertEqual(fetch_x_signals.ROSTER_CACHE_PATH, Path('/tmp/test-state/x_signal_roster_cache.json'))
            self.assertEqual(calconviction_growth_metrics.DEFAULT_OUTPUT, Path('/tmp/test-state/calconviction_growth_metrics.jsonl'))
        for module in modules:
            importlib.reload(module)


if __name__ == '__main__':
    unittest.main()
