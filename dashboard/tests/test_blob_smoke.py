# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
"""Opt-in real Vercel Blob transport smoke test.

Run explicitly (never in normal CI):
  MARKETWIKI_REAL_BLOB_SMOKE=1 MARKETWIKI_BLOB_ORIGIN=https://... \
    python3 -m unittest tests/test_blob_smoke.py -v
The token is read from BLOB_READ_WRITE_TOKEN or an explicitly configured credential file, never argv.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from urllib.parse import urlencode

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "publish_wiki_data.py"
sys.path.insert(0, str(MODULE_PATH.resolve().parent))
SPEC = importlib.util.spec_from_file_location("publish_wiki_data_smoke", MODULE_PATH)
pub = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(pub)


@unittest.skipUnless(os.environ.get("MARKETWIKI_REAL_BLOB_SMOKE") == "1", "real Blob smoke is opt-in")
class RealBlobSmokeTest(unittest.TestCase):
    def test_upload_exact_readback_conditional_manifest_and_cleanup(self):
        origin_value = os.environ.get("MARKETWIKI_BLOB_ORIGIN")
        self.assertIsNotNone(origin_value, "MARKETWIKI_BLOB_ORIGIN is required")
        origin = pub.validate_origin(origin_value or "")
        transport = pub.NodeBlobTransport()
        prefix = f"marketwiki/smoke/{uuid.uuid4().hex}"
        urls: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            body = b'{"schemaVersion":1,"probe":"publisher-smoke"}\n'
            snapshot.write_bytes(body)
            digest = hashlib.sha256(body).hexdigest()
            snapshot_path = f"{prefix}/snapshots/{digest}.json"
            snapshot_url = f"{origin}/{snapshot_path}"
            manifest_path = f"{prefix}/manifest.json"
            manifest_url = f"{origin}/{manifest_path}"
            try:
                result = transport.put(snapshot_path, snapshot, overwrite=False, if_match=None, cache_age=31536000)
                urls.append(result["url"])
                status, headers, readback = pub.http_get(f"{snapshot_url}?{urlencode({'v': digest})}")
                self.assertEqual(status, 200)
                self.assertEqual(hashlib.sha256(readback).hexdigest(), digest)
                self.assertTrue(pub.CONTENT_TYPE_RE.match(headers.get("content-type", "")))
                self.assertEqual(headers.get("access-control-allow-origin"), "*")

                first = root / "manifest-one.json"
                first.write_text('{"schemaVersion":1,"probe":"one"}\n')
                created = transport.put(manifest_path, first, overwrite=False, if_match=None, cache_age=60)
                urls.append(created["url"])
                etag = transport.head(manifest_url).get("etag")
                self.assertTrue(etag)
                second = root / "manifest-two.json"
                second.write_text('{"schemaVersion":1,"probe":"two"}\n')
                transport.put(manifest_path, second, overwrite=True, if_match=etag, cache_age=60)
                propagated = False
                for attempt in range(16):
                    status, headers, manifest_body = pub.http_get(f"{manifest_url}?v=two-{attempt}")
                    if status == 200 and json.loads(manifest_body).get("probe") == "two":
                        propagated = True
                        break
                    time.sleep(5)
                self.assertTrue(propagated, "conditional manifest overwrite did not propagate in 80s")
            finally:
                transport.delete(list(dict.fromkeys(reversed(urls))))


if __name__ == "__main__":
    unittest.main()
