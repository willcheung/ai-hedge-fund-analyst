import io
import json
import sys
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fetch_x_signals as scanner


MEMBER = {
    "id": "123",
    "username": "analyst",
    "name": "An Analyst",
    "description": "semiconductor research",
    "public_metrics": {"followers_count": 42},
    "style": "ai_infrastructure",
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class RosterCacheTests(unittest.TestCase):
    def test_cache_hit_avoids_member_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "roster.json"
            fetched_at = datetime.now(timezone.utc).isoformat()
            scanner.save_roster_cache([MEMBER], fetched_at=fetched_at, path=path)
            with mock.patch.object(scanner, "fetch_list_members") as fetch_members:
                members, meta = scanner.get_list_roster(path=path)
            fetch_members.assert_not_called()
            self.assertEqual(members[0]["username"], "analyst")
            self.assertEqual(members[0]["fetched_at"], fetched_at)
            self.assertEqual(meta["status"], "hit")

    def test_forced_refresh_persists_full_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "roster.json"
            with mock.patch.object(
                scanner, "fetch_list_members", return_value=[dict(MEMBER)]
            ) as fetch_members:
                members, meta = scanner.get_list_roster(force_refresh=True, path=path)
            fetch_members.assert_called_once_with(return_metadata=True)
            saved = json.loads(path.read_text())
            self.assertEqual(meta["status"], "refreshed")
            self.assertEqual(saved["members"][0]["id"], "123")
            self.assertEqual(saved["members"][0]["description"], "semiconductor research")
            self.assertEqual(saved["members"][0]["public_metrics"], {"followers_count": 42})
            self.assertEqual(saved["members"][0]["style"], "ai_infrastructure")
            self.assertTrue(saved["members"][0]["fetched_at"])
            self.assertEqual(members[0]["fetched_at"], saved["fetched_at"])

    def test_forced_refresh_pagination_failure_preserves_existing_cache(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "roster.json"
            scanner.save_roster_cache([MEMBER], path=path)
            original_cache = path.read_bytes()
            page_one = FakeResponse({
                "data": [dict(MEMBER)],
                "meta": {"next_token": "page-two"},
            })
            page_two_error = scanner.urllib.error.HTTPError(
                "https://api.x.com/2/lists/test/members",
                500,
                "Internal Server Error",
                {},
                io.BytesIO(b"server error"),
            )
            requests = []

            def fake_urlopen(req, timeout=0):
                requests.append(req)
                if len(requests) == 1:
                    return page_one
                raise page_two_error

            with mock.patch.object(scanner, "_list_auth_tokens", return_value=["token"]), mock.patch.object(
                scanner.urllib.request, "urlopen", side_effect=fake_urlopen
            ):
                members, meta = scanner.get_list_roster(force_refresh=True, path=path)

            self.assertIsNone(members)
            self.assertEqual(meta["status"], "refresh_failed")
            self.assertEqual(path.read_bytes(), original_cache)
            self.assertEqual(len(requests), 2)
            second_query = urllib.parse.parse_qs(urllib.parse.urlparse(requests[1].full_url).query)
            self.assertEqual(second_query["pagination_token"], ["page-two"])

    def test_pagination_failure_restarts_from_page_one_with_next_auth_token(self):
        requests = []
        replacement = {**MEMBER, "id": "456", "username": "replacement"}

        def fake_urlopen(req, timeout=0):
            requests.append(req)
            auth = req.get_header("Authorization")
            query = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
            if auth == "Bearer token-a" and "pagination_token" not in query:
                return FakeResponse({"data": [dict(MEMBER)], "meta": {"next_token": "bad-page"}})
            if auth == "Bearer token-a":
                raise scanner.urllib.error.HTTPError(
                    req.full_url, 500, "Internal Server Error", {}, io.BytesIO(b"server error")
                )
            if "pagination_token" not in query:
                return FakeResponse({"data": [replacement], "meta": {"next_token": "good-page"}})
            return FakeResponse({"data": [dict(MEMBER)], "meta": {}})

        with mock.patch.object(
            scanner, "_list_auth_tokens", return_value=["token-a", "token-b"]
        ), mock.patch.object(scanner.urllib.request, "urlopen", side_effect=fake_urlopen):
            members = scanner.fetch_list_members(return_metadata=True)

        self.assertEqual([member["username"] for member in members], ["replacement", "analyst"])
        third_query = urllib.parse.parse_qs(urllib.parse.urlparse(requests[2].full_url).query)
        self.assertNotIn("pagination_token", third_query)
        self.assertEqual(requests[2].get_header("Authorization"), "Bearer token-b")

    def test_cache_rejects_future_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "roster.json"
            now = datetime(2026, 8, 28, tzinfo=timezone.utc)
            scanner.save_roster_cache([MEMBER], fetched_at=(now + timedelta(seconds=1)).isoformat(), path=path)
            members, meta = scanner.load_roster_cache(path=path, now=now)
            self.assertIsNone(members)
            self.assertEqual(meta["status"], "stale_or_invalid")

    def test_cache_rejects_malformed_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "roster.json"
            scanner.save_roster_cache([MEMBER], fetched_at="not-a-timestamp", path=path)
            members, meta = scanner.load_roster_cache(path=path)
            self.assertIsNone(members)
            self.assertEqual(meta["status"], "invalid")

    def test_cache_rejects_timestamp_older_than_30_days(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "roster.json"
            now = datetime(2026, 8, 28, tzinfo=timezone.utc)
            scanner.save_roster_cache(
                [MEMBER], fetched_at=(now - timedelta(days=30, microseconds=1)).isoformat(), path=path
            )
            members, meta = scanner.load_roster_cache(path=path, now=now)
            self.assertIsNone(members)
            self.assertEqual(meta["status"], "stale_or_invalid")

    def test_cache_accepts_timestamp_exactly_30_days_old(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "roster.json"
            now = datetime(2026, 8, 28, tzinfo=timezone.utc)
            scanner.save_roster_cache([MEMBER], fetched_at=(now - timedelta(days=30)).isoformat(), path=path)
            members, meta = scanner.load_roster_cache(path=path, now=now)
            self.assertEqual(members[0]["username"], "analyst")
            self.assertEqual(meta["status"], "hit")

    def test_list_timeline_omits_expansions_with_cached_id_map(self):
        requests = []

        def fake_urlopen(req, timeout=0):
            requests.append(req)
            return FakeResponse({"data": [], "meta": {}})

        cached = {"123": dict(MEMBER)}
        with mock.patch.object(scanner, "_list_auth_tokens", return_value=["token"]), mock.patch.object(
            scanner.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            result = scanner.fetch_list_tweets(users_by_id=cached, page_limit=1)

        query = urllib.parse.parse_qs(urllib.parse.urlparse(requests[0].full_url).query)
        self.assertNotIn("expansions", query)
        self.assertNotIn("user.fields", query)
        self.assertEqual(result["users_by_id"]["123"]["username"], "analyst")
        self.assertEqual(result["meta"]["author_mapping_source"], "roster_cache")


class OnboardingCacheTests(unittest.TestCase):
    def _existing_cache(self, directory):
        path = Path(directory) / "roster.json"
        scanner.save_roster_cache([MEMBER], path=path)
        return path

    def test_successful_add_invalidates_existing_roster_cache(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._existing_cache(td)
            with mock.patch.object(
                scanner, "add_to_list", return_value={"success": True, "username": "new"}
            ), mock.patch.object(scanner, "follow_user", return_value={"success": True}):
                result = scanner.onboard_account("new", roster_cache_path=path)
            self.assertFalse(path.exists())
            self.assertTrue(result["success"])
            self.assertEqual(result["roster_cache"]["status"], "invalidated")

    def test_already_member_invalidates_existing_roster_cache(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._existing_cache(td)
            with mock.patch.object(
                scanner,
                "add_to_list",
                return_value={"success": True, "username": "new", "already_member": True},
            ), mock.patch.object(scanner, "follow_user", return_value={"success": True}):
                result = scanner.onboard_account("new", roster_cache_path=path)
            self.assertFalse(path.exists())
            self.assertEqual(result["roster_cache"]["status"], "invalidated")

    def test_failed_add_does_not_invalidate_existing_roster_cache(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._existing_cache(td)
            original_cache = path.read_bytes()
            with mock.patch.object(scanner, "add_to_list", return_value={"error": "add failed"}), mock.patch.object(
                scanner, "follow_user", return_value={"success": True}
            ):
                result = scanner.onboard_account("new", roster_cache_path=path)
            self.assertEqual(path.read_bytes(), original_cache)
            self.assertFalse(result["success"])
            self.assertEqual(result["roster_cache"]["status"], "unchanged")


class GuardTests(unittest.TestCase):
    def run_main(self, argv, env=None):
        output = io.StringIO()
        env = env or {}
        with mock.patch.object(sys, "argv", argv), mock.patch.object(scanner, "BEARER_TOKEN", "token"), mock.patch.dict(
            scanner.os.environ, env, clear=True
        ), redirect_stdout(output):
            try:
                scanner.main()
            except SystemExit as exc:
                return exc.code, json.loads(output.getvalue())
        return 0, json.loads(output.getvalue())

    def test_default_list_scan_is_refused_before_roster_or_x_calls(self):
        with mock.patch.object(scanner, "get_list_roster") as roster:
            code, payload = self.run_main(["fetch_x_signals.py"])
        self.assertEqual(code, 2)
        roster.assert_not_called()
        self.assertIn("latest saved artifact", payload["error"])
        self.assertEqual(payload["scan_stats"]["list_scan_guard"]["allowed"], False)

    def test_explicit_allow_runs_list_scan_and_reports_cache_metadata(self):
        cache_meta = {
            "status": "hit",
            "usable": True,
            "fetched_at": "2026-08-28T00:00:00+00:00",
            "age_days": 0.5,
            "member_count": 1,
        }
        account_result = {
            "username": "analyst",
            "display_name": "An Analyst",
            "fetch_meta": {"read_path": "list_timeline"},
            "newest_id": None,
            "total_tweets": 0,
            "unique_tickers": 0,
            "tickers": {},
            "raw_tweets": [],
        }
        list_meta = {"pages": 1, "tweets_fetched": 0, "tweets_in_window": 0, "stopped_reason": "end"}
        with mock.patch.object(scanner, "get_list_roster", return_value=([dict(MEMBER)], cache_meta)) as roster, mock.patch.object(
            scanner, "process_list_timeline", return_value=({"analyst": account_result}, list_meta)
        ) as process:
            code, payload = self.run_main(["fetch_x_signals.py", "--allow-list-scan"])
        self.assertEqual(code, 0)
        roster.assert_called_once()
        process.assert_called_once()
        self.assertEqual(payload["scan_stats"]["roster_cache"]["status"], "hit")
        self.assertEqual(payload["scan_stats"]["list_scan_guard"]["allowed"], True)
        self.assertEqual(payload["scan_stats"]["list_scan_guard"]["source"], "cli")

    def test_environment_allow_runs_list_scan_and_reports_source(self):
        cache_meta = {"status": "hit", "usable": True, "member_count": 1}
        account_result = {
            "username": "analyst",
            "display_name": "An Analyst",
            "fetch_meta": {"read_path": "list_timeline"},
            "newest_id": None,
            "total_tweets": 0,
            "unique_tickers": 0,
            "tickers": {},
            "raw_tweets": [],
        }
        list_meta = {"pages": 1, "tweets_fetched": 0, "tweets_in_window": 0, "stopped_reason": "end"}
        with mock.patch.object(scanner, "get_list_roster", return_value=([dict(MEMBER)], cache_meta)), mock.patch.object(
            scanner, "process_list_timeline", return_value=({"analyst": account_result}, list_meta)
        ):
            code, payload = self.run_main(
                ["fetch_x_signals.py"], env={"HERMES_X_SCANNER_ALLOWED": "1"}
            )
        self.assertEqual(code, 0)
        self.assertTrue(payload["scan_stats"]["list_scan_guard"]["allowed"])
        self.assertEqual(payload["scan_stats"]["list_scan_guard"]["source"], "environment")


if __name__ == "__main__":
    unittest.main()
