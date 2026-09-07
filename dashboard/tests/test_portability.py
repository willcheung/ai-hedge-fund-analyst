# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
"""Synthetic external interface checks. Never consult a real wiki or credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures/wiki"


class PortabilityTests(unittest.TestCase):
    def run_script(self, root, script, *args, wiki=None):
        env = {"PATH": os.environ["PATH"], "HOME": str(root / "home"),
               "MARKETWIKI_WIKI_ROOT": str(wiki or root / "wiki"),
               "MARKETWIKI_CRON_ROOT": str(root / "cron"),
               "MARKETWIKI_CACHE_ROOT": str(root / "cache"),
               "MARKETWIKI_STATE_ROOT": str(root / "state"),
               "MARKETWIKI_ENV_FILE": str(root / "no-credentials")}
        return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args],
                              env=env, capture_output=True, text=True, timeout=30)

    def test_synthetic_wiki_interface_at_two_paths(self):
        for name in ("wiki", "wiki with spaces"):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                wiki = root / name
                shutil.copytree(FIXTURE, wiki)
                (root / "cron").mkdir()
                result = self.run_script(root, "validate_section_contract.py", "--integration", "--wiki-schema", str(wiki / "schemas/public_market_snapshot_v1.schema.json"), wiki=wiki)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                out = root / "output.json"
                result = self.run_script(root, "generate_wiki_data.py", "--output", str(out), "--wiki-root", str(wiki), "--cron-root", str(root / "cron"), "--offline", wiki=wiki)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                body = json.loads(out.read_text())
                self.assertEqual(body["tickers"], [])
                self.assertFalse((root / "cache/tradingview-symbols.json").exists())
                self.assertNotEqual(body["sourceHealth"]["status"], "pass")

    def test_missing_explicit_wiki_fails_without_output_or_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "output.json"
            result = self.run_script(root, "generate_wiki_data.py", "--output", str(out), "--wiki-root", str(root / "wiki"), "--cron-root", str(root / "cron"), "--offline")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no fallback attempted", result.stderr)
            self.assertFalse(out.exists())
            result = self.run_script(root, "validate_section_contract.py", "--integration", "--wiki-schema", str(root / "wiki/schemas/public_market_snapshot_v1.schema.json"))
            self.assertNotEqual(result.returncode, 0)
            # Ordinary source builds never probe optional external schemas.
            result = self.run_script(root, "validate_section_contract.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_synthetic_mirror_schema_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(FIXTURE, root / "wiki")
            schema = root / "wiki/schemas/public_market_snapshot_v1.schema.json"
            body = json.loads(schema.read_text())
            body["title"] = "SYNTHETIC contract drift"
            schema.write_text(json.dumps(body))
            result = self.run_script(root, "validate_section_contract.py", "--integration", "--wiki-schema", str(root / "wiki/schemas/public_market_snapshot_v1.schema.json"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("update both copies", result.stdout)
