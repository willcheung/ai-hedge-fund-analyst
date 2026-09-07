# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import public_snapshot as ps
import validate_section_contract as contract


class SectionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(contract.SNAPSHOT_SCHEMA.read_text(encoding="utf-8"))

    def test_checked_in_section_contract_is_aligned(self):
        self.assertEqual(contract.section_contract_errors(self.schema), [])
        contract.validate_section_contract()

    def test_missing_health_registration_has_actionable_error(self):
        schema = copy.deepcopy(self.schema)
        del schema["properties"]["sourceHealth"]["properties"]["sections"]["properties"]["tickers"]
        errors = contract.section_contract_errors(schema)
        self.assertTrue(any(
            "sourceHealth.sections properties" in error and "tickers" in error
            for error in errors
        ), errors)

    def test_policy_maps_only_reference_registered_sections(self):
        registered = set(ps.PUBLIC_SECTIONS)
        self.assertLessEqual(set(ps.CRITICAL_SECTIONS), registered)
        self.assertLessEqual(set(ps.SECTION_THRESHOLDS_SECONDS), registered)
        self.assertLessEqual(set(ps.SECTION_PRODUCERS), registered)

    def test_wiki_schema_mirror_is_aligned(self):
        mirror_path = Path(os.environ.get("MARKETS_WIKI_SCHEMA", str(contract.WIKI_SNAPSHOT_SCHEMA)))
        mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
        self.assertEqual(contract.mirror_schema_errors(self.schema, mirror), [])

    def test_schema_mirror_drift_is_actionable(self):
        mirror = copy.deepcopy(self.schema)
        mirror["title"] = "drifted"
        errors = contract.mirror_schema_errors(self.schema, mirror)
        self.assertTrue(any("update both copies" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
