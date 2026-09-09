# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
"""Offline synthetic staging contracts; no live inputs or credentials required."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import public_snapshot as ps
import stage_demo as demo
import validate_demo_privacy as privacy
import shutil
from jsonschema import Draft202012Validator, FormatChecker


class StageDemoTests(unittest.TestCase):
    def test_both_scenarios_validate_and_are_deterministic(self):
        for scenario in demo.SCENARIOS:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as td:
                roots = [Path(td) / "one", Path(td) / "two"]
                results = [demo.stage_demo(root, scenario=scenario) for root in roots]
                self.assertEqual(results[0], results[1])
                files = sorted(p.relative_to(roots[0]) for p in roots[0].rglob("*") if p.is_file())
                self.assertEqual(len(files), 3)
                for rel in files:
                    self.assertEqual((roots[0] / rel).read_bytes(), (roots[1] / rel).read_bytes())
                manifest = results[0]
                snapshot = roots[0] / "market-data" / "snapshots" / (manifest["objectSha256"] + ".json")
                payload = snapshot.read_bytes()
                body = json.loads(payload)
                self.assertEqual(payload, (roots[0] / "wiki-data.json").read_bytes())
                self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest["objectSha256"])
                self.assertEqual(len(payload), manifest["byteLength"])
                self.assertEqual(ps.snapshot_id(body), manifest["snapshotId"])
                ps.validate_public_snapshot_schema(body)
                schema = json.loads((SCRIPTS.parent / "schema/demo-manifest-v1.schema.json").read_text())
                Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)
                self.assertEqual(ps.scan_public_assets([roots[0]]), [])
                self.assertIn("SYNTHETIC", body["privacy"]["note"])
                self.assertEqual(manifest["sourceHealth"], body["sourceHealth"])

    def test_client_origin_and_local_route_contract(self):
        body, manifest = demo.build_demo()
        self.assertEqual(manifest["snapshotUrl"], f"./market-data/snapshots/{manifest['objectSha256']}.json")
        self.assertNotIn("https://", manifest["snapshotUrl"])
        self.assertEqual(body["refreshMode"], "runtime-manifest")
        self.assertEqual({p["type"] for p in body["publications"]}, {"brief", "company", "theme"})

    def test_degraded_is_not_fake_research(self):
        body, _ = demo.build_demo("degraded")
        self.assertEqual(body["sourceHealth"]["status"], "degraded")
        self.assertIn("tickers", body["sourceHealth"]["staleSections"])
        self.assertIn("intradayEquityWatchdog", body["sourceHealth"]["missingSections"])
        self.assertEqual(body["counts"]["researched"], 0)
        self.assertEqual(body["macroRegimeMeter"]["score"], 5.5)
        self.assertEqual(body["macroRegimeMeter"]["generatedAt"], demo.AS_OF)
        self.assertTrue(all(source["path"].startswith("synthetic/") for source in body["macroRegimeMeter"]["sourceHealth"]["sources"]))
        self.assertTrue(all(t["isStub"] for t in body["tickers"]))
        self.assertEqual(body["focusTickers"], [])
        self.assertNotIn("automation", body["currentAsymmetricShortlist"])
        self.assertFalse(demo.demo_raw("degraded")["currentAsymmetricShortlist"]["automation"]["enabled"])
        for row in body["aiProjectionExhibits"]["rows"]:
            self.assertIsNone(row["price"])
            self.assertFalse(row.get("capitalEligibleFromProjection", False))
            self.assertEqual(row["dataQualityLabel"], "Assessment unavailable")
            self.assertTrue(row["missingCriticalFields"])
        self.assertTrue(body["dailyJournal"])
        self.assertIn("SYNTHETIC", body["cronTimeline"][0]["summary"])
        self.assertNotIn("schedule", body["cronTimeline"][0])
        self.assertEqual(demo.demo_raw("degraded")["cronTimeline"][0]["schedule"], "disabled")
        self.assertTrue(body["marketGraphs"])
        self.assertTrue(body["sources"])

    def test_missing_preserves_empty_and_null_sections(self):
        body, _ = demo.build_demo("missing")
        self.assertEqual(body["sourceHealth"]["status"], "fail")
        for key in ("tickers", "dailyJournal", "marketPosture", "marketGraphs"):
            self.assertEqual(body[key], [])
        for key in ("currentAsymmetricShortlist", "aiProjectionExhibits", "aiWarRoomCompleteData", "intradayEquityWatchdog"):
            self.assertIsNone(body[key])
        self.assertEqual(body["counts"]["tickers"], 0)
        self.assertIsNone(body["macroRegimeMeter"]["score"])

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sentinel = root / "wiki-data.json"
            sentinel.write_text("existing staging data")
            with self.assertRaises(FileExistsError):
                demo.stage_demo(root)
            self.assertEqual(sentinel.read_text(), "existing staging data")
            self.assertFalse((root / "market-data").exists())

    def test_symlink_ancestor_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "actual").mkdir()
            (root / "link").symlink_to(root / "actual", target_is_directory=True)
            with self.assertRaises(ValueError):
                demo.stage_demo(root / "link" / "output")
            self.assertEqual(list((root / "actual").iterdir()), [])

    def test_validation_failure_writes_nothing(self):
        for invalid in ("invalid", [], None, True, -1, 1.5, 9007199254740992):
            with tempfile.TemporaryDirectory() as td:
                raw = demo.demo_raw("degraded")
                raw["counts"]["tickers"] = invalid
                with patch.object(demo, "demo_raw", return_value=raw):
                    with self.assertRaises(ValueError):
                        demo.stage_demo(Path(td) / "output")
                self.assertFalse((Path(td) / "output").exists())

    def test_dataset_root_and_dangling_symlinks_are_rejected(self):
        for relative in ("wiki-data.json", "market-data"):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root / relative).symlink_to(root / "absent")
                with self.assertRaises(ValueError): demo.stage_demo(root, refresh=True)
                self.assertFalse((root / "absent").exists())

    def test_final_asset_privacy_failure_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "output"
            with patch.object(ps, "scan_public_assets", return_value=["synthetic privacy rejection"]):
                with self.assertRaises(ps.PrivacyError): demo.stage_demo(output)
            self.assertFalse(output.exists())

    def test_refresh_reuses_identical_data_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = demo.stage_demo(root)
            self.assertEqual(demo.stage_demo(root, refresh=True), first)
            target = root / "wiki-data.json"
            target.write_text("different data")
            with self.assertRaises(FileExistsError):
                demo.stage_demo(root, refresh=True)
            self.assertEqual(target.read_text(), "different data")

    def test_refresh_refuses_extra_snapshot_or_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            demo.stage_demo(root)
            extra = root / "market-data/extra.json"
            extra.write_text("{}")
            with self.assertRaises(FileExistsError): demo.stage_demo(root, refresh=True)
            extra.unlink()
            extra.symlink_to(root / "wiki-data.json")
            with self.assertRaises(FileExistsError): demo.stage_demo(root, refresh=True)

    def test_unknown_scenario_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                demo.stage_demo(Path(td) / "output", scenario="live")
            self.assertFalse((Path(td) / "output").exists())


class AnalyticsPrivacyValidationTests(unittest.TestCase):
    def test_guarded_capability_passes_and_missing_gates_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'src').mkdir()
            for name in ('main.tsx', 'analytics.ts', 'useMarketData.ts'):
                shutil.copyfile(SCRIPTS.parent / 'src' / name, root / 'src' / name)
            self.assertEqual(privacy.analytics_source_errors(root), [])
            main = root / 'src/main.tsx'
            original = main.read_text()
            for gate in ('import.meta.env.PROD && ',
                         "import.meta.env.VITE_ENABLE_ANALYTICS === 'true' && ",
                         '!isStagedPreviewBuild && ', ' beforeSend={sanitizeAnalyticsEvent}'):
                main.write_text(original.replace(gate, ''))
                self.assertTrue(privacy.analytics_source_errors(root), gate)
            main.write_text(original)
            mode = root / 'src/useMarketData.ts'
            original_mode = mode.read_text()
            mode.write_text(original_mode.replace("!== 'production'", "=== 'bundled'"))
            self.assertTrue(privacy.analytics_source_errors(root))
            mode.write_text(original_mode)
            for added in ("import { inject } from '@vercel/analytics'", '<Analytics />',
                          "fetch('/_vercel/insights/view')"):
                (root / 'src/extra.tsx').write_text(added)
                self.assertTrue(privacy.analytics_source_errors(root), added)

    def test_demo_artifacts_reject_analytics_in_javascript_and_html(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            demo.stage_demo(root / 'public')
            shutil.copytree(root / 'public', root / 'dist')
            html = root / 'dist/index.html'
            clean_html = "<meta content=\"connect-src 'self'; frame-src 'none'\">"
            html.write_text(clean_html)
            self.assertEqual(privacy.artifact_errors(root), [])
            for transport in ('/_vercel/insights/script.js', '/_vercel/speed-insights/script.js',
                              'https://va.vercel-scripts.com/v1/script.js'):
                for suffix in ('js', 'html'):
                    path = root / 'dist' / ('injected.' + suffix)
                    path.write_text('<script src="' + transport + '"></script>')
                    self.assertIn('dist/' + path.name + ': analytics transport', privacy.artifact_errors(root))
                    path.unlink()


if __name__ == "__main__":
    unittest.main()
