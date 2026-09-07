import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import calconviction_growth_metrics as metrics


class ClassificationTests(unittest.TestCase):
    def tweet(self, text, note=False):
        value = {"text": text}
        if note:
            value["note_tweet"] = {"text": text}
        return value

    def test_deep_dive(self):
        self.assertEqual(metrics.classify_post(self.tweet("$XYZ deep dive:\nNumbers", True)), "deep_dive")

    def test_conviction_list(self):
        text = "No changes. " + ("x" * 300) + " Highest conviction remains XYZ."
        self.assertEqual(metrics.classify_post(self.tweet(text, True)), "conviction_list")

    def test_daily_market_brief(self):
        self.assertEqual(metrics.classify_post(self.tweet("Morning market map: breadth improved.")), "daily_market_brief")

    def test_macro_and_friday_prefixes(self):
        self.assertEqual(metrics.classify_post(self.tweet("Macro shift: credit spreads widened.")), "macro")
        self.assertEqual(metrics.classify_post(self.tweet("Friday close: breadth broke late.")), "friday_take")

    def test_earnings_result(self):
        self.assertEqual(metrics.classify_post(self.tweet("$XYZ earnings: revenue beat and guidance rose.")), "earnings_result")

    def test_watchlist(self):
        self.assertEqual(metrics.classify_post(self.tweet("2. $XYZ — Company\nRevenue grew.")), "watchlist")

    def test_watchlist_hook_with_earnings_word_is_not_earnings_result(self):
        text = "4 quantum stocks I'm watching after earnings\n\n1. $QBTS — D-Wave"
        self.assertEqual(metrics.classify_post(self.tweet(text)), "watchlist")

    def test_append_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"
            self.assertTrue(metrics.append_snapshot({"captured_at": "one"}, path))
            self.assertFalse(metrics.append_snapshot({"captured_at": "one"}, path))
            self.assertTrue(metrics.append_snapshot({"captured_at": "two"}, path))
            self.assertEqual(path.read_text().count("\n"), 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_append_snapshot_quarantines_partial_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"
            path.write_text('{"captured_at":"broken"', encoding="utf-8")
            self.assertTrue(metrics.append_snapshot({"captured_at": "good"}, path))
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(records, [{"captured_at": "good"}])
            quarantine = path.with_name(path.name + ".corrupt")
            self.assertEqual(quarantine.read_text().strip(), '{"captured_at":"broken"')
            self.assertEqual(quarantine.stat().st_mode & 0o777, 0o600)

    def test_append_snapshot_repairs_valid_unterminated_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"
            path.write_text('{"captured_at":"one"}', encoding="utf-8")
            self.assertTrue(metrics.append_snapshot({"captured_at": "two"}, path))
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(records, [{"captured_at": "one"}, {"captured_at": "two"}])

    def test_no_append_mode_never_calls_writer(self):
        snapshot = {
            "captured_at": "now",
            "profile": {"followers": 101, "tweet_count": 508},
            "scope": {
                "posts_returned": 0,
                "content_units_returned": 0,
                "truncated": False,
            },
        }
        with mock.patch.object(metrics, "collect", return_value=snapshot), mock.patch.object(
            metrics, "append_snapshot"
        ) as writer, mock.patch.object(sys, "argv", ["metrics", "--no-append"]):
            self.assertEqual(metrics.main(), 0)
        writer.assert_not_called()

    def test_thread_members_group_into_one_watchlist_unit(self):
        posts = [
            {
                "id": "10",
                "conversation_id": "10",
                "created_at": "2026-08-28T00:00:00Z",
                "format": "watchlist",
                "impressions": 100,
                "engagements": 1,
                "x_total_engagements": 2,
                "profile_clicks": 1,
                "preview": "4 small caps",
            },
            {
                "id": "11",
                "conversation_id": "10",
                "created_at": "2026-08-28T00:00:01Z",
                "format": "watchlist",
                "impressions": 50,
                "engagements": 1,
                "x_total_engagements": 3,
                "profile_clicks": 2,
                "preview": "2. $XYZ",
            },
            {
                "id": "12",
                "conversation_id": "10",
                "created_at": "2026-08-28T00:00:02Z",
                "format": "timely_single",
                "impressions": 25,
                "engagements": 0,
                "x_total_engagements": 1,
                "profile_clicks": 0,
                "preview": "Closer",
            },
        ]
        units = metrics.aggregate_content_units(posts)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["format"], "watchlist")
        self.assertEqual(units[0]["tweet_objects"], 3)
        self.assertEqual(units[0]["root_impressions"], 100)
        self.assertEqual(units[0]["profile_clicks"], 3)
        summary = metrics.summarize_by_format(
            units, "root_impressions", "object_impressions_sum"
        )["watchlist"]
        self.assertEqual(summary["rate_denominator_impressions"], 175)
        self.assertEqual(
            summary["profile_clicks_per_1000_impressions"], round(3 / 175 * 1000, 2)
        )

    def test_collect_keeps_owned_profile_click_metrics(self):
        profile = {
            "data": {
                "id": "1",
                "username": "CalConviction",
                "public_metrics": {
                    "followers_count": 101,
                    "following_count": 76,
                    "tweet_count": 508,
                    "listed_count": 1,
                    "media_count": 6,
                },
            }
        }
        timeline = {
            "data": [
                {
                    "id": "2",
                    "created_at": "2026-08-28T00:00:00Z",
                    "conversation_id": "2",
                    "text": "Morning market map: breadth improved.",
                    "public_metrics": {
                        "impression_count": 200,
                        "like_count": 1,
                        "reply_count": 0,
                        "retweet_count": 0,
                        "quote_count": 0,
                        "bookmark_count": 1,
                    },
                    "non_public_metrics": {
                        "engagements": 7,
                        "impression_count": 200,
                        "user_profile_clicks": 3,
                    },
                    "organic_metrics": {"user_profile_clicks": 3},
                }
            ]
        }
        with mock.patch.object(
            metrics.calconviction, "get_access_token", return_value="token"
        ), mock.patch.object(
            metrics.calconviction, "api_call", side_effect=[profile, timeline]
        ) as api_call:
            snapshot = metrics.collect(max_results=5)
        timeline_url = api_call.call_args_list[1].args[1]
        post = snapshot["posts"][0]
        summary = snapshot["format_summary"]["daily_market_brief"]
        self.assertIn("exclude=retweets", timeline_url)
        self.assertNotIn("replies", timeline_url)
        self.assertEqual(snapshot["schema_version"], 3)
        self.assertEqual(snapshot["scope"]["content_units_returned"], 1)
        self.assertEqual(post["profile_clicks"], 3)
        self.assertEqual(post["x_total_engagements"], 7)
        self.assertEqual(summary["profile_clicks"], 3)
        self.assertEqual(summary["profile_clicks_per_1000_impressions"], 15.0)


if __name__ == "__main__":
    unittest.main()
