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
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
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


class MoveGameRevisionToGamesMigrationTest(TransactionTestCase):
    migrate_from = [
        ("curation", "0036_backfill_game_revisions"),
        (
            "games",
            "0026_remove_game_games_game_state_redirect_target_and_more",
        ),
    ]
    migrate_to = [
        ("curation", "0038_alter_llmtrajectory_edit_delete_gamerevision"),
        ("games", "0027_gamerevision"),
    ]

    def setUp(self) -> None:
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        self._create_old_data(apps)

    def tearDown(self) -> None:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _create_old_data(self, apps: Any) -> None:
        Game = apps.get_model("games", "Game")
        GameRevision = apps.get_model("curation", "GameRevision")
        timestamp = timezone.now()

        game = Game.objects.create(
            title="Migrated Game",
            creation_time=timestamp,
            state="PUBLISHED",
        )
        self.game_id = game.id
        self.published_rev = GameRevision.objects.create(
            game=game,
            created_at=timestamp,
            published_at=timestamp,
            status="PUBLISHED",
            origin="AUTO_IMPORT",
            canonical_text="canonical",
        )
        self.proposed_rev = GameRevision.objects.create(
            game=game,
            created_at=timestamp,
            status="PROPOSED",
            origin="AUTO_IMPORT",
            canonical_text="canonical",
        )

    def test_move_and_status_migration(self) -> None:
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps

        NewGameRevision = apps.get_model("games", "GameRevision")
        self.assertEqual(NewGameRevision.objects.count(), 2)

        published = NewGameRevision.objects.get(id=self.published_rev.id)
        self.assertEqual(published.status, "ACCEPTED")

        proposed = NewGameRevision.objects.get(id=self.proposed_rev.id)
        self.assertEqual(proposed.status, "PROPOSED")

        # Test reverse migration
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        OldGameRevision = apps.get_model("curation", "GameRevision")
        self.assertEqual(OldGameRevision.objects.count(), 2)

        rev = OldGameRevision.objects.get(id=self.published_rev.id)
        self.assertEqual(rev.status, "PUBLISHED")
