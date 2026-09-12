from io import StringIO
from typing import Any, cast

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from curation.models import (
    EditPipeline,
    GameCuration,
    GameHistoryAuditLog,
    GameSource,
    GameSourceFetch,
)
from games.gameinfo import GameInfo, GameUrl, Tag
from games.models import URL, Game, GameRevision, GameTag, GameTagCategory


class ReconcileOverridesTest(TestCase):
    user: Any
    pipeline: EditPipeline
    tag_cat: GameTagCategory
    tag1: GameTag
    tag2: GameTag

    @classmethod
    def setUpTestData(cls) -> None:
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())
        User = get_user_model()
        cls.user = cast(Any, User.objects).create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        cls.pipeline, _ = EditPipeline.objects.update_or_create(
            name="Test Pipeline",
            defaults={"passes": [{"name": "merge_sources"}]},
        )
        cls.tag_cat = GameTagCategory.objects.get(symbolic_id="tag")
        cls.tag1 = GameTag.objects.create(name="tag1", category=cls.tag_cat)
        cls.tag2 = GameTag.objects.create(name="tag2", category=cls.tag_cat)

    def _create_game(
        self,
        title: str,
        tags: list[GameTag] | None = None,
        urls: list[GameUrl] | None = None,
        include_overrides: dict[str, Any] | None = None,
        state: str = GameCuration.State.SETTLED,
    ) -> tuple[Game, GameCuration]:
        game = Game.objects.create(
            title=title,
            state=Game.State.PUBLISHED,
            creation_time=timezone.now(),
        )
        curation = GameCuration.objects.create(
            game=game,
            state=state,
            include_overrides=include_overrides or {},
        )
        info = GameInfo(name=title)
        for t in tags or []:
            info.tags.append(Tag(t.category.symbolic_id, None, t.id, None))
        for u in urls or []:
            info.urls.append(u)
        _, canonical = info.save(game)
        rev = GameRevision.objects.create(
            game=game,
            created_at=timezone.now(),
            created_by=self.user,
            origin=GameRevision.Origin.BACKFILL,
            status=GameRevision.Status.ACCEPTED,
            published_at=timezone.now(),
            published_by=self.user,
            canonical_text=canonical,
        )
        game.published_revision = rev
        game.published_revision_id = rev.pk
        game.save(update_fields=["published_revision"])
        return game, curation

    def _add_source_fetch(self, game: Game, canonical_text: str) -> GameSource:
        source = GameSource.objects.create(
            game=game,
            type=GameSource.SourceType.IFWIKI,
            url=f"https://ifwiki.ru/{game.id}",
        )
        GameSourceFetch.objects.create(
            source=source,
            first_fetch=timezone.now(),
            last_fetch=timezone.now(),
            canonical_text=canonical_text,
            canonical_text_hash="dummy_hash",
        )
        return source

    def test_front_matter_changed_enqueues_game_for_update(self) -> None:
        game, curation = self._create_game("Original Title", tags=[self.tag1])
        # Source has tag1 AND tag2 (so front matter changes by adding tag2)
        source_canonical = f"""---
- name: "Original Title"
- tags:
  - ["tag", {self.tag1.id}]
  - ["tag", {self.tag2.id}]
---
Description"""
        self._add_source_fetch(game, source_canonical)

        out = StringIO()
        call_command("reconcile_overrides", stdout=out)

        curation.refresh_from_db()
        self.assertEqual(
            curation.state, GameCuration.State.SCHEDULED_FOR_UPDATE
        )
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=game,
                kind=GameHistoryAuditLog.AuditKind.AUTO_UPDATE_SCHEDULED,
            ).exists()
        )
        # Overrides should not have been modified on the game because
        # it was enqueued
        self.assertEqual(curation.include_overrides, {})
        self.assertIn("Enqueued:          1", out.getvalue())

    def test_front_matter_unchanged_prunes_include_overrides(self) -> None:
        # Game has tag1 and tag2.
        # include_overrides contains both tag1 and tag2.
        overrides = {
            "tags": [["tag", self.tag1.id], ["tag", self.tag2.id]],
        }
        game, curation = self._create_game(
            "Original Title",
            tags=[self.tag1, self.tag2],
            include_overrides=overrides,
        )
        # Source only has tag1.
        # With overrides applied, tag1 (from source) + tag2 (from overrides)
        # equals the served tags! Front matter doesn't change.
        # tag1 should be pruned from include_overrides because it's in source!
        source_canonical = f"""---
- name: "Original Title"
- tags:
  - ["tag", {self.tag1.id}]
---
Description"""
        self._add_source_fetch(game, source_canonical)

        rev_count_before = GameRevision.objects.filter(game=game).count()
        out = StringIO()
        call_command("reconcile_overrides", stdout=out)

        curation.refresh_from_db()
        # State remains SETTLED
        self.assertEqual(curation.state, GameCuration.State.SETTLED)
        # No edit revision was created
        self.assertEqual(
            GameRevision.objects.filter(game=game).count(), rev_count_before
        )
        # include_overrides has tag1 pruned, only tag2 remains
        self.assertEqual(
            curation.include_overrides,
            {"tags": [["tag", self.tag2.id]]},
        )
        self.assertIn("Overrides pruned:  1", out.getvalue())

    def test_no_usable_sources_skipped(self) -> None:
        overrides = {"tags": [["tag", self.tag1.id]]}
        game, curation = self._create_game(
            "Original Title",
            tags=[self.tag1],
            include_overrides=overrides,
        )
        # No sources added

        out = StringIO()
        call_command("reconcile_overrides", stdout=out)

        curation.refresh_from_db()
        self.assertEqual(curation.state, GameCuration.State.SETTLED)
        self.assertEqual(curation.include_overrides, overrides)
        self.assertIn("No usable sources: 1", out.getvalue())

    def test_dry_run_leaves_database_unmodified(self) -> None:
        overrides = {
            "tags": [["tag", self.tag1.id], ["tag", self.tag2.id]],
        }
        game, curation = self._create_game(
            "Original Title",
            tags=[self.tag1, self.tag2],
            include_overrides=overrides,
        )
        source_canonical = f"""---
- name: "Original Title"
- tags:
  - ["tag", {self.tag1.id}]
---
Description"""
        self._add_source_fetch(game, source_canonical)

        out = StringIO()
        call_command("reconcile_overrides", dry_run=True, stdout=out)

        curation.refresh_from_db()
        # Still has original unpruned overrides
        self.assertEqual(curation.include_overrides, overrides)
        self.assertIn("DRY RUN", out.getvalue())
        self.assertIn("Overrides pruned:  1", out.getvalue())

    def test_game_filter(self) -> None:
        game1, _ = self._create_game("Game 1", tags=[self.tag1])
        game2, curation2 = self._create_game("Game 2", tags=[self.tag1])
        source_canonical = f"""---
- name: "New Title"
- tags:
  - ["tag", {self.tag1.id}]
---
Description"""
        self._add_source_fetch(game1, source_canonical)
        self._add_source_fetch(game2, source_canonical)

        out = StringIO()
        call_command("reconcile_overrides", game=game1.id, stdout=out)

        self.assertIn("Inspected:         1", out.getvalue())
        curation2.refresh_from_db()
        self.assertEqual(curation2.state, GameCuration.State.SETTLED)

    def test_front_matter_unchanged_with_different_source_url_description(
        self,
    ) -> None:
        url_obj = URL.objects.create(
            original_url="https://www.youtube.com/watch?v=6EN50Fn1nWk",
            creation_date=timezone.now(),
        )
        game, curation = self._create_game(
            "Original Title",
            urls=[
                GameUrl(
                    category="video",
                    url_id=url_obj.id,
                    description="Видео прохождения",
                    url=None,
                )
            ],
            include_overrides={},
        )
        source_canonical = f"""---
- name: "Original Title"
- urls:
  - ["video", "Видео прохождения от Адженты", "{url_obj.original_url}"]
---
Description"""
        self._add_source_fetch(game, source_canonical)

        out = StringIO()
        call_command("reconcile_overrides", stdout=out)

        curation.refresh_from_db()
        self.assertEqual(curation.state, GameCuration.State.SETTLED)
        self.assertIn("Unchanged:         1", out.getvalue())
        self.assertIn("Enqueued:          0", out.getvalue())
