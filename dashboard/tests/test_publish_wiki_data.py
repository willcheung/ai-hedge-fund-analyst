# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "publish_wiki_data.py"
sys.path.insert(0, str(MODULE_PATH.resolve().parent))
SPEC = importlib.util.spec_from_file_location("publish_wiki_data", MODULE_PATH)
pub = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(pub)

ORIGIN = "https://store.public.blob.vercel-storage.com"


class NodeTransportErrorMappingTest(unittest.TestCase):
    def test_blob_not_found_error_is_mapped_to_not_found(self):
        completed = type("Completed", (), {
            "returncode": 1,
            "stdout": json.dumps({
                "ok": False,
                "error": "Vercel Blob: The requested blob does not exist",
                "code": "BlobNotFoundError",
                "status": None,
            }) + "\n",
            "stderr": "",
        })()
        with patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "fake-unit-test-token-not-a-credential"}), \
                patch.object(pub.subprocess, "run", return_value=completed) as run:
            transport = pub.NodeBlobTransport(Path("helper.mjs"), Path("/tmp/no-env-needed"))
            with self.assertRaises(pub.NotFoundError):
                transport.head(f"{ORIGIN}/marketwiki/manifest.json")
            run.assert_called_once()


class FakeTransport:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.meta: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.etags = 0
        self.fail_put_path: str | None = None
        self.conflict_puts = 0
        self.conflict_put_path: str | None = None
        self.secret = "vercel_blob_super_secret_value"

    def _url(self, pathname: str) -> str:
        return f"{ORIGIN}/{pathname}"

    def head(self, url: str):
        self.calls.append(("head", url))
        if url not in self.objects:
            raise pub.NotFoundError()
        return self.meta[url]

    def put(self, pathname: str, file: Path, *, overwrite: bool, if_match: str | None, cache_age: int):
        self.calls.append(("put", pathname, overwrite, if_match, cache_age))
        if pathname == self.fail_put_path:
            raise pub.PublishError("injected", f"failed with {self.secret}")
        url = self._url(pathname)
        if self.conflict_puts and (self.conflict_put_path is None or pathname == self.conflict_put_path):
            self.conflict_puts -= 1
            raise pub.ConflictError("injected conflict")
        current = self.meta.get(url)
        if current is not None:
            if not overwrite:
                raise pub.ConflictError("already exists")
            if if_match != current["etag"]:
                raise pub.ConflictError("etag mismatch")
        elif overwrite:
            raise pub.ConflictError("cannot overwrite missing object")
        self.etags += 1
        body = file.read_bytes()
        self.objects[url] = body
        self.meta[url] = {"etag": f"etag-{self.etags}", "size": len(body), "uploadedAt": f"2026-08-09T00:00:{self.etags:02d}Z"}
        return {"url": url, "pathname": pathname}

    def list(self, prefix: str, cursor=None):
        self.calls.append(("list", prefix, cursor))
        blobs = []
        for url, body in self.objects.items():
            pathname = urlsplit(url).path.lstrip("/")
            if pathname.startswith(prefix):
                blobs.append({"url": url, "pathname": pathname, "size": len(body),
                              "uploadedAt": self.meta[url]["uploadedAt"]})
        return {"blobs": blobs, "cursor": None}

    def delete(self, urls: list[str]):
        self.calls.append(("delete", tuple(urls)))
        for url in urls:
            self.objects.pop(url, None)
            self.meta.pop(url, None)

    def fetch(self, url: str, timeout: float):
        clean = url.split("?", 1)[0]
        body = self.objects.get(clean)
        if body is None:
            return 404, {"content-type": "application/json"}, b""
        return 200, {"content-type": "application/json", "etag": self.meta[clean]["etag"]}, body


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transport = FakeTransport()
        self.publisher = pub.Publisher(
            origin=ORIGIN, prefix="marketwiki", transport=self.transport,
            fetch=self.transport.fetch, state_path=self.root / "state.json",
            freeze_path=self.root / "freeze.json", retention=3,
            propagation_attempts=4, conflict_attempts=3, sleep=lambda _: None,
        )

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, name: str, value: int = 1) -> tuple[Path, bytes, str]:
        health_row = {
            "status": "pass", "dataAsOf": "2026-08-09T01:00:00Z",
            "producer": {"jobId": None, "latestStatus": "not_applicable", "lastSuccessAt": None},
            "artifactTimestamp": "2026-08-09T01:00:00Z", "validation": "pass",
            "usableLastKnownGood": True, "stalenessThresholdSeconds": 86400,
        }
        health_sections = {
            section: dict(health_row) for section in (
                "counts", "actionBuckets", "topTags", "categoryCounts", "marketPosture",
                "dailyJournal", "cronTimeline",
                "intradayEquityWatchdog", "marketGraphs", "currentAsymmetricShortlist",
                "aiProjectionExhibits", "aiWarRoomCompleteData", "sources", "tickers",
            )
        }
        snapshot = {
            "schemaVersion": 1,
            "publications": [],
            "dataAsOf": "2026-08-09T01:00:00Z",
            "refreshMode": "runtime-manifest",
            "counts": {"reports": f"{name}:{value}"}, "actionBuckets": {}, "topTags": [],
            "categoryCounts": {}, "marketPosture": [],
            "dailyJournal": [], "cronTimeline": [],
            "intradayEquityWatchdog": None, "marketGraphs": [],
            "currentAsymmetricShortlist": None, "aiProjectionExhibits": None,
            "aiWarRoomCompleteData": None, "sources": [], "tickers": [], "focusTickers": [],
            "sourceHealth": {
                "status": "pass", "criticalSections": [], "staleSections": [],
                "missingSections": [], "sections": health_sections,
            },
            "privacy": {
                "classification": "public", "projection": "structural-allowlist-v1",
                "excluded": [], "note": "public projection validated",
            },
        }
        body = pub.canonical_json(snapshot)
        path = self.root / f"{name}.json"
        path.write_bytes(body)
        return path, body, pub.sha256_bytes(body)

    def write_snapshot_value(self, name: str, mutate) -> Path:
        path, body, _ = self.snapshot(name)
        value = json.loads(body)
        mutate(value)
        path.write_bytes(pub.canonical_json(value))
        return path

    def assert_no_transport_writes(self):
        self.assertFalse(any(call[0] in {"put", "delete"} for call in self.transport.calls))

    @staticmethod
    def metadata():
        return {
            "builtAt": "2026-08-09T01:02:03Z",
            "projectionStatus": {"status": "pass", "privacy": "validated"},
        }

    def publish(self, name: str, value: int = 1):
        path, body, digest = self.snapshot(name, value)
        result = self.publisher.publish(path, self.metadata())
        return result, body, digest

    def manifest(self):
        return json.loads(self.transport.objects[f"{ORIGIN}/marketwiki/manifest.json"])

    def test_new_snapshot_is_uploaded_verified_before_conditional_manifest(self):
        result, body, digest = self.publish("one")
        self.assertEqual(result["action"], "published")
        calls = self.transport.calls
        snapshot_put = next(i for i, call in enumerate(calls) if call[:2] == ("put", f"marketwiki/snapshots/{digest}.json"))
        manifest_put = next(i for i, call in enumerate(calls) if call[:2] == ("put", "marketwiki/manifest.json"))
        self.assertLess(snapshot_put, manifest_put)
        snapshot_url = f"{ORIGIN}/marketwiki/snapshots/{digest}.json"
        self.assertEqual(self.transport.objects[snapshot_url], body)
        manifest = self.manifest()
        self.assertEqual(manifest["snapshotId"], f"sha256:{digest}")
        self.assertEqual(manifest["objectSha256"], digest)
        self.assertEqual(manifest["snapshotPath"], f"marketwiki/snapshots/{digest}.json")
        self.assertEqual(manifest["byteLength"], len(body))
        self.assertIsNone(manifest["previousSnapshotId"])
        self.assertEqual(manifest["sourceHealth"]["status"], "pass")
        self.assertEqual(manifest["projectionStatus"]["status"], "pass")
        self.assertEqual(calls[manifest_put][2:], (False, None, 60))

    def test_existing_immutable_snapshot_is_never_overwritten_and_exactly_verified(self):
        path, body, digest = self.snapshot("same")
        url = f"{ORIGIN}/marketwiki/snapshots/{digest}.json"
        self.transport.objects[url] = body
        self.transport.meta[url] = {"etag": "old", "size": len(body), "uploadedAt": "2026-08-08T00:00:00Z"}
        self.publisher.publish(path, self.metadata())
        puts = [call for call in self.transport.calls if call[0] == "put" and "snapshots" in call[1]]
        self.assertEqual(puts[0][2], False)
        self.assertEqual(self.transport.objects[url], body)

    def test_existing_immutable_key_with_wrong_bytes_aborts_before_manifest(self):
        path, body, digest = self.snapshot("collision")
        url = f"{ORIGIN}/marketwiki/snapshots/{digest}.json"
        wrong = body + b" "
        self.transport.objects[url] = wrong
        self.transport.meta[url] = {"etag": "wrong", "size": len(wrong), "uploadedAt": "2026-08-08T00:00:00Z"}
        with self.assertRaisesRegex(pub.PublishError, "mismatch"):
            self.publisher.publish(path, self.metadata())
        self.assertNotIn(f"{ORIGIN}/marketwiki/manifest.json", self.transport.objects)

    def test_identical_remote_snapshot_is_no_change_and_recovers_corrupt_local_state(self):
        _, _, digest = self.publish("same")
        self.publisher.state_path.write_text("not json")
        before = len([c for c in self.transport.calls if c[0] == "put"])
        result, _, _ = self.publish("same")
        after = len([c for c in self.transport.calls if c[0] == "put"])
        self.assertEqual(result["action"], "no_change")
        self.assertEqual(before, after)
        state = json.loads(self.publisher.state_path.read_text())
        self.assertTrue(state["recoveredFromRemote"])
        self.assertEqual(state["lastSuccessfulSnapshotId"], f"sha256:{digest}")

    def test_snapshot_upload_failure_leaves_manifest_and_state_unchanged(self):
        self.publish("old")
        old_manifest = self.transport.objects[f"{ORIGIN}/marketwiki/manifest.json"]
        old_state = self.publisher.state_path.read_bytes()
        _, _, digest = self.snapshot("new")
        self.transport.fail_put_path = f"marketwiki/snapshots/{digest}.json"
        with self.assertRaises(pub.PublishError):
            self.publisher.publish(self.root / "new.json", self.metadata())
        self.assertEqual(self.transport.objects[f"{ORIGIN}/marketwiki/manifest.json"], old_manifest)
        self.assertEqual(self.publisher.state_path.read_bytes(), old_state)

    def test_manifest_failure_does_not_advance_local_state(self):
        self.publish("old")
        old_state = self.publisher.state_path.read_bytes()
        self.transport.fail_put_path = "marketwiki/manifest.json"
        with self.assertRaises(pub.PublishError):
            self.publish("new")
        self.assertEqual(self.publisher.state_path.read_bytes(), old_state)

    def test_precondition_conflict_is_refetched_and_retried(self):
        self.publish("old")
        self.transport.conflict_puts = 1
        self.transport.conflict_put_path = "marketwiki/manifest.json"
        result, _, _ = self.publish("new")
        self.assertEqual(result["action"], "published")
        manifest_puts = [c for c in self.transport.calls if c[:2] == ("put", "marketwiki/manifest.json")]
        self.assertGreaterEqual(len(manifest_puts), 3)  # old + conflict + success
        self.assertTrue(manifest_puts[-1][2])
        self.assertIsNotNone(manifest_puts[-1][3])

    def test_stale_public_manifest_readback_is_retried(self):
        self.publish("old")
        old_body = self.transport.objects[f"{ORIGIN}/marketwiki/manifest.json"]
        real_fetch = self.transport.fetch
        stale_remaining = 1

        def stale_fetch(url, timeout):
            nonlocal stale_remaining
            if "/manifest.json?" in url and stale_remaining and any(c[:2] == ("put", "marketwiki/manifest.json") for c in self.transport.calls[-2:]):
                stale_remaining -= 1
                return 200, {"content-type": "application/json"}, old_body
            return real_fetch(url, timeout)

        self.publisher.fetch = stale_fetch
        result, _, _ = self.publish("new")
        self.assertEqual(result["action"], "published")
        self.assertEqual(stale_remaining, 0)

    def test_previous_pointer_rolls_and_retention_preserves_current_previous(self):
        _, _, first = self.publish("one")
        _, _, second = self.publish("two")
        _, _, third = self.publish("three")
        _, _, fourth = self.publish("four")
        manifest = self.manifest()
        self.assertEqual(manifest["snapshotId"], f"sha256:{fourth}")
        self.assertEqual(manifest["previousSnapshotId"], f"sha256:{third}")
        urls = set(self.transport.objects)
        self.assertIn(f"{ORIGIN}/marketwiki/snapshots/{fourth}.json", urls)
        self.assertIn(f"{ORIGIN}/marketwiki/snapshots/{third}.json", urls)
        snapshots = [u for u in urls if "/snapshots/" in u]
        self.assertLessEqual(len(snapshots), 3)
        self.assertNotIn(f"{ORIGIN}/marketwiki/snapshots/{first}.json", urls)
        self.assertNotEqual(first, second)

    def test_freeze_blocks_publish_and_rollback_requires_freeze(self):
        _, _, first = self.publish("one")
        self.publish("two")
        with self.assertRaisesRegex(pub.PublishError, "requires publisher freeze"):
            self.publisher.rollback(f"sha256:{first}")
        self.publisher.freeze_path.write_text("{}")
        path, _, _ = self.snapshot("three")
        with self.assertRaisesRegex(pub.PublishError, "publisher frozen"):
            self.publisher.publish(path, self.metadata())

    def test_rollback_conditionally_points_to_verified_retained_snapshot(self):
        _, _, first = self.publish("one")
        _, _, second = self.publish("two")
        self.publisher.freeze_path.write_text("{}")
        rolled = self.publisher.rollback(f"sha256:{first}")
        self.assertEqual(rolled["snapshotId"], f"sha256:{first}")
        self.assertEqual(rolled["previousSnapshotId"], f"sha256:{second}")
        manifest_put = [c for c in self.transport.calls if c[:2] == ("put", "marketwiki/manifest.json")][-1]
        self.assertTrue(manifest_put[2])
        self.assertIsNotNone(manifest_put[3])

    def test_emergency_delete_requires_freeze_and_protects_active(self):
        _, _, first = self.publish("one")
        _, _, second = self.publish("two")
        with self.assertRaises(pub.PublishError):
            self.publisher.emergency_delete(f"sha256:{first}")
        self.publisher.freeze_path.write_text("{}")
        with self.assertRaisesRegex(pub.PublishError, "current/previous"):
            self.publisher.emergency_delete(f"sha256:{first}")
        deleted = self.publisher.emergency_delete(f"sha256:{first}", allow_active=True)
        self.assertEqual(len(deleted), 1)
        self.assertNotIn(f"{ORIGIN}/marketwiki/snapshots/{first}.json", self.transport.objects)
        self.assertNotEqual(first, second)

    def test_dry_run_performs_no_remote_or_local_writes(self):
        path, _, _ = self.snapshot("plan")
        result = self.publisher.publish(path, self.metadata(), dry_run=True)
        self.assertEqual(result["action"], "publish")
        self.assertFalse(any(call[0] in {"put", "delete"} for call in self.transport.calls))
        self.assertFalse(self.publisher.state_path.exists())

    def test_failure_state_deduplicates_alert_and_redacts_token(self):
        error = pub.PublishError("transport", f"bad {self.transport.secret}")
        self.assertTrue(self.publisher.record_failure(error, cooldown_seconds=3600))
        self.assertFalse(self.publisher.record_failure(error, cooldown_seconds=3600))
        text = self.publisher.state_path.read_text()
        self.assertNotIn(self.transport.secret, text)
        state = json.loads(text)
        self.assertFalse(state["alertDue"])
        self.assertEqual(state["consecutiveFailures"], 2)

    def test_invalid_origin_and_manifest_host_are_rejected(self):
        with self.assertRaises(pub.PublishError):
            pub.validate_origin("http://example.com")
        self.publish("safe")
        manifest_url = f"{ORIGIN}/marketwiki/manifest.json"
        manifest = json.loads(self.transport.objects[manifest_url])
        manifest["snapshotUrl"] = "https://evil.example/x.json"
        self.transport.objects[manifest_url] = pub.canonical_json(manifest)
        with self.assertRaises(pub.PublishError):
            self.publisher.read_remote_manifest()

    def test_lock_contention_is_nonblocking_quiet_noop_primitive(self):
        lock = self.root / "publisher.lock"
        with pub.nonblocking_flock(lock) as first:
            self.assertTrue(first)
            with pub.nonblocking_flock(lock) as second:
                self.assertFalse(second)

    def test_metadata_must_come_from_snapshot_or_override(self):
        path = self.root / "bad.json"
        path.write_bytes(pub.canonical_json({"schemaVersion": 1}))
        with self.assertRaises(pub.PublishError):
            self.publisher.publish(path, self.metadata())

    def test_shadow_mode_uses_isolated_prefix_and_state_paths(self):
        parser = pub.build_parser()
        args = parser.parse_args(["--shadow", "publish", "snapshot.json"])
        prefix, state, freeze, lock = pub.mode_paths(args)
        self.assertEqual(prefix, "marketwiki/shadow")
        self.assertIn("_shadow", state.name)
        self.assertIn("_shadow", freeze.name)
        self.assertIn("_shadow", lock.name)

    def test_snapshot_content_type_or_schema_mismatch_fails(self):
        path, _, digest = self.snapshot("invalid-readback")
        original_fetch = self.transport.fetch

        def wrong_type(url, timeout):
            status, headers, body = original_fetch(url, timeout)
            if f"/snapshots/{digest}.json" in url:
                headers = {"content-type": "text/plain"}
            return status, headers, body

        self.publisher.fetch = wrong_type
        with self.assertRaisesRegex(pub.PublishError, "content-type"):
            self.publisher.publish(path, self.metadata())
        self.assertNotIn(f"{ORIGIN}/marketwiki/manifest.json", self.transport.objects)

    def test_noncanonical_snapshot_variants_are_rejected_before_transport_write(self):
        path, body, _ = self.snapshot("noncanonical")
        value = json.loads(body)
        reversed_value = dict(reversed(list(value.items())))
        variants = {
            "missing-lf": body[:-1],
            "extra-lf": body + b"\n",
            "unsorted": (json.dumps(reversed_value, ensure_ascii=False, separators=(",", ":")) + "\n").encode(),
            "noncompact": (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode(),
        }
        value["categoryCounts"]["label"] = "cafe\u0301"
        variants["non-nfc"] = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for name, variant in variants.items():
            with self.subTest(name=name):
                self.transport.calls.clear()
                path.write_bytes(variant)
                with self.assertRaisesRegex(pub.PublishError, "noncanonical"):
                    self.publisher.publish(path, self.metadata())
                self.assert_no_transport_writes()

    def test_oversized_snapshot_is_rejected_before_transport_write(self):
        path = self.root / "oversized.json"
        path.write_bytes(b"{" + b" " * pub.MAX_SNAPSHOT_BYTES + b"}")
        with self.assertRaisesRegex(pub.PublishError, "hard cap"):
            self.publisher.publish(path, self.metadata())
        self.assert_no_transport_writes()

    def test_public_schema_violation_is_rejected_before_transport_write(self):
        path = self.write_snapshot_value("bad-schema", lambda value: value.pop("refreshMode"))
        with self.assertRaisesRegex(pub.PublishError, "schema violation"):
            self.publisher.publish(path, self.metadata())
        self.assert_no_transport_writes()

    def test_precontract_snapshot_is_rejected_before_transport_or_state_change(self):
        self.publish("old")
        old_objects = dict(self.transport.objects)
        old_state = self.publisher.state_path.read_bytes()
        self.transport.calls.clear()
        path = self.write_snapshot_value("precontract", lambda value: value.pop("publications"))
        with self.assertRaisesRegex(pub.PublishError, "publications.*required") as raised:
            self.publisher.publish(path, self.metadata())
        self.assertEqual(raised.exception.code, "snapshot_invalid")
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.transport.objects, old_objects)
        self.assertEqual(self.publisher.state_path.read_bytes(), old_state)

    def test_malformed_publications_are_rejected_before_transport(self):
        from test_publications import example

        for malformed in (None, {}, "invalid", [None], [{}], [{**example(), "publishedAt": 42}]):
            with self.subTest(publications=malformed):
                path = self.write_snapshot_value("malformed-publications", lambda value: value.update(publications=malformed))
                with self.assertRaisesRegex(pub.PublishError, "schema violation") as raised:
                    self.publisher.publish(path, self.metadata())
                self.assertEqual(raised.exception.code, "snapshot_invalid")
                self.assertEqual(self.transport.calls, [])
                self.assertFalse(self.publisher.state_path.exists())

    def test_valid_publication_is_published_and_preserved(self):
        from test_publications import example

        row = example()
        path = self.write_snapshot_value("publication", lambda value: value.update(publications=[row]))
        result = self.publisher.publish(path, self.metadata())
        self.assertEqual(result["action"], "published")
        published = json.loads(self.transport.objects[self.manifest()["snapshotUrl"]])
        self.assertEqual(published["publications"], [row])

    def test_private_key_is_rejected_before_transport_write(self):
        path = self.write_snapshot_value("private-key", lambda value: value["categoryCounts"].update({"accountValue": 42}))
        with self.assertRaisesRegex(pub.PublishError, "forbidden private key"):
            self.publisher.publish(path, self.metadata())
        self.assert_no_transport_writes()

    def test_business_label_containing_token_word_is_not_treated_as_credential(self):
        pub._validate_public_privacy({"summary": {"actions": {"HOLD TOKEN": 1}}})

    def test_forbidden_path_and_private_classification_are_rejected_before_writes(self):
        for name, mutation in (
            ("path", lambda value: value["categoryCounts"].update({"citation": "/root/private.json"})),
            ("class", lambda value: value["categoryCounts"].update({"privacy_class": "private_local_only"})),
        ):
            with self.subTest(name=name):
                self.transport.calls.clear()
                path = self.write_snapshot_value(name, mutation)
                with self.assertRaises(pub.PublishError):
                    self.publisher.publish(path, self.metadata())
                self.assert_no_transport_writes()

    def test_manifest_only_snapshot_metadata_is_rejected_before_transport_write(self):
        path = self.write_snapshot_value("immutable-field", lambda value: value.update({"publishedAt": "2026-08-09T01:00:00Z"}))
        with self.assertRaisesRegex(pub.PublishError, "manifest-only"):
            self.publisher.publish(path, self.metadata())
        self.assert_no_transport_writes()

    def test_failed_source_health_and_projection_are_rejected_before_writes(self):
        path = self.write_snapshot_value("bad-health", lambda value: value["sourceHealth"].update({"status": "fail"}))
        with self.assertRaisesRegex(pub.PublishError, "blocks publication"):
            self.publisher.publish(path, self.metadata())
        self.assert_no_transport_writes()
        path, _, _ = self.snapshot("bad-projection")
        metadata = self.metadata()
        metadata["projectionStatus"] = {"status": "degraded"}
        with self.assertRaisesRegex(pub.PublishError, "must be pass"):
            self.publisher.publish(path, metadata)
        self.assert_no_transport_writes()

    def test_local_manifest_schema_is_enforced_before_transport_write(self):
        path, _, _ = self.snapshot("bad-local-manifest")
        real_build = self.publisher._build_manifest

        def invalid_build(entry, remote):
            manifest = real_build(entry, remote)
            manifest["projectionStatus"] = "pass"
            return manifest

        with patch.object(self.publisher, "_build_manifest", side_effect=invalid_build):
            with self.assertRaisesRegex(pub.PublishError, "manifest schema violation"):
                self.publisher.publish(path, self.metadata())
        self.assert_no_transport_writes()

    def test_remote_manifest_schema_is_enforced_before_transport_write(self):
        self.publish("valid-remote")
        manifest_url = f"{ORIGIN}/marketwiki/manifest.json"
        manifest = json.loads(self.transport.objects[manifest_url])
        manifest["projectionStatus"] = "pass"
        self.transport.objects[manifest_url] = pub.canonical_json(manifest)
        self.transport.calls.clear()
        path, _, _ = self.snapshot("next")
        with self.assertRaisesRegex(pub.PublishError, "manifest"):
            self.publisher.publish(path, self.metadata())
        self.assert_no_transport_writes()


if __name__ == "__main__":
    unittest.main()
