from datetime import timedelta
from hashlib import sha256
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils.timezone import now

from .fetch import FetchStats, run_fetch
from .gameinfo import GameInfo
from .models import GameSource, GameSourceFetch
from .providers import GameSourceProvider


class FakeProvider(GameSourceProvider):
    def __init__(self, source_type, fetches=(), infos=()):
        self.source_type = source_type
        self.fetches = list(fetches)
        self.infos = list(infos)
        self.fetched_urls = []

    def owns(self, url: str) -> bool:
        return False

    def fetch(self, url: str) -> str:
        self.fetched_urls.append(url)
        result = self.fetches.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        result = self.infos.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FetchTest(TestCase):
    def source(
        self,
        source_type=GameSource.SourceType.APERO,
        url="http://example.com/game",
        **kwargs,
    ):
        return GameSource.objects.create(type=source_type, url=url, **kwargs)

    def info(self, name):
        return GameInfo(name=name, description=f"{name} description")

    def run_with(self, *providers, **kwargs):
        provider_map = {
            provider.source_type: provider for provider in providers
        }
        with patch("curation.fetch.PROVIDER_BY_TYPE", provider_map):
            return run_fetch(**kwargs)

    def test_new_source_creates_fetch_with_hash(self):
        info = self.info("Game")
        self.source()
        provider = FakeProvider(
            GameSource.SourceType.APERO, fetches=["raw"], infos=[info]
        )

        stats = self.run_with(provider)

        canonical = info.to_canonical()
        fetch = GameSourceFetch.objects.get()
        self.assertEqual(stats, [FetchStats("APERO", 1, 1, 0, 1, 0)])
        self.assertEqual(fetch.raw_content, "raw")
        self.assertEqual(fetch.canonical_text, canonical)
        self.assertEqual(
            fetch.canonical_text_hash,
            sha256(canonical.encode()).hexdigest(),
        )

    def test_identical_refetch_bumps_latest_fetch(self):
        self.source()
        first_time = now()
        second_time = first_time + timedelta(minutes=5)

        with patch("curation.fetch.now", return_value=first_time):
            self.run_with(
                FakeProvider(
                    GameSource.SourceType.APERO,
                    fetches=["raw 1"],
                    infos=[self.info("Same")],
                )
            )
        original = GameSourceFetch.objects.get()

        with patch("curation.fetch.now", return_value=second_time):
            stats = self.run_with(
                FakeProvider(
                    GameSource.SourceType.APERO,
                    fetches=["raw 2"],
                    infos=[self.info("Same")],
                )
            )

        updated = GameSourceFetch.objects.get()
        self.assertEqual(stats, [FetchStats("APERO", 1, 1, 0, 0, 1)])
        self.assertEqual(updated.pk, original.pk)
        self.assertEqual(updated.first_fetch, first_time)
        self.assertEqual(updated.last_fetch, second_time)

    def test_changed_canonical_creates_second_fetch(self):
        self.source()
        self.run_with(
            FakeProvider(
                GameSource.SourceType.APERO,
                fetches=["raw 1"],
                infos=[self.info("Old")],
            )
        )

        stats = self.run_with(
            FakeProvider(
                GameSource.SourceType.APERO,
                fetches=["raw 2"],
                infos=[self.info("New")],
            )
        )

        hashes = list(
            GameSourceFetch.objects.order_by("first_fetch").values_list(
                "canonical_text_hash", flat=True
            )
        )
        self.assertEqual(stats, [FetchStats("APERO", 1, 1, 0, 1, 0)])
        self.assertEqual(GameSourceFetch.objects.count(), 2)
        self.assertNotEqual(hashes[0], hashes[1])

    def test_failure_records_error_and_later_success_clears_it(self):
        source = self.source()
        failed_at = now()
        succeeded_at = failed_at + timedelta(minutes=5)

        with self.assertLogs("worker", level="ERROR"):
            with patch("curation.fetch.now", return_value=failed_at):
                failed_stats = self.run_with(
                    FakeProvider(
                        GameSource.SourceType.APERO,
                        fetches=[RuntimeError("boom")],
                    )
                )

        source.refresh_from_db()
        self.assertEqual(failed_stats, [FetchStats("APERO", 1, 0, 1, 0, 0)])
        self.assertEqual(source.failing_since, failed_at)
        self.assertEqual(source.last_error, "boom")
        self.assertFalse(GameSourceFetch.objects.exists())

        with patch("curation.fetch.now", return_value=succeeded_at):
            success_stats = self.run_with(
                FakeProvider(
                    GameSource.SourceType.APERO,
                    fetches=["raw"],
                    infos=[self.info("Recovered")],
                )
            )

        source.refresh_from_db()
        self.assertEqual(success_stats, [FetchStats("APERO", 1, 1, 0, 1, 0)])
        self.assertIsNone(source.failing_since)
        self.assertIsNone(source.last_error)
        self.assertEqual(GameSourceFetch.objects.count(), 1)

    def test_type_filter_limits_sources(self):
        self.source(GameSource.SourceType.APERO, "http://example.com/apero")
        self.source(GameSource.SourceType.QSP, "http://example.com/qsp")
        apero = FakeProvider(
            GameSource.SourceType.APERO,
            fetches=["apero raw"],
            infos=[self.info("Apero")],
        )
        qsp = FakeProvider(
            GameSource.SourceType.QSP,
            fetches=["qsp raw"],
            infos=[self.info("QSP")],
        )

        stats = self.run_with(qsp, apero, types=[GameSource.SourceType.QSP])

        self.assertEqual(stats, [FetchStats("QSP", 1, 1, 0, 1, 0)])
        self.assertEqual(apero.fetched_urls, [])
        self.assertEqual(qsp.fetched_urls, ["http://example.com/qsp"])

    def test_limit_fetches_oldest_attempts_first(self):
        old_source = self.source(url="http://example.com/old")
        self.source(url="http://example.com/recent", last_attempt=now())
        provider = FakeProvider(
            GameSource.SourceType.APERO,
            fetches=["raw"],
            infos=[self.info("Old")],
        )

        stats = self.run_with(provider, limit=1)

        self.assertEqual(stats, [FetchStats("APERO", 1, 1, 0, 1, 0)])
        self.assertEqual(provider.fetched_urls, [old_source.url])
        self.assertEqual(GameSourceFetch.objects.count(), 1)

    def test_source_id_targets_one_source(self):
        self.source(url="http://example.com/skip")
        wanted = self.source(url="http://example.com/wanted")
        provider = FakeProvider(
            GameSource.SourceType.APERO,
            fetches=["raw"],
            infos=[self.info("Wanted")],
        )

        stats = self.run_with(provider, source_id=wanted.pk)

        self.assertEqual(stats, [FetchStats("APERO", 1, 1, 0, 1, 0)])
        self.assertEqual(provider.fetched_urls, [wanted.url])

    def test_sources_fetch_command_prints_counts(self):
        def fake_run_fetch(types, limit, source_id, url, on_source_done=None):
            self.assertEqual(types, [GameSource.SourceType.APERO])
            self.assertEqual(limit, 5)
            self.assertEqual(source_id, 123)
            self.assertEqual(url, "http://example.com/game")
            self.assertIsNone(on_source_done)
            return [FetchStats("APERO", 12, 11, 1, 4, 7)]

        stdout = StringIO()
        with patch(
            "curation.management.commands.sources.run_fetch", fake_run_fetch
        ):
            call_command(
                "sources",
                "fetch",
                "--type",
                GameSource.SourceType.APERO,
                "--limit",
                "5",
                "--source",
                "123",
                "--url",
                "http://example.com/game",
                stdout=stdout,
            )

        self.assertIn(
            "sources [APERO]: 12 processed, 11 ok, 1 failed, "
            "4 new, 7 unchanged",
            stdout.getvalue(),
        )

    def test_sources_fetch_command_verbose_prints_source_url(self):
        source = GameSource(
            id=46,
            type=GameSource.SourceType.APERO,
            url="http://example.com/game",
        )

        def fake_run_fetch(types, limit, source_id, url, on_source_done=None):
            self.assertIsNotNone(on_source_done)
            on_source_done(source, "created", None)
            return [FetchStats("APERO", 1, 1, 0, 1, 0)]

        stdout = StringIO()
        with patch(
            "curation.management.commands.sources.run_fetch", fake_run_fetch
        ):
            call_command("sources", "fetch", "-v", "2", stdout=stdout)

        self.assertIn(
            "source #46 [APERO] http://example.com/game: created",
            stdout.getvalue(),
        )
