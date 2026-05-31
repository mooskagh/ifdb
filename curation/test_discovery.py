from collections import Counter
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils.timezone import now

from .discovery import DiscoveryStats, run_discover
from .gameinfo import GameInfo
from .models import GameHistory, GameSource, SourceDiscoveryStatus
from .providers import DiscoveredSource, GameSourceProvider


class FakeProvider(GameSourceProvider):
    def __init__(self, source_type, urls):
        self.source_type = source_type
        self.urls = urls

    def owns(self, url: str) -> bool:
        return False

    def fetch(self, url: str) -> str:
        raise NotImplementedError

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        raise NotImplementedError

    def discover(self):
        return (DiscoveredSource(url) for url in self.urls)


class DiscoveryTest(TestCase):
    def run_with(self, *providers, types=None):
        with patch("curation.discovery.REGISTERED_PROVIDERS", list(providers)):
            return run_discover(types=types)

    def test_run_discover_creates_orphan_sources(self):
        counts = self.run_with(
            FakeProvider(
                GameSource.SourceType.APERO,
                ["http://example.com/a", "http://example.com/b"],
            )
        )

        self.assertEqual(counts, Counter({GameSource.SourceType.APERO: 2}))
        self.assertEqual(
            list(
                GameSource.objects.order_by("url").values_list(
                    "type", "url", "history_id"
                )
            ),
            [
                (GameSource.SourceType.APERO, "http://example.com/a", None),
                (GameSource.SourceType.APERO, "http://example.com/b", None),
            ],
        )

    def test_run_discover_dedups_by_type_and_url(self):
        history = GameHistory.objects.create(creation_time=now())
        GameSource.objects.create(
            type=GameSource.SourceType.APERO,
            url="http://example.com/existing",
            history=history,
            created_at=now(),
        )
        provider = FakeProvider(
            GameSource.SourceType.APERO,
            ["http://example.com/existing", "http://example.com/new"],
        )

        first_counts = self.run_with(provider)
        second_counts = self.run_with(provider)

        self.assertEqual(
            first_counts, Counter({GameSource.SourceType.APERO: 1})
        )
        self.assertEqual(second_counts, Counter())
        self.assertEqual(
            GameSource.objects.filter(
                type=GameSource.SourceType.APERO,
                url="http://example.com/existing",
            ).count(),
            1,
        )
        self.assertEqual(GameSource.objects.count(), 2)

    def test_discovered_source_url_gets_provider_type(self):
        self.run_with(
            FakeProvider(GameSource.SourceType.QSP, ["http://example.com/qsp"])
        )

        source = GameSource.objects.get()
        self.assertEqual(source.type, GameSource.SourceType.QSP)
        self.assertEqual(source.url, "http://example.com/qsp")

    def test_run_discover_filters_types(self):
        counts = self.run_with(
            FakeProvider(
                GameSource.SourceType.APERO, ["http://example.com/a"]
            ),
            FakeProvider(
                GameSource.SourceType.QSP, ["http://example.com/qsp"]
            ),
            types=[GameSource.SourceType.QSP],
        )

        self.assertEqual(counts, Counter({GameSource.SourceType.QSP: 1}))
        self.assertEqual(
            GameSource.objects.get().type, GameSource.SourceType.QSP
        )

    def test_run_discover_reports_existing_new_and_missing(self):
        GameSource.objects.create(
            type=GameSource.SourceType.APERO,
            url="http://example.com/existing",
            created_at=now(),
        )
        GameSource.objects.create(
            type=GameSource.SourceType.APERO,
            url="http://example.com/missing",
            created_at=now(),
        )
        provider = FakeProvider(
            GameSource.SourceType.APERO,
            [
                "http://example.com/existing",
                "http://example.com/new",
                "http://example.com/new",
            ],
        )
        stats = []

        with patch("curation.discovery.REGISTERED_PROVIDERS", [provider]):
            run_discover(on_provider_done=stats.append)

        self.assertEqual(
            stats,
            [
                DiscoveryStats(
                    source_type=GameSource.SourceType.APERO,
                    candidates=3,
                    discovered=2,
                    existing=1,
                    new=1,
                    missing=1,
                )
            ],
        )

    def test_run_discover_records_status(self):
        provider = FakeProvider(
            GameSource.SourceType.APERO, ["http://example.com/a"]
        )

        self.run_with(provider)  # discovers /a as new
        self.run_with(provider)  # now existing -> new row
        self.run_with(provider)  # identical to previous -> extends it

        rows = list(
            SourceDiscoveryStatus.objects.filter(
                source_type=GameSource.SourceType.APERO
            ).order_by("first_seen")
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0].new_count, rows[0].existing_count), (1, 0))
        self.assertEqual((rows[1].new_count, rows[1].existing_count), (0, 1))
        self.assertGreater(rows[1].last_seen, rows[1].first_seen)
        self.assertFalse(rows[1].is_error)

    def test_run_discover_records_provider_error(self):
        class BoomProvider(FakeProvider):
            def discover(self):
                raise RuntimeError("boom")

        self.run_with(BoomProvider(GameSource.SourceType.QSP, []))

        row = SourceDiscoveryStatus.objects.get()
        self.assertTrue(row.is_error)
        self.assertEqual(row.error_message, "boom")


class SourceDiscoveryStatusRecordTest(TestCase):
    def test_record_run_length_encodes(self):
        t0, t1, t2 = (now() for _ in range(3))
        kwargs = dict(is_error=False, error_message=None, new=1, existing=2)

        first = SourceDiscoveryStatus.record(
            GameSource.SourceType.APERO, ts=t0, missing=3, **kwargs
        )
        same = SourceDiscoveryStatus.record(
            GameSource.SourceType.APERO, ts=t1, missing=3, **kwargs
        )
        changed = SourceDiscoveryStatus.record(
            GameSource.SourceType.APERO, ts=t2, missing=4, **kwargs
        )

        self.assertEqual(same.pk, first.pk)
        self.assertEqual(same.last_seen, t1)
        self.assertEqual(same.first_seen, t0)
        self.assertNotEqual(changed.pk, first.pk)
        self.assertEqual(SourceDiscoveryStatus.objects.count(), 2)

    def test_sources_command_prints_counts_without_verbose(self):
        def fake_run_discover(types, on_provider_done=None):
            self.assertEqual(types, [GameSource.SourceType.APERO])
            on_provider_done(
                DiscoveryStats(
                    source_type=GameSource.SourceType.APERO,
                    candidates=3,
                    discovered=3,
                    existing=2,
                    new=1,
                    missing=5,
                )
            )
            return Counter({GameSource.SourceType.APERO: 1})

        stdout = StringIO()
        with patch(
            "curation.management.commands.sources.run_discover",
            fake_run_discover,
        ):
            call_command(
                "sources",
                "discover",
                "--type",
                GameSource.SourceType.APERO,
                stdout=stdout,
            )

        output = stdout.getvalue()
        self.assertIn(
            "sources [APERO]: 3 discovered, 2 existing, 1 new, 5 missing",
            output,
        )
        self.assertNotIn("candidates", output)
