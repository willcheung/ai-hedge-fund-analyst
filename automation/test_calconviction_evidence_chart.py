import json
import tempfile
import unittest
from pathlib import Path

import calconviction_evidence_chart as chart


class EvidenceChartTests(unittest.TestCase):
    def valid_payload(self):
        return {
            "ticker": "TEST",
            "title": "Revenue is finally becoming real",
            "subtitle": "Quarterly revenue, USD millions",
            "periods": ["Q1", "Q2", "Q3", "Q4"],
            "values": [12.0, 18.0, 27.0, 41.0],
            "source": "Company filings",
            "as_of": "2026-08-28",
            "highlight_index": 3,
        }

    def test_validate_accepts_compact_public_payload(self):
        clean = chart.validate_payload(self.valid_payload())
        self.assertEqual(clean["ticker"], "TEST")
        self.assertEqual(clean["highlight_index"], 3)

    def test_validate_rejects_mismatched_series(self):
        payload = self.valid_payload()
        payload["values"] = [1, 2]
        with self.assertRaises(ValueError):
            chart.validate_payload(payload)

    def test_validate_rejects_private_language(self):
        payload = self.valid_payload()
        payload["subtitle"] = "Main taxable account value"
        with self.assertRaises(ValueError):
            chart.validate_payload(payload)

    def test_validate_rejects_too_many_points(self):
        payload = self.valid_payload()
        payload["periods"] = [str(i) for i in range(9)]
        payload["values"] = list(range(9))
        with self.assertRaises(ValueError):
            chart.validate_payload(payload)

    def test_render_writes_real_16_by_9_png(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "chart.png"
            chart.render(self.valid_payload(), output)
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 10_000)
            from PIL import Image
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1600, 900))

    def test_cli_writes_sidecar_with_source_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload_path = root / "input.json"
            output = root / "chart.png"
            payload_path.write_text(json.dumps(self.valid_payload()), encoding="utf-8")
            result = chart.main([str(payload_path), str(output)])
            self.assertEqual(result, 0)
            sidecar = json.loads(output.with_suffix(".json").read_text())
            self.assertEqual(sidecar["source"], "Company filings")
            self.assertEqual(sidecar["as_of"], "2026-08-28")


if __name__ == "__main__":
    unittest.main()
