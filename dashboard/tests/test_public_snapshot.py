# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import public_snapshot as ps


class CanonicalJsonContractTests(unittest.TestCase):
    def test_utf8_nfc_sorted_compact_trailing_lf_and_exact_hash(self):
        value = {"z": 1, "e\u0301": "cafe\u0301"}
        expected = b'{"z":1,"\xc3\xa9":"caf\xc3\xa9"}\n'
        actual = ps.canonical_json_bytes(value)
        self.assertEqual(actual, expected)
        self.assertEqual(actual[-1:], b"\n")
        self.assertFalse(actual.endswith(b"\n\n"))
        self.assertEqual(hashlib.sha256(actual).hexdigest(), "a7a070c9fee07a7cd3f095f699c7afa1a783126996df8e272a78e920d6470a07")

    def test_shuffled_object_order_produces_identical_bytes(self):
        left = {"b": {"y": 2, "x": 1}, "a": [3, 2, 1]}
        right = {"a": [3, 2, 1], "b": {"x": 1, "y": 2}}
        self.assertEqual(ps.canonical_json_bytes(left), ps.canonical_json_bytes(right))

    def test_nan_infinity_and_nfc_key_collision_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                ps.canonical_json_bytes({"value": value})
        with self.assertRaises(ValueError):
            ps.canonical_json_bytes({"é": 1, "e\u0301": 2})

    def test_manifest_only_fields_are_not_hashable_snapshot_body(self):
        for key in ("snapshotId", "builtAt", "publishedAt"):
            with self.assertRaises(ValueError):
                ps.snapshot_id({"schemaVersion": 1, key: "x"})


