from pathlib import Path
import tempfile
import unittest
import check_source as checks

class SourceBoundaryTests(unittest.TestCase):
    def test_safe_source_and_explicit_env_template(self):
        self.assertIsNone(checks.path_violation('dashboard/scripts/generate.py'))
        self.assertIsNone(checks.path_violation('dashboard/schema/public-snapshot.json'))

    def test_removed_top_level_source_trees_fail(self):
        for path in ['automation/collector.py', 'deploy/jobs/definitions.json',
                     'trading-execution/src/router.py']:
            with self.subTest(path=path):
                self.assertEqual(checks.path_violation(path), 'non_dashboard_public_source')

    def test_private_and_generated_paths_fail(self):
        for path in ['.env', 'dashboard/public/wiki-data.json', 'x/state/results.json',
                     '.hermes/auth.json', 'foo/node_modules/index.js', 'wiki-market/index.md']:
            with self.subTest(path=path):
                self.assertIsNotNone(checks.path_violation(path))

    def test_syntax_and_symlink_are_checked_without_import(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            (root/'safe.py').write_text('raise RuntimeError("must not import")\n')
            self.assertEqual(checks.inspect_files(root,['safe.py']),[])
            (root/'bad.py').write_text('def broken(\n')
            self.assertTrue(checks.inspect_files(root,['bad.py']))
            (root/'link.py').symlink_to(root/'safe.py')
            self.assertTrue(checks.inspect_files(root,['link.py']))

class InventoryTests(unittest.TestCase):
    def test_enumeration_needs_no_git_and_does_not_hide_credentials(self):
        from privacy_scan import source_names
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('synthetic')
            (root / 'test.py').write_text('pass')
            (root / '.venv').mkdir()
            (root / '.venv/package.py').write_text('pass')
            (root / 'link').symlink_to(root / '.venv', target_is_directory=True)
            self.assertEqual(source_names(root), ['.env', 'link', 'test.py'])

    def test_manifest_detects_extra_missing_and_duplicate_entries(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for files in [[], ['other.py'], ['a.py', 'a.py']]:
                (root / 'SOURCE-MANIFEST.json').write_text(json.dumps({'format_version': 2, 'files': files}))
                self.assertTrue(checks.inspect_manifest(root, ['a.py']))
            (root / 'SOURCE-MANIFEST.json').write_text(json.dumps({'format_version': 2, 'files': ['a.py']}))
            self.assertEqual(checks.inspect_manifest(root, ['a.py']), [])

    def test_static_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in ['{"a": 1, "a": 2}', '{"a": NaN}', '{']:
                (root / 'sample.json').write_text(value)
                self.assertEqual(checks.inspect_files(root, ['sample.json']),
                                 [{'path': 'sample.json', 'reason': 'invalid_json'}])

if __name__=='__main__': unittest.main()
