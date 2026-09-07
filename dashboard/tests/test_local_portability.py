# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
"""Offline contract defaults and fail-closed integration checks."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_section_contract as contract
import test_public_snapshot
import test_section_contract


class LocalPortabilityTests(unittest.TestCase):
    def test_default_validator_and_schema_tests_only_access_checked_in_contracts(self):
        allowed = {contract.SNAPSHOT_SCHEMA, contract.WIKI_SNAPSHOT_SCHEMA}
        accessed = set()
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            absolute = Path(os.path.abspath(path))
            self.assertIn(absolute, allowed, f"unexpected default file read: {absolute}")
            accessed.add(absolute)
            return original_open(path, *args, **kwargs)

        with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()):
            # Guard contract file reads; leave path resolution and Python source introspection alone.
            with patch.object(Path, "open", guarded_open):
                self.assertEqual(contract.main([]), 0)
                test_section_contract.SectionContractTests.setUpClass()
                test_section_contract.SectionContractTests().test_wiki_schema_mirror_is_aligned()
                test_public_snapshot.SchemaAlignmentTests().test_dashboard_and_wiki_public_snapshot_schemas_are_identical()
        self.assertEqual(accessed, allowed)

    def run_validator(self, cwd, *args, mirror_env=None):
        env = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}
        if mirror_env is not None:
            env["MARKETS_WIKI_SCHEMA"] = str(mirror_env)
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_section_contract.py"), *args],
            cwd=cwd, env=env, capture_output=True, text=True, check=False,
        )

    def test_default_cli_works_outside_checkout_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_validator(td)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_explicit_valid_schema_via_flag_and_environment(self):
        with tempfile.TemporaryDirectory() as td:
            mirror = Path(td) / "integration schema.json"
            mirror.write_bytes(contract.SNAPSHOT_SCHEMA.read_bytes())
            for args, env in [(("--wiki-schema", str(mirror)), None), ((), mirror)]:
                with self.subTest(args=args, env=env):
                    result = self.run_validator(td, "--integration", *args, mirror_env=env)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_mismatched_and_invalid_explicit_schemas_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mismatch = copy.deepcopy(json.loads(contract.SNAPSHOT_SCHEMA.read_text()))
            mismatch["title"] = "incompatible integration contract"
            (root / "mismatch.json").write_text(json.dumps(mismatch))
            (root / "invalid.json").write_text("not json")
            for name in ("missing.json", "mismatch.json", "invalid.json"):
                for via_env in (False, True):
                    with self.subTest(name=name, via_env=via_env):
                        mirror = root / name
                        args = () if via_env else ("--wiki-schema", str(mirror))
                        result = self.run_validator(td, *args, mirror_env=mirror if via_env else None)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn("section contract valid", result.stdout)

    def test_integration_requires_explicit_path_and_rejects_empty_override(self):
        with tempfile.TemporaryDirectory() as td:
            for args, env in [(("--integration",), None), (("--wiki-schema", ""), None), ((), "")]:
                with self.subTest(args=args, env=env):
                    result = self.run_validator(td, *args, mirror_env=env)
                    self.assertNotEqual(result.returncode, 0)

    def test_cli_path_takes_precedence_over_environment(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_validator(td, "--wiki-schema", str(contract.WIKI_SNAPSHOT_SCHEMA),
                                        mirror_env=Path(td) / "missing.json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_checked_in_mirror_fails_even_with_valid_integration_schema(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(contract, "WIKI_SNAPSHOT_SCHEMA", Path(td) / "missing.json"):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(contract.main(["--wiki-schema", str(contract.SNAPSHOT_SCHEMA)]), 1)