class ProjectionPrivacyAndHealthTests(unittest.TestCase):
    def minimal_raw(self):
        return {
            "counts": {"tickers": 2},
            "actionBuckets": {}, "topTags": [], "categoryCounts": {},
            "marketPosture": [{"title": "Breadth", "score": 4}],
            "dailyJournal": [], "cronTimeline": [],
            "intradayEquityWatchdog": None,
            "marketGraphs": [{"workflowId": "public", "privacy_class": "public"}, {"workflowId": "secret", "privacy_class": "private_local_only", "claims": [{"claim": "leak"}]}],
            "currentAsymmetricShortlist": {"status": "fresh"},
            "aiProjectionExhibits": None, "aiWarRoomCompleteData": {"rows": []},
            "sources": [],
            "tickers": [{"symbol": "AAA", "pnl": 123}, {"symbol": "BBB", "accountNumber": "x"}],
            "focusTickers": [{"symbol": "BBB"}, {"symbol": "AAA"}, {"symbol": "BBB"}],
        }

    def test_structural_projection_removes_private_fields_nodes_and_normalizes_focus_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            body = ps.build_public_snapshot(self.minimal_raw(), data_as_of="2026-08-09T00:00:00Z", cron_root=root)
        self.assertEqual(body["focusTickers"], ["BBB", "AAA"])
        self.assertNotIn("capitalAllocation", body)
        self.assertNotIn("nextDollarBoard", body)
        self.assertNotIn("pnl", body["tickers"][0])
        self.assertEqual([row["workflowId"] for row in body["marketGraphs"]], ["public"])
        text = ps.canonical_json_bytes(body).decode()
        self.assertNotIn("leak", text)
        self.assertNotIn("accountNumber", text)

    def test_absolute_paths_and_private_markers_fail_closed(self):
        raw = self.minimal_raw()
        raw["sources"] = [{"path": "/root/synthetic-wiki/private.json"}]
        with tempfile.TemporaryDirectory() as td:
            body = ps.build_public_snapshot(raw, data_as_of="2026-08-09T00:00:00Z", cron_root=Path(td))
        self.assertNotIn("/root/", ps.canonical_json_bytes(body).decode())

    def test_unknown_nested_claims_and_private_nested_objects_never_pass_through(self):
        raw = self.minimal_raw()
        raw["tickers"][0].update({
            "unknownClaims": [{"claim": "not part of the public contract"}],
            "detailSections": [
                {"title": "Public", "summary": "safe", "bullets": ["ok"], "internalMemo": "drop me"},
                {"title": "Private", "summary": "secret", "privacy_class": "private_local_only"},
            ],
        })
        with tempfile.TemporaryDirectory() as td:
            body = ps.build_public_snapshot(raw, data_as_of="2026-08-09T00:00:00Z", cron_root=Path(td))
        ticker = body["tickers"][0]
        self.assertNotIn("unknownClaims", ticker)
        self.assertEqual(ticker["detailSections"], [{"bullets": ["ok"], "summary": "safe", "title": "Public"}])
        self.assertNotIn("drop me", ps.canonical_json_bytes(body).decode())

    def test_decision_learning_projection_drops_unknown_private_fields(self):
        raw = self.minimal_raw()
        raw["currentAsymmetricShortlist"] = {
            "generatedAt": "2026-08-21T20:00:00Z",
            "rows": [],
            "actionChanges": [],
            "decisionLearning": {
                "generatedAt": "2026-08-21T20:00:00Z",
                "receiptCount": 1,
                "openExceptionCount": 0,
                "outcomeCount": 7,
                "reviewDueCount": 2,
                "candidateExceptionCount": 4,
                "policyRuleCount": 5,
                "adoptedPolicyRuleCount": 3,
                "unlinkedPolicyRuleCount": 2,
                "recentReceipts": [{
                    "id": "cdr_1", "symbol": "AAA", "decision": "STARTER",
                    "missingFields": [], "accountValue": 123,
                }],
                "openExceptions": [],
                "recentOutcomes": [{
                    "receiptId": f"cdr_{i}", "sourceReceiptId": "cdr_1", "symbol": "AAA",
                    "receiptDecision": "STARTER", "priorDecision": "WATCH", "currentDecision": "HOLD",
                    "state": "reviewed", "status": "closed", "classification": "good_process",
                    "observedAt": "2026-08-21T20:00:00Z", "returnPct": 4.2,
                    "reviewReason": "scheduled", "reason": "proof held", "supersededBy": "cdr_next",
                    "accountValue": 123,
                } for i in range(7)],
                "exceptionCandidates": [{
                    "id": f"candidate-{i}", "symbol": "AAA", "classification": "timing",
                    "question": "Should confirmation be required?", "status": "candidate",
                    "sourceReceiptId": "cdr_1", "observedAt": "2026-08-21T20:00:00Z",
                    "severity": "warning", "priorDecision": "WATCH", "currentDecision": "HOLD",
                    "nextReviewEvent": "Weekly IC", "lessonCandidate": "Wait for proof", "returnPct": -1.2,
                    "privateMemo": "drop me",
                } for i in range(4)],
                "handoffs": {
                    "canonicalState": "queries/current_asymmetric_shortlist.md",
                    "outcomes": "data/automation/decision_outcomes.json",
                    "policyRules": "queries/decision_policy_rules.md",
                    "privatePath": "hidden",
                },
            },
        }
        with tempfile.TemporaryDirectory() as td:
            body = ps.build_public_snapshot(raw, data_as_of="2026-08-21T20:00:00Z", cron_root=Path(td))
        # Owner decision receipts/returns and operational handoffs never enter public storage.
        self.assertNotIn("decisionLearning", body["currentAsymmetricShortlist"])
        self.assertNotIn("cdr_1", ps.canonical_json_bytes(body).decode())

    def test_failed_or_paused_producer_keeps_validated_last_known_good_degraded(self):
        raw = self.minimal_raw()
        raw["aiWarRoomCompleteData"] = {"rows": [{"symbol": "AAA"}], "generatedAt": "2026-08-08T23:00:00Z"}
        with tempfile.TemporaryDirectory() as td:
            cron = Path(td)
            (cron / "jobs.json").write_text(json.dumps({"jobs": [{"id": "synthetic-job-06", "lastStatus": "paused", "lastSuccessAt": "2026-08-08T22:00:00Z"}]}))
            body = ps.build_public_snapshot(raw, data_as_of="2026-08-09T00:00:00Z", cron_root=cron)
        health = body["sourceHealth"]["sections"]["aiWarRoomCompleteData"]
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["producer"]["latestStatus"], "paused")
        self.assertTrue(health["usableLastKnownGood"])

    def test_snake_case_cron_state_is_reflected_in_source_health(self):
        raw = self.minimal_raw()
        raw["aiProjectionExhibits"] = {"rows": [{"symbol": "AAA"}], "generatedAt": "2026-08-08T23:00:00Z"}
        with tempfile.TemporaryDirectory() as td:
            cron = Path(td)
            (cron / "jobs.json").write_text(json.dumps({"jobs": [{
                "id": "synthetic-job-0b", "state": "scheduled", "last_status": "ok",
                "last_run_at": "2026-08-08T23:05:00Z",
            }]}))
            body = ps.build_public_snapshot(raw, data_as_of="2026-08-09T00:00:00Z", cron_root=cron)
        health = body["sourceHealth"]["sections"]["aiProjectionExhibits"]
        self.assertEqual(health["producer"]["latestStatus"], "ok")
        self.assertEqual(health["producer"]["lastSuccessAt"], "2026-08-08T23:05:00Z")
        self.assertEqual(health["status"], "pass")

    def test_missing_critical_section_drives_global_fail(self):
        raw = self.minimal_raw()
        raw["marketPosture"] = []
        with tempfile.TemporaryDirectory() as td:
            body = ps.build_public_snapshot(raw, data_as_of="2026-08-09T00:00:00Z", cron_root=Path(td))
        self.assertEqual(body["sourceHealth"]["status"], "fail")
        self.assertIn("marketPosture", body["sourceHealth"]["missingSections"])


    def test_market_session_carry_handles_weekend_holiday_and_open_boundary(self):
        sections = {name: {"present": True} for name in ps.PUBLIC_SECTIONS}
        sections["currentAsymmetricShortlist"] = {"generatedAt": "2026-08-14T23:00:00Z", "rows": [1]}
        with tempfile.TemporaryDirectory() as td:
            weekend = ps.build_source_health(
                sections, data_as_of="2026-08-16T18:00:00Z", cron_root=Path(td)
            )
        self.assertEqual(weekend["sections"]["currentAsymmetricShortlist"]["status"], "pass")

        sections["currentAsymmetricShortlist"] = {"generatedAt": "2026-05-22T20:00:00Z", "rows": [1]}
        with tempfile.TemporaryDirectory() as td:
            pre_open = ps.build_source_health(
                sections, data_as_of="2026-05-26T13:00:00Z", cron_root=Path(td)
            )
            post_open = ps.build_source_health(
                sections, data_as_of="2026-05-26T14:00:00Z", cron_root=Path(td)
            )
        self.assertEqual(pre_open["sections"]["currentAsymmetricShortlist"]["status"], "pass")
        self.assertEqual(post_open["sections"]["currentAsymmetricShortlist"]["status"], "degraded")

    def test_future_section_timestamp_fails_closed(self):
        sections = {name: {"present": True} for name in ps.PUBLIC_SECTIONS}
        sections["currentAsymmetricShortlist"] = {"generatedAt": "2026-08-17T13:30:00Z", "rows": [1]}
        with tempfile.TemporaryDirectory() as td:
            health = ps.build_source_health(
                sections, data_as_of="2026-08-17T13:00:00Z", cron_root=Path(td)
            )
        self.assertEqual(health["sections"]["currentAsymmetricShortlist"]["status"], "degraded")
        self.assertIn("currentAsymmetricShortlist", health["staleSections"])


