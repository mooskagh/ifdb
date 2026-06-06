from collections import Counter
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils.timezone import now

from .discovery import DiscoveryStats, run_discover
from .edit import EditStats
from .fetch import FetchStats
from .gameinfo import GameInfo
from .models import GameHistory, GameSource, SourceDiscoveryStatus
from .providers import (
    DiscoveredSource,
    GameSourceProvider,
    IfictionProvider,
    QspSuProvider,
)
from .reconcile import ReconcileStats
from .tasks import discover_sources


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

    def test_run_discover_handles_duplicate_existing_sources(self):
        history = GameHistory.objects.create(creation_time=now())
        used_dup = GameSource.objects.create(
            type=GameSource.SourceType.INSTEAD,
            url="http://example.com/dup",
            history=history,
            created_at=now(),
        )
        unused_dup = GameSource.objects.create(
            type=GameSource.SourceType.INSTEAD,
            url="http://example.com/dup",
            created_at=now(),
        )
        provider = FakeProvider(
            GameSource.SourceType.INSTEAD,
            ["http://example.com/dup", "http://example.com/new"],
        )
        stats = []

        with patch("curation.discovery.REGISTERED_PROVIDERS", [provider]):
            counts = run_discover(on_provider_done=stats.append)

        self.assertEqual(counts, Counter({GameSource.SourceType.INSTEAD: 1}))
        # Both duplicate rows match -> two existing ids, one new orphan.
        self.assertEqual(
            (len(stats[0].existing_ids), len(stats[0].new_ids)), (2, 1)
        )
        new_source = GameSource.objects.get(url="http://example.com/new")
        self.assertEqual(
            stats[0].duplicate_id_clusters, [[used_dup.id, unused_dup.id]]
        )
        self.assertEqual(stats[0].unused_ids, [unused_dup.id, new_source.id])
        self.assertEqual(
            GameSource.objects.filter(
                type=GameSource.SourceType.INSTEAD,
                url="http://example.com/dup",
            ).count(),
            2,
        )
        self.assertEqual(
            GameSource.objects.filter(
                type=GameSource.SourceType.INSTEAD,
                url="http://example.com/new",
                history__isnull=True,
            ).count(),
            1,
        )

    def test_run_discover_matches_across_scheme(self):
        GameSource.objects.create(
            type=GameSource.SourceType.INSTEAD,
            url="http://example.com/x",
            created_at=now(),
        )
        provider = FakeProvider(
            GameSource.SourceType.INSTEAD,
            ["https://example.com/x", "https://example.com/new"],
        )
        stats = []

        with patch("curation.discovery.REGISTERED_PROVIDERS", [provider]):
            run_discover(on_provider_done=stats.append)

        self.assertEqual(
            (
                len(stats[0].existing_ids),
                len(stats[0].new_ids),
                len(stats[0].absent_ids),
            ),
            (1, 1, 0),
        )
        self.assertEqual(
            GameSource.objects.filter(
                type=GameSource.SourceType.INSTEAD,
                url__contains="example.com/x",
            ).count(),
            1,
        )

    def test_run_discover_matches_trailing_slash(self):
        GameSource.objects.create(
            type=GameSource.SourceType.QUESTBOOK,
            url="http://example.com/g/",
            created_at=now(),
        )
        provider = FakeProvider(
            GameSource.SourceType.QUESTBOOK, ["http://example.com/g"]
        )
        stats = []

        with patch("curation.discovery.REGISTERED_PROVIDERS", [provider]):
            run_discover(on_provider_done=stats.append)

        self.assertEqual(
            (
                len(stats[0].existing_ids),
                len(stats[0].new_ids),
                len(stats[0].absent_ids),
            ),
            (1, 0, 0),
        )
        self.assertEqual(GameSource.objects.count(), 1)

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
        existing_row = GameSource.objects.create(
            type=GameSource.SourceType.APERO,
            url="http://example.com/existing",
            created_at=now(),
        )
        missing_row = GameSource.objects.create(
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

        self.assertEqual(len(stats), 1)
        stat = stats[0]
        self.assertEqual(stat.source_type, GameSource.SourceType.APERO)
        self.assertEqual((stat.candidates, stat.discovered), (3, 2))
        self.assertEqual(len(stat.new_ids), 1)
        self.assertEqual(stat.existing_ids, [existing_row.id])
        self.assertEqual(stat.absent_ids, [])
        self.assertEqual(stat.newly_missing_ids, [missing_row.id])

    def test_run_discover_flags_newly_missing_then_absent(self):
        row = GameSource.objects.create(
            type=GameSource.SourceType.APERO,
            url="http://example.com/gone",
            created_at=now(),
        )
        provider = FakeProvider(GameSource.SourceType.APERO, [])
        stats = []

        with patch("curation.discovery.REGISTERED_PROVIDERS", [provider]):
            run_discover(on_provider_done=stats.append)
        self.assertEqual(stats[0].absent_ids, [])
        self.assertEqual(stats[0].newly_missing_ids, [row.id])
        row.refresh_from_db()
        self.assertIsNotNone(row.missing_since)
        first_missing_since = row.missing_since

        with patch("curation.discovery.REGISTERED_PROVIDERS", [provider]):
            run_discover(on_provider_done=stats.append)
        self.assertEqual(stats[1].absent_ids, [row.id])
        self.assertEqual(stats[1].newly_missing_ids, [])
        row.refresh_from_db()
        self.assertEqual(row.missing_since, first_missing_since)

    def test_run_discover_clears_missing_since_on_rediscovery(self):
        row = GameSource.objects.create(
            type=GameSource.SourceType.INSTEAD,
            url="http://example.com/back",
            created_at=now(),
            missing_since=now(),
        )
        provider = FakeProvider(
            GameSource.SourceType.INSTEAD, ["https://example.com/back"]
        )
        stats = []

        with patch("curation.discovery.REGISTERED_PROVIDERS", [provider]):
            run_discover(on_provider_done=stats.append)

        self.assertEqual(stats[0].existing_ids, [row.id])
        self.assertEqual(stats[0].absent_ids, [])
        row.refresh_from_db()
        self.assertIsNone(row.missing_since)

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
        self.assertEqual(
            (len(rows[0].new_ids), len(rows[0].existing_ids)), (1, 0)
        )
        self.assertEqual(
            (len(rows[1].new_ids), len(rows[1].existing_ids)), (0, 1)
        )
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


class SourceKeyTest(TestCase):
    def test_ifiction_ignores_lid_param(self):
        provider = IfictionProvider()
        self.assertEqual(
            provider.source_key("http://ifiction.ru/g?id=2766&lid=14"),
            provider.source_key("https://ifiction.ru/g?id=2766"),
        )

    def test_qsp_keys_on_sobi2id_only(self):
        provider = QspSuProvider()
        a = "http://qsp.su/index.php?option=com_sobi2&catid=0&sobi2Id=42&Itemid=55"
        b = "http://qsp.su/index.php?option=com_sobi2&sobi2Id=42&catid=7"
        self.assertEqual(provider.source_key(a), provider.source_key(b))
        self.assertEqual(provider.source_key(a), "qsp:sobi2id=42")


class SourceDiscoveryStatusRecordTest(TestCase):
    def test_record_run_length_encodes(self):
        t0, t1, t2 = (now() for _ in range(3))
        kwargs = dict(
            is_error=False,
            error_message=None,
            new_ids=[1],
            existing_ids=[2, 3],
            newly_missing_ids=[],
            unused_ids=[7],
            duplicate_id_clusters=[[8, 9]],
        )

        first = SourceDiscoveryStatus.record(
            GameSource.SourceType.APERO, ts=t0, absent_ids=[4, 5], **kwargs
        )
        same = SourceDiscoveryStatus.record(
            GameSource.SourceType.APERO, ts=t1, absent_ids=[4, 5], **kwargs
        )
        changed = SourceDiscoveryStatus.record(
            GameSource.SourceType.APERO, ts=t2, absent_ids=[4, 5, 6], **kwargs
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
                    new_ids=[1],
                    existing_ids=[2, 3],
                    newly_missing_ids=[4, 5],
                    absent_ids=[6, 7, 8],
                    unused_ids=[1],
                    duplicate_id_clusters=[[2, 3], [6, 7, 8]],
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
            "sources [APERO]: 3 discovered, 2 existing, 1 new, "
            "2 newly missing, 3 absent, 1 unused, 2 duplicate clusters",
            output,
        )
        self.assertNotIn("candidates", output)


class DiscoverSourcesTaskTest(TestCase):
    def test_auto_import_fetches_reconciles_and_edits_new_orphans(self):
        calls = []
        orphan_history = GameHistory(pk=51, game=None)

        def fake_run_discover(types, on_provider_done=None):
            self.assertEqual(types, [GameSource.SourceType.APERO])
            on_provider_done(
                DiscoveryStats(
                    source_type=GameSource.SourceType.APERO,
                    candidates=2,
                    discovered=2,
                    new_ids=[11, 12],
                    existing_ids=[],
                    absent_ids=[],
                    newly_missing_ids=[],
                    unused_ids=[11, 12],
                    duplicate_id_clusters=[],
                )
            )
            return Counter({GameSource.SourceType.APERO: 2})

        def fake_run_fetch(source_id):
            calls.append(("fetch", source_id))
            return [FetchStats(GameSource.SourceType.APERO, 1, 1, 0, 1, 0)]

        def fake_run_reconcile(source_id, on_source_done=None):
            calls.append(("reconcile", source_id))
            on_source_done(
                GameSource(pk=source_id, type=GameSource.SourceType.APERO),
                "spawned",
                orphan_history,
            )
            return [ReconcileStats(GameSource.SourceType.APERO, 1, 0, 0, 1, 0)]

        def fake_run_edit(history_id, pipeline_id):
            calls.append(("edit", history_id, pipeline_id))
            return EditStats(1, 0, 0, 1, 0, 0, 0)

        with (
            patch("curation.tasks.run_discover", fake_run_discover),
            patch("curation.tasks.run_fetch", fake_run_fetch),
            patch("curation.tasks.run_reconcile", fake_run_reconcile),
            patch("curation.tasks.run_edit", fake_run_edit),
        ):
            result = discover_sources(
                types=[GameSource.SourceType.APERO],
                auto_import_new=True,
                pipeline_id=7,
            )

        self.assertEqual(
            calls,
            [
                ("fetch", 11),
                ("fetch", 12),
                ("reconcile", 11),
                ("reconcile", 12),
                ("edit", 51, 7),
            ],
        )
        self.assertEqual(
            result["discovered"], {GameSource.SourceType.APERO: 2}
        )
        self.assertEqual(result["auto_import_new"]["source_ids"], [11, 12])

    def test_auto_import_skips_pipeline_when_no_new_sources(self):
        def fake_run_discover(types, on_provider_done=None):
            on_provider_done(
                DiscoveryStats(
                    source_type=GameSource.SourceType.APERO,
                    candidates=1,
                    discovered=1,
                    new_ids=[],
                    existing_ids=[11],
                    absent_ids=[],
                    newly_missing_ids=[],
                    unused_ids=[],
                    duplicate_id_clusters=[],
                )
            )
            return Counter()

        with (
            patch("curation.tasks.run_discover", fake_run_discover),
            patch("curation.tasks.run_fetch") as run_fetch,
            patch("curation.tasks.run_reconcile") as run_reconcile,
            patch("curation.tasks.run_edit") as run_edit,
        ):
            result = discover_sources(auto_import_new=True, pipeline_id=7)

        self.assertEqual(result, {"discovered": {}, "auto_import_new": None})
        run_fetch.assert_not_called()
        run_reconcile.assert_not_called()
        run_edit.assert_not_called()
