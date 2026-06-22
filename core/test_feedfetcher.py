from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .feedfetcher import run_fetch_feeds
from .models import BlogFeed


class FeedFetcherTest(TestCase):
    def setUp(self):
        BlogFeed.objects.all().delete()

    def _feed(self, feed_id, last_attempt=None):
        return BlogFeed.objects.create(
            feed_id=feed_id,
            title=feed_id,
            url=f"https://example.com/{feed_id}",
            rss=f"https://example.com/{feed_id}.xml",
            show_author=True,
            last_attempt=last_attempt,
        )

    @patch("core.feedfetcher._fetch_blog_feed", return_value=0)
    def test_fetches_least_recently_attempted_feeds_first(self, fetch):
        ts = timezone.now()
        never = self._feed("never")
        old = self._feed("old", ts - timedelta(days=2))
        self._feed("new", ts - timedelta(days=1))

        stats = run_fetch_feeds(limit=2)

        self.assertEqual([s.feed_id for s in stats], ["never", "old"])
        self.assertEqual(
            [call.args[0].feed_id for call in fetch.call_args_list],
            [never.feed_id, old.feed_id],
        )

    @patch("core.feedfetcher._fetch_blog_feed")
    def test_failed_feed_does_not_block_next_feed(self, fetch):
        bad = self._feed("bad")
        good = self._feed("good")
        fetch.side_effect = [RuntimeError("boom"), 3]

        stats = run_fetch_feeds(limit=2)

        self.assertEqual([s.ok for s in stats], [False, True])
        bad.refresh_from_db()
        good.refresh_from_db()
        self.assertIsNotNone(bad.last_attempt)
        self.assertIsNotNone(bad.failing_since)
        self.assertEqual(bad.last_error, "boom")
        self.assertIsNotNone(good.last_attempt)
        self.assertIsNotNone(good.last_success)
        self.assertIsNone(good.failing_since)
        self.assertIsNone(good.last_error)

    @patch("core.feedfetcher._fetch_blog_feed", return_value=0)
    def test_disabled_feeds_are_skipped(self, fetch):
        self._feed("enabled")
        disabled = self._feed("disabled")
        disabled.is_enabled = False
        disabled.save(update_fields=["is_enabled"])

        stats = run_fetch_feeds(limit=None)

        self.assertEqual([s.feed_id for s in stats], ["enabled"])
        fetch.assert_called_once()