class StableInventoryAndAtomicWriteTests(unittest.TestCase):
    def test_represented_data_as_of_ignores_unrelated_inventory_churn(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            represented = root / "tickers" / "AAA.md"
            unrelated = root / "private" / "churn.json"
            represented.parent.mkdir()
            unrelated.parent.mkdir()
            represented.write_text("represented")
            unrelated.write_text("old")
            raw = {"tickers": [{"symbol": "AAA", "sourcePath": "tickers/AAA.md", "updated": "2026-08-08"}]}
            first = ps.represented_data_as_of(raw, ps.input_inventory([root]), trusted_roots=[root])
            unrelated.write_text("new unrelated contents")
            second = ps.represented_data_as_of(raw, ps.input_inventory([root]), trusted_roots=[root])
            self.assertEqual(first, second)

    def test_section_health_does_not_inherit_global_freshness(self):
        raw = ProjectionPrivacyAndHealthTests().minimal_raw()
        with tempfile.TemporaryDirectory() as td:
            body = ps.build_public_snapshot(raw, data_as_of="2026-08-09T00:00:00Z", cron_root=Path(td))
        self.assertIsNone(body["sourceHealth"]["sections"]["marketPosture"]["dataAsOf"])

    def test_one_mixed_generation_retries_then_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.json"
            source.write_text('{"v":1}')
            calls = 0
            def builder():
                nonlocal calls
                calls += 1
                if calls == 1:
                    source.write_text('{"v":2}')
                return {"v": json.loads(source.read_text())["v"]}
            raw, _ = ps.stable_build(builder, [root])
            self.assertEqual(calls, 2)
            self.assertEqual(raw, {"v": 2})

    def test_second_mixed_generation_fails_and_prior_output_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.json"
            output = root / "output.bin"
            source.write_text('{"v":0}')
            output.write_bytes(b"prior\n")
            calls = 0
            def builder():
                nonlocal calls
                calls += 1
                source.write_text(json.dumps({"v": calls}))
                return {"v": calls}
            with self.assertRaises(ps.MixedGenerationError):
                ps.stable_build(builder, [root], attempts=2)
            self.assertEqual(output.read_bytes(), b"prior\n")

    def test_atomic_write_is_write_if_changed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshot.json"
            self.assertTrue(ps.atomic_write_bytes(path, b"{}\n"))
            first_mtime = path.stat().st_mtime_ns
            self.assertFalse(ps.atomic_write_bytes(path, b"{}\n"))
            self.assertEqual(path.stat().st_mtime_ns, first_mtime)

    def test_public_asset_scan_all_text_and_hard_denied_filename(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.js").write_text('const p = "/root/synthetic-wiki";')
            (root / "strategy-data.json").write_text("{}")
            errors = ps.scan_public_assets([root])
            self.assertTrue(any("denied public filename" in error for error in errors))
            self.assertTrue(any("forbidden marker" in error for error in errors))


class SchemaAlignmentTests(unittest.TestCase):
    def test_both_schemas_require_valid_publications_and_accept_projector_output(self):
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry, Resource
        from public_content import SCHEMA
        from test_publications import example

        registry = Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
        with tempfile.TemporaryDirectory() as td:
            empty = ps.build_public_snapshot({}, data_as_of="2026-09-04T14:00:00Z", cron_root=Path(td))
            populated = ps.build_public_snapshot(
                {"publications": [example()]}, data_as_of="2026-09-04T14:00:00Z", cron_root=Path(td),
            )
        self.assertEqual(empty["publications"], [])
        self.assertEqual(len(populated["publications"]), 1)
        ps.validate_public_snapshot_schema(populated)
        for name in ("public-snapshot-v1.schema.json", "staged-wiki-public-snapshot-v1.schema.json"):
            schema = json.loads((SCRIPTS.parent / "schema" / name).read_text())
            validator = Draft202012Validator(schema, format_checker=FormatChecker(), registry=registry)
            with self.subTest(schema=name):
                validator.validate(empty)
                validator.validate(populated)
                precontract = {key: value for key, value in empty.items() if key != "publications"}
                self.assertFalse(validator.is_valid(precontract))
                for malformed in (None, {}, "invalid", [None], [{}], [{**example(), "publishedAt": 42}]):
                    with self.subTest(publications=malformed):
                        self.assertFalse(validator.is_valid({**empty, "publications": malformed}))
                for field in SCHEMA["required"]:
                    row = {key: value for key, value in example().items() if key != field}
                    with self.subTest(missing_publication_field=field):
                        self.assertFalse(validator.is_valid({**empty, "publications": [row]}))

    def test_dashboard_and_wiki_public_snapshot_schemas_are_identical(self):
        dashboard = Path(__file__).resolve().parents[1] / "schema" / "public-snapshot-v1.schema.json"
        wiki = Path(os.environ.get("MARKETS_WIKI_SCHEMA", str(dashboard.with_name("staged-wiki-public-snapshot-v1.schema.json"))))
        self.assertEqual(json.loads(dashboard.read_text()), json.loads(wiki.read_text()))

    def test_schema_rejects_unknown_nested_ticker_and_graph_node_fields(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "schema" / "public-snapshot-v1.schema.json").read_text())
        self.assertFalse(schema["properties"]["tickers"]["items"].get("additionalProperties", True))
        graph_node = schema["$defs"]["graphNode"]
        self.assertFalse(graph_node.get("additionalProperties", True))

    def test_shortlist_actionability_fields_are_strict_and_consistent(self):
        from jsonschema import Draft202012Validator

        schema = json.loads((Path(__file__).resolve().parents[1] / "schema" / "public-snapshot-v1.schema.json").read_text())
        row_schema = schema["properties"]["currentAsymmetricShortlist"]["properties"]["rows"]["items"]
        validator = Draft202012Validator(row_schema)
        valid = {
            "symbol": "TEST",
            "bucket": "Buy / Scout Now",
            "capitalEligible": True,
            "entryEligible": True,
            "entryStatus": "inside_zone",
        }
        self.assertEqual(list(validator.iter_errors(valid)), [])
        malformed = {**valid, "capitalEligible": "false", "entryEligible": 1, "entryStatus": True}
        self.assertTrue(list(validator.iter_errors(malformed)))
        contradiction = {**valid, "entryEligible": False, "entryStatus": "above_zone"}
        self.assertTrue(list(validator.iter_errors(contradiction)))


if __name__ == "__main__":
    unittest.main()
