from typing import Any

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class GameRevisionBackfillMigrationTest(TransactionTestCase):
    migrate_from = [("curation", "0035_rename_gameedit_to_gamerevision")]
    migrate_to = [("curation", "0036_backfill_game_revisions")]

    def setUp(self) -> None:
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        self._create_old_data(apps)

    def tearDown(self) -> None:
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def _create_old_data(self, apps: Any) -> None:
        Game = apps.get_model("games", "Game")
        GameRevision = apps.get_model("curation", "GameRevision")
        GameSource = apps.get_model("curation", "GameSource")
        GameSourceFetch = apps.get_model("curation", "GameSourceFetch")
        timestamp = timezone.now()

        matching = Game.objects.create(
            title="Matching",
            description="Current description",
            creation_time=timestamp,
            state="PUBLISHED",
        )
        self.matching_id = matching.id
        GameRevision.objects.create(
            game=matching,
            created_at=timestamp,
            published_at=timestamp,
            status="APPLIED",
            origin="AUTO_IMPORT",
            canonical_text=(
                '---\n- name: "Matching"\n---\nCurrent description'
            ),
        )

        mismatched = Game.objects.create(
            title="Mismatched",
            description="Current description",
            creation_time=timestamp,
            state="PUBLISHED",
        )
        self.mismatched_id = mismatched.id
        previous = GameRevision.objects.create(
            game=mismatched,
            created_at=timestamp,
            published_at=timestamp,
            status="APPLIED",
            origin="AUTO_IMPORT",
            canonical_text='---\n- name: "Mismatched"\n---\nOld description',
        )
        source = GameSource.objects.create(
            game=mismatched,
            type="IFWIKI",
            url="https://example.com/game",
        )
        fetch = GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            canonical_text="source canonical",
            canonical_text_hash="hash",
            first_fetch=timestamp,
            last_fetch=timestamp,
        )
        previous.used_sources.add(fetch)
        self.fetch_id = fetch.id

        missing = Game.objects.create(
            title="Missing",
            creation_time=timestamp,
            state="PUBLISHED",
        )
        self.missing_id = missing.id
        Game.objects.create(
            title="Draft",
            creation_time=timestamp,
            state="DRAFT",
        )

    def test_forward_and_reverse(self) -> None:
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        GameRevision = apps.get_model("curation", "GameRevision")

        self.assertFalse(
            GameRevision.objects.filter(status="APPLIED").exists()
        )
        self.assertEqual(
            GameRevision.objects.filter(
                game_id=self.matching_id,
                status="PUBLISHED",
            ).count(),
            1,
        )

        mismatched = GameRevision.objects.get(
            game_id=self.mismatched_id,
            origin="BACKFILL",
        )
        self.assertEqual(
            mismatched.previous_canonical_text,
            '---\n- name: "Mismatched"\n---\nOld description',
        )
        self.assertEqual(
            mismatched.canonical_text,
            '---\n- name: "Mismatched"\n---\nCurrent description',
        )
        self.assertEqual(
            list(mismatched.used_sources.values_list("id", flat=True)),
            [self.fetch_id],
        )

        missing = GameRevision.objects.get(
            game_id=self.missing_id,
            origin="BACKFILL",
        )
        self.assertEqual(missing.previous_canonical_text, "")
        self.assertEqual(
            missing.canonical_text,
            '---\n- name: "Missing"\n---\n',
        )
        self.assertEqual(
            GameRevision.objects.filter(origin="BACKFILL").count(), 2
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        GameRevision = apps.get_model("curation", "GameRevision")
        self.assertFalse(
            GameRevision.objects.filter(origin="BACKFILL").exists()
        )
        self.assertEqual(
            set(GameRevision.objects.values_list("status", flat=True)),
            {"APPLIED"},
        )
