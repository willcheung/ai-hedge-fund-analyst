# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_wiki_data.py"
spec = importlib.util.spec_from_file_location("generate_wiki_data", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TickerDecisionParsingTests(unittest.TestCase):
    def setUp(self):
        self.body = """
## What It Is
Synthetic Circuits makes fictional logic devices for test scenarios.

## Thesis
Synthetic demand and example firmware could expand the fictional product range.

## War Room — 2026-08-09
- **Action:** WATCH / tiny common-only scout on a stabilized reset; no fresh add-size at $43.21.
- **Scout / dislocation:** $31-$36 first review; $21-$26 stronger dislocation.
- **Proof-add:** Hold above $45, then $49, with Q3 example-device revenue >=$80M.
- **Thesis kill:** Q3 example-device below $70M or example merger delays.
"""

    def test_company_description_is_distinct_from_thesis(self):
        description = mod.company_description(self.body)
        thesis = mod.first_paragraph(mod.section(self.body, "Thesis"))
        self.assertEqual(
            description,
            "Synthetic Circuits makes fictional logic devices for test scenarios.",
        )
        self.assertNotEqual(description, thesis)

    def test_war_room_overrides_drive_buy_answer_and_gates(self):
        overrides = mod.war_room_overrides(self.body)
        self.assertEqual(
            overrides["shortlistRec"],
            "WATCH / tiny common-only scout on a stabilized reset; no fresh add-size at $43.21.",
        )
        self.assertIn("$31-$36", overrides["entryPoint"])
        self.assertIn("$45", overrides["trigger"])
        self.assertIn("Q3 example-device below $70M", overrides["shortlistRisk"])
        self.assertEqual(overrides["shortlistStatus"], overrides["shortlistRec"])

    def test_freshest_dated_war_room_wins_even_when_older_section_is_later(self):
        body = """
## War Room — 2026-08-09
- **Action:** HOLD / PULLBACK WATCH — no chase.
- **Scout / dislocation:** $51-$59 common-only review.
- **Proof-add:** Q2 revenue and margin proof, then $61-$69 reclaim.
- **Thesis kill:** Guide slips or loses $39 without proof.

## Research Log
Historical notes.

## War Room — 2026-07-31
- **Action:** Core hold / tactical starter only on weakness.
- **Scout / dislocation:** $41-$44 starter.
- **Proof-add:** $55-$57 reclaim.
- **Thesis kill:** Below $37-$38.
"""
        overrides = mod.war_room_overrides(body)
        self.assertEqual(overrides["shortlistRec"], "HOLD / PULLBACK WATCH — no chase.")
        self.assertIn("$51-$59", overrides["entryPoint"])
        self.assertIn("$61-$69", overrides["trigger"])
        self.assertIn("$39", overrides["shortlistRisk"])

    def test_detail_cards_reserve_a_slot_for_freshest_war_room(self):
        body = "\n".join(
            [f"## Thesis Note {i}\nPreferred detail {i}." for i in range(9)]
            + [
                "## War Room — 2026-08-16\n**Action:** HOLD / TRIM-REVIEW.",
                "## War Room — 2026-08-09\n**Action:** Old decision.",
            ]
        )
        details = mod.ticker_detail_sections(
            mod.heading_sections(body), ["Thesis", "War Room"], limit=8
        )
        war_rooms = [row["title"] for row in details if row["title"].startswith("War Room")]
        self.assertEqual(war_rooms, ["War Room — 2026-08-16"])
        self.assertEqual(details[0]["title"], "War Room — 2026-08-16")
        self.assertEqual(len(details), 8)

    def test_prefixed_older_war_room_is_omitted(self):
        body = """
## SYNTHK War Room Refresh — 2026-08-09
**Action:** Old decision.

## War Room — 2026-08-16
**Action:** Current decision.
"""
        details = mod.ticker_detail_sections(
            mod.heading_sections(body), ["War Room"], limit=8
        )
        self.assertEqual([row["title"] for row in details], ["War Room — 2026-08-16"])

    def test_full_summary_omits_superseded_portfolio_war_rooms(self):
        body = """
## War Room — 2026-08-21
**Action:** INDEPENDENT WATCH / WAIT FOR ROIC PROOF.

## War Room — 2026-08-16
**Action:** HOLD / tax-aware trim-review / 0% incremental.

## Forward Signal / Post-Event Verdict — 2026-05-13
**Action:** If owned, hold core exposure and size around the existing position.
"""
        details = mod.ticker_detail_sections(
            mod.heading_sections(body), ["War Room", "Forward Signal"], limit=8
        )
        summary = mod.ticker_full_summary(body, details)
        self.assertIn("INDEPENDENT WATCH", summary)
        self.assertNotIn("tax-aware", summary)
        self.assertNotIn("0% incremental", summary)
        self.assertNotIn("If owned", summary)
        self.assertFalse(any("Forward Signal" in row["title"] for row in details))


class DecisionLearningParsingTests(unittest.TestCase):
    def test_shortlist_parser_projects_membership_run_and_live_automation_graph(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wiki = root / "wiki"
            cron = root / "cron"
            data_dir = wiki / "data/automation"
            data_dir.mkdir(parents=True)
            cron.mkdir()
            (data_dir / "current_asymmetric_shortlist_latest.json").write_text(json.dumps({
                "generatedAt": "2026-09-03T18:10:00Z",
                "all": [],
                "actionChanges": [],
                "summary": {"rowCount": 23, "researchSnapshots": 23},
                "regime": {},
                "membershipPolicy": {
                    "bucketMode": "mutually_exclusive",
                    "description": "One bucket per ticker.",
                    "bucketOrder": ["Buy / Scout Now", "Wait for Trigger"],
                },
                "runSummary": {
                    "builder": "current_shortlist_builder",
                    "scheduledOwner": "Market Wiki Freshness Gate",
                    "generatedAt": "2026-09-03T18:10:00Z",
                    "previousGeneratedAt": "2026-09-03T17:55:00Z",
                    "status": "changed",
                    "rowCount": 23,
                    "addedSymbols": ["NEW"],
                    "removedSymbols": ["OLD"],
                    "changedCount": 3,
                    "unchangedCount": 21,
                },
                "membershipChanges": [{
                    "symbol": "TEST", "changeType": "bucket_changed", "fromBucket": "Wait for Trigger",
                    "toBucket": "Buy / Scout Now", "fromAction": "Wait", "toAction": "Scout",
                    "fromFreshness": "fresh", "toFreshness": "fresh", "changedFields": ["bucket", "action"],
                }],
            }), encoding="utf-8")
            (cron / "jobs.json").write_text(json.dumps({"jobs": [{
                "id": "synthetic-job-04", "name": "Market Wiki Freshness Gate", "enabled": True,
                "schedule": {"display": "15 13 * * 1-5"}, "last_status": "ok",
                "last_run_at": "2026-09-03T18:10:11Z", "next_run_at": "2026-09-04T13:15:00Z",
            }, {
                "id": "synthetic-job-0f", "name": "X Signal Scanner — singleton cost-capped", "enabled": True,
                "schedule": {"display": "0 13 * * 1,3,5"}, "last_status": "ok",
                "last_run_at": "2026-09-02T13:15:00Z", "next_run_at": "2026-09-04T13:00:00Z",
            }]}), encoding="utf-8")
            old_wiki, old_cron = mod.WIKI, mod.CRON_ROOT
            try:
                mod.WIKI, mod.CRON_ROOT = wiki, cron
                parsed = mod.parse_current_asymmetric_shortlist()
            finally:
                mod.WIKI, mod.CRON_ROOT = old_wiki, old_cron

        self.assertEqual(parsed["membershipPolicy"]["bucketMode"], "mutually_exclusive")
        self.assertEqual(parsed["runSummary"]["addedSymbols"], ["NEW"])
        self.assertEqual(parsed["membershipChanges"][0]["changedFields"], ["bucket", "action"])
        self.assertEqual(parsed["automation"]["lastStatus"], "ok")
        self.assertEqual(parsed["automation"]["nextRunAt"], "2026-09-04T13:15:00Z")
        job_names = {node["label"] for node in parsed["membershipWorkflow"]["nodes"] if node["kind"] == "job"}
        self.assertIn("X Signal Scanner", job_names)
        self.assertIn("Market Wiki Freshness Gate", job_names)
        nodes = {node["id"]: node for node in parsed["membershipWorkflow"]["nodes"]}
        self.assertIn("membership_policy_write", nodes)
        self.assertIn("No job auto-promotes", nodes["membership_policy_write"]["detail"])
        self.assertTrue(any(edge["from"] == "research_snapshots" and edge["to"] == "membership_policy_write" for edge in parsed["membershipWorkflow"]["edges"]))
        self.assertTrue(any(edge["from"] == "membership_policy_write" and edge["to"] == "membership_gate" for edge in parsed["membershipWorkflow"]["edges"]))

    def test_publisher_node_ignores_its_own_volatile_cron_timestamps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cron = root / "cron"
            state_dir = root / "state"
            cron.mkdir()
            state_dir.mkdir()
            jobs_path = cron / "jobs.json"
            publisher = {
                "id": "synthetic-job-10",
                "name": "MarketWiki independent data publisher (failure-only)",
                "enabled": True,
                "schedule": {"display": "every 5m"},
                "last_status": "error",
                "last_run_at": "2026-09-03T23:58:12Z",
                "next_run_at": "2026-09-04T00:03:12Z",
            }
            jobs_path.write_text(json.dumps({"jobs": [publisher]}), encoding="utf-8")
            (state_dir / "market_dashboard_data_publish_state.json").write_text(json.dumps({
                "consecutiveFailures": 0,
                "lastError": None,
                "lastBuiltAt": "2026-09-03T23:58:52Z",
                "lastSuccessAt": "2026-09-03T23:59:35Z",
            }), encoding="utf-8")
            old_cron = mod.CRON_ROOT
            try:
                mod.CRON_ROOT = cron
                first = mod.build_shortlist_membership_workflow({"summary": {}})
                publisher["last_status"] = "ok"
                publisher["last_run_at"] = "2026-09-04T00:03:13Z"
                publisher["next_run_at"] = "2026-09-04T00:08:13Z"
                jobs_path.write_text(json.dumps({"jobs": [publisher]}), encoding="utf-8")
                second = mod.build_shortlist_membership_workflow({"summary": {}})
            finally:
                mod.CRON_ROOT = old_cron

        first_node = next(node for node in first["nodes"] if node["id"] == "blob_publisher")
        second_node = next(node for node in second["nodes"] if node["id"] == "blob_publisher")
        self.assertEqual(first_node, second_node)
        self.assertEqual(first_node["status"], "pass")
        self.assertEqual(first_node["lastRunAt"], "")
        self.assertEqual(first_node["nextRunAt"], "")

    def test_shortlist_parser_projects_completed_feedback_loop_with_bounded_public_rows(self):
        with tempfile.TemporaryDirectory() as td:
            wiki = Path(td)
            data_dir = wiki / "data/automation"
            data_dir.mkdir(parents=True)
            (data_dir / "current_asymmetric_shortlist_latest.json").write_text(json.dumps({
                "generatedAt": "2026-08-21T20:00:00Z",
                "all": [],
                "actionChanges": [],
                "summary": {},
                "regime": {},
            }))
            (data_dir / "decision_learning_latest.json").write_text(json.dumps({
                "schemaVersion": 1,
                "generatedAt": "2026-08-21T20:01:00Z",
                "policy": "Canonical current state first.",
                "receiptCount": 4,
                "newReceiptCount": 1,
                "integrityGapCount": 0,
                "openExceptionCount": 4,
                "outcomeCount": 8,
                "reviewDueCount": 2,
                "candidateExceptionCount": 5,
                "policyRuleCount": 4,
                "adoptedPolicyRuleCount": 3,
                "unlinkedPolicyRuleCount": 1,
                "casebookCount": 5,
                "casebookPolicy": "Curated only.",
                "recentReceipts": [{
                    "id": "cdr_1", "recordedAt": "2026-08-21T20:00:00Z", "symbol": "AAA",
                    "decision": "STARTER", "decisionState": "TRIGGER_READY", "researchTier": "speculative",
                    "thesis": "Portfolio mover", "entry": "$10-$11", "proofTrigger": "customer proof",
                    "killTrigger": "below $8", "maxSize": "tiny", "decisionExpiration": "2026-08-28",
                    "decisionQuote": 10.42, "quoteAsOf": "2026-08-21T19:50:00Z", "fundingRule": "factor rebalance",
                    "completeness": "complete", "missingFields": [], "recordReason": "capital_decision_snapshot",
                    "privateAccountValue": 123,
                }],
                "openExceptions": [
                    {"id": f"ex-{i}", "symbol": f"T{i}", "classification": "bad_timing", "question": f"Q{i}", "status": "open", "sourceReceiptId": "cdr_1"}
                    for i in range(4)
                ],
                "recentOutcomes": [
                    {
                        "receiptId": f"cdr_{i}", "sourceReceiptId": "cdr_1", "symbol": f"O{i}",
                        "receiptDecision": "STARTER", "priorDecision": "WATCH", "currentDecision": "HOLD",
                        "state": "reviewed", "status": "closed", "classification": "good_process",
                        "observedAt": "2026-08-21T20:00:00Z", "returnPct": i + 0.5,
                        "reviewReason": "scheduled review", "reason": "proof held", "supersededBy": "cdr_next",
                        "privateAccountValue": 999,
                    }
                    for i in range(8)
                ],
                "exceptionCandidates": [
                    {
                        "id": f"candidate-{i}", "symbol": f"C{i}", "classification": "timing",
                        "question": f"Review candidate {i}?", "status": "candidate", "sourceReceiptId": "cdr_1",
                        "observedAt": "2026-08-21T20:00:00Z", "severity": "warning",
                        "priorDecision": "WATCH", "currentDecision": "HOLD", "nextReviewEvent": "Weekly IC",
                        "lessonCandidate": "Wait for confirmation", "returnPct": -2.5, "internalNotes": "drop me",
                    }
                    for i in range(5)
                ] + [{"id": "not-candidate", "status": "open", "question": "Do not mix with candidates"}],
                "handoffs": {
                    "canonicalState": "queries/current_asymmetric_shortlist.md",
                    "outcomes": "data/automation/decision_outcomes.json",
                    "policyRules": "queries/decision_policy_rules.md",
                    "privatePath": "/root/private",
                },
            }))
            with patch.multiple(mod, WIKI=wiki, CRON_ROOT=wiki / "cron"):
                parsed = mod.parse_current_asymmetric_shortlist()
        learning = parsed["decisionLearning"]
        self.assertEqual(learning["receiptCount"], 4)
        self.assertEqual(len(learning["openExceptions"]), 3)
        self.assertEqual(learning["outcomeCount"], 8)
        self.assertEqual(learning["reviewDueCount"], 2)
        self.assertEqual(learning["candidateExceptionCount"], 5)
        self.assertEqual(learning["policyRuleCount"], 4)
        self.assertEqual(learning["adoptedPolicyRuleCount"], 3)
        self.assertEqual(learning["unlinkedPolicyRuleCount"], 1)
        self.assertEqual(len(learning["recentOutcomes"]), 6)
        self.assertEqual(len(learning["exceptionCandidates"]), 3)
        self.assertTrue(all(row["status"] == "candidate" for row in learning["exceptionCandidates"]))
        self.assertNotIn("privateAccountValue", learning["recentOutcomes"][0])
        self.assertNotIn("internalNotes", learning["exceptionCandidates"][0])
        self.assertNotIn("privateAccountValue", learning["recentReceipts"][0])
        self.assertNotIn("fundingRule", learning["recentReceipts"][0])
        self.assertNotIn("maxSize", learning["recentReceipts"][0])
        self.assertNotIn("privatePath", learning["handoffs"])
        self.assertEqual(learning["handoffs"]["outcomes"], "data/automation/decision_outcomes.json")
        self.assertEqual(learning["handoffs"]["policyRules"], "queries/decision_policy_rules.md")


class MarketGraphPrivacyTests(unittest.TestCase):
    def test_parse_market_graphs_requires_explicit_public_node_classification(self):
        with tempfile.TemporaryDirectory() as td:
            wiki = Path(td)
            run_dir = wiki / "data/automation/graph_runs/market_research_cio_dashboard/run"
            run_dir.mkdir(parents=True)
            workflow = run_dir.parent
            (workflow / "latest.json").write_text(json.dumps({
                "checker_path": str((run_dir / "checker.json").relative_to(wiki)),
                "final_path": str((run_dir / "final.md").relative_to(wiki)),
                "final_gate": "pass",
                "run_id": "run",
                "generated_at": "2026-08-09T00:00:00Z",
            }))
            (run_dir / "final.md").write_text("## Recommendation\nPass.\n")
            (run_dir / "checker.json").write_text(json.dumps({"node_results": [
                {"node_id": "public", "privacy_class": "public_ok", "status": "pass", "allowed_into_synthesis": True},
                {"node_id": "private", "privacy_class": "private_local_only", "status": "pass", "allowed_into_synthesis": True, "reason": "secret"},
                {"node_id": "unclassified", "status": "pass", "allowed_into_synthesis": True, "reason": "must fail closed"},
            ]}))
            old_wiki = mod.WIKI
            try:
                mod.WIKI = wiki
                graph = next(g for g in mod.parse_market_graphs() if g["workflowId"] == "market_research_cio_dashboard")
            finally:
                mod.WIKI = old_wiki
        ids = {node["id"] for node in graph["graphNodes"]}
        self.assertIn("public", ids)
        self.assertNotIn("private", ids)
        self.assertNotIn("unclassified", ids)
        self.assertEqual(graph["nodeCount"], 1)
        self.assertEqual(graph["privacy_class"], "public_ok")

        # The public ops graph must represent the real post-checker delivery
        # path, not stop at synthesis: synthesis -> projected snapshot ->
        # manifest pointer -> the sole current graph-status consumer, Workflow Ops.
        self.assertTrue({
            "public_snapshot", "runtime_manifest", "workflow_ops"
        }.issubset(ids))
        edge_pairs = {(edge["from"], edge["to"]) for edge in graph["graphEdges"]}
        self.assertIn(("synthesis", "public_snapshot"), edge_pairs)
        self.assertIn(("public_snapshot", "runtime_manifest"), edge_pairs)
        self.assertEqual(
            {to for source, to in edge_pairs if source == "runtime_manifest"},
            {"workflow_ops"},
        )
        self.assertNotIn("cio_exceptions", ids)
        self.assertEqual({n["id"] for n in graph["graphNodes"] if n.get("kind") == "consumer"}, {"workflow_ops"})
        self.assertTrue(all(node.get("privacy_class") == "public_ok" for node in graph["graphNodes"]))


class MacroStateParsingTests(unittest.TestCase):
    def test_canonical_macro_snapshot_replaces_legacy_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            wiki = Path(td)
            path = wiki / "data/automation/macro_regime_snapshot_latest.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "as_of": "2026-08-22T12:00:00Z",
                "structural_regime": "broadening",
                "tactical_risk": "selective_risk_on",
                "exposure_dial": "NEW_ENTRY_ALLOWED",
                "confidence": "medium",
                "freshness_status": "pass",
                "external_sentiment": "negative_watch",
                "press_allowed": False,
                "add_size_allowed": False,
                "reason": "Observed market stays authoritative.",
                "source_paths": ["raw/briefings/macro.json"],
                "qualitativeLeadingPressure": {"evidence": [{"private": "must not project"}]},
            }), encoding="utf-8")
            old_wiki = mod.WIKI
            try:
                mod.WIKI = wiki
                state = mod.parse_macro_state()
            finally:
                mod.WIKI = old_wiki

        self.assertEqual(state["structural_regime"], "broadening")
        self.assertEqual(state["tactical_risk"], "selective_risk_on")
        self.assertFalse(state["press_allowed"])
        self.assertNotIn("qualitativeLeadingPressure", state)

    def test_canonical_macro_posture_card_is_compact_and_public_safe(self):
        with tempfile.TemporaryDirectory() as td:
            wiki = Path(td)
            path = wiki / "data/automation/macro_regime_snapshot_latest.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "asOf": "2026-08-22T12:00:00Z",
                "structuralRegime": "broadening",
                "tacticalRisk": "selective_risk_on",
                "freshness": {"status": "pass"},
                "observedMarket": {
                    "transitionScore": 58.0,
                    "breadthScore": 79.2,
                    "breadthZone": "Healthy",
                    "exposureRecommendation": "NEW_ENTRY_ALLOWED",
                },
                "qualitativeLeadingPressure": {"score": 0.09, "label": "neutral", "evidence": [{"private": "drop"}]},
                "decisionPolicy": {
                    "pressAllowed": False,
                    "addSizeAllowed": False,
                    "axisWarnings": ["liquidity_policy"],
                },
                "decisionTransmission": {"channels": [
                    {"channel": "duration_sensitive_growth", "pressure": -1.05, "actionEffect": "reduce_one_step"},
                    {"channel": "small_caps", "pressure": 1.14, "actionEffect": "improve_timing_only"},
                ]},
            }), encoding="utf-8")
            old_wiki = mod.WIKI
            try:
                mod.WIKI = wiki
                card = mod.canonical_macro_posture()
            finally:
                mod.WIKI = old_wiki

        self.assertEqual(card["name"], "Canonical regime")
        self.assertEqual(card["score"], 58.0)
        self.assertEqual(card["plainTitle"], "More stocks are working, but stay selective")
        self.assertEqual(card["plainEnglish"], "Small new positions are okay. Wait for stronger proof before adding size.")
        self.assertIn("Market participation is broad and healthy", card["watch"])
        self.assertIn("Main risk: the flow of money into markets is becoming less supportive", card["watch"])
        self.assertTrue(any("low rates or cheap funding" in row.lower() for row in card["watch"]))
        visible_copy = ' '.join([card["plainTitle"], card["plainEnglish"], *card["watch"]]).lower()
        for jargon in ("leading pressure", "liquidity policy", "duration sensitive growth", "new entry allowed", "press blocked"):
            self.assertNotIn(jargon, visible_copy)
        self.assertNotIn("evidence", json.dumps(card))


if __name__ == "__main__":
    unittest.main()
