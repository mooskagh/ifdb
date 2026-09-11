from io import StringIO
from typing import Any, cast

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from curation.manual import store_manual_add, store_manual_edit
from curation.manual_reconcile import _apply_game_info
from curation.merge import merge_game_into_game
from curation.models import GameCuration
from curation.overrides import (
    apply_and_prune_overrides,
    build_initial_overrides,
    format_overrides_for_display,
    format_overrides_yaml,
    merge_overrides_dicts,
    parse_tags,
    remove_from_overrides_dict,
    serialize_tag,
    update_overrides_from_diff,
)
from curation.views import _accept_edit
from games.gameinfo import GameInfo, GameUrl, Person, Tag
from games.models import (
    URL,
    Game,
    GameRevision,
    GameTag,
    GameTagCategory,
    PersonalityAlias,
)
from moder.actions.games_action import GameCloneAction


class OverridesTest(TestCase):
    user: Any
    tag_cat: GameTagCategory
    genre_cat: GameTagCategory
    tag1: GameTag
    tag2: GameTag
    tag_genre: GameTag
    alias1: PersonalityAlias
    alias2: PersonalityAlias
    url1: URL

    @classmethod
    def setUpTestData(cls) -> None:
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())
        User = get_user_model()
        cls.user = cast(Any, User.objects).create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        cls.tag_cat = GameTagCategory.objects.get(symbolic_id="tag")
        cls.genre_cat = GameTagCategory.objects.get(symbolic_id="genre")
        cls.tag1 = GameTag.objects.create(name="tag1", category=cls.tag_cat)
        cls.tag2 = GameTag.objects.create(name="tag2", category=cls.tag_cat)
        cls.tag_genre = GameTag.objects.create(
            name="genre1", category=cls.genre_cat
        )
        cls.alias1 = PersonalityAlias.objects.create(name="Author One")
        cls.alias2 = PersonalityAlias.objects.create(name="Author Two")
        cls.url1 = URL.objects.create(
            original_url="http://example.com/play",
            creation_date=timezone.now(),
        )

    def _create_game_and_curation(
        self, title: str = "Test Game"
    ) -> tuple[Game, GameCuration]:
        game = Game.objects.create(
            title=title,
            state=Game.State.PUBLISHED,
            creation_time=timezone.now(),
        )
        curation = GameCuration.objects.create(game=game)
        info = GameInfo(name=title)
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

    def test_serialize_and_parse_tags(self) -> None:
        t_slug = Tag("os", "os_win", None, None)
        self.assertEqual(serialize_tag(t_slug), "os_win")

        t_id = Tag("tag", None, self.tag1.id, None)
        self.assertEqual(serialize_tag(t_id), ["tag", self.tag1.id])

        t_text = Tag("tag", None, None, "custom")
        self.assertEqual(serialize_tag(t_text), ["tag", "custom"])

        parsed = parse_tags([
            "os_win",
            ["tag", self.tag1.id],
            ["tag", "custom"],
        ])
        self.assertEqual(len(parsed), 3)

    def test_apply_and_prune_overrides_tags(self) -> None:
        _, curation = self._create_game_and_curation()
        # Sources provide tag1
        sources_info = GameInfo(tags=[Tag("tag", None, self.tag1.id, None)])
        # Curation has tag1 and tag2 in include_overrides,
        # and tag_genre in exclude_overrides
        curation.include_overrides = {
            "tags": [["tag", self.tag1.id], ["tag", self.tag2.id]]
        }
        # tag_genre is in exclude, but NOT in sources -> should be pruned
        curation.exclude_overrides = {"tags": [["genre", self.tag_genre.id]]}

        updated, changed = apply_and_prune_overrides(curation, sources_info)
        self.assertTrue(changed)
        # tag1 was already in sources -> pruned from include_overrides
        # tag2 was not in sources -> kept in include_overrides and appended
        self.assertEqual(
            curation.include_overrides.get("tags"), [["tag", self.tag2.id]]
        )
        # tag_genre was not in sources -> pruned from exclude_overrides
        self.assertNotIn("tags", curation.exclude_overrides)
        # Result tags have tag1 and tag2
        result_tag_ids = {t.tag_id for t in updated.tags}
        self.assertEqual(result_tag_ids, {self.tag1.id, self.tag2.id})

    def test_apply_and_prune_overrides_exclude_active(self) -> None:
        _, curation = self._create_game_and_curation()
        # Sources provide tag1 and tag2
        sources_info = GameInfo(
            tags=[
                Tag("tag", None, self.tag1.id, None),
                Tag("tag", None, self.tag2.id, None),
            ]
        )
        # Exclude tag1
        curation.include_overrides = {}
        curation.exclude_overrides = {"tags": [["tag", self.tag1.id]]}

        updated, changed = apply_and_prune_overrides(curation, sources_info)
        # tag1 was in sources -> kept in exclude, stripped from sources
        self.assertEqual(
            curation.exclude_overrides.get("tags"), [["tag", self.tag1.id]]
        )
        result_tag_ids = {t.tag_id for t in updated.tags}
        self.assertEqual(result_tag_ids, {self.tag2.id})

    def test_update_overrides_from_diff(self) -> None:
        _, curation = self._create_game_and_curation()
        before = GameInfo(
            tags=[Tag("tag", None, self.tag1.id, None)],
            personalities={"author": [Person(self.alias1.id, "")]},
            urls=[GameUrl("play_online", self.url1.id, "Play", None)],
        )
        after = GameInfo(
            tags=[Tag("tag", None, self.tag2.id, None)],
            personalities={"author": [Person(self.alias2.id, "")]},
            urls=[],
        )

        changed = update_overrides_from_diff(curation, before, after)
        self.assertTrue(changed)

        # Added elements should be in include_overrides
        self.assertEqual(
            curation.include_overrides.get("tags"), [["tag", self.tag2.id]]
        )
        self.assertEqual(
            curation.include_overrides.get("personalities"),
            {"author": [self.alias2.id]},
        )
        self.assertNotIn("urls", curation.include_overrides)

        # Removed elements should be in exclude_overrides
        self.assertEqual(
            curation.exclude_overrides.get("tags"), [["tag", self.tag1.id]]
        )
        self.assertEqual(
            curation.exclude_overrides.get("personalities"),
            {"author": [self.alias1.id]},
        )
        self.assertEqual(
            curation.exclude_overrides.get("urls"),
            [["play_online", "Play", self.url1.id]],
        )

    def test_build_initial_overrides_rich_vs_non_rich(self) -> None:
        info = GameInfo(
            tags=[
                Tag("tag", None, self.tag1.id, None),
                Tag("language", None, None, "русский"),
            ],
            personalities={"author": [Person(self.alias1.id, "")]},
            urls=[GameUrl("play_online", self.url1.id, "Play", None)],
        )

        # Non-rich keeps everything
        non_rich = build_initial_overrides(info, is_rich_source=False)
        self.assertIn("personalities", non_rich)
        self.assertIn("tags", non_rich)
        self.assertEqual(len(non_rich["tags"]), 2)
        self.assertIn("urls", non_rich)

        # Rich source drops personalities and language
        rich = build_initial_overrides(info, is_rich_source=True)
        self.assertNotIn("personalities", rich)
        self.assertIn("tags", rich)
        self.assertEqual(len(rich["tags"]), 1)
        self.assertEqual(rich["tags"][0], ["tag", self.tag1.id])
        self.assertIn("urls", rich)

    def test_store_manual_edit_updates_overrides(self) -> None:
        game, curation = self._create_game_and_curation()
        # Moderator edit adding tag1 and author
        data = {
            "game_id": game.pk,
            "title": game.title,
            "tags": [["tag", "tag1"]],
            "authors": [["author", "Author One"]],
            "links": [],
        }
        store_manual_edit(game, data, self.user, apply=True)
        curation.refresh_from_db()

        self.assertIn("tags", curation.include_overrides)
        self.assertIn("personalities", curation.include_overrides)

        # Now moderator removes tag1
        data2 = {
            "game_id": game.pk,
            "title": game.title,
            "tags": [],
            "authors": [["author", "Author One"]],
            "links": [],
        }
        store_manual_edit(game, data2, self.user, apply=True)
        curation.refresh_from_db()

        # tag1 should now be in exclude_overrides
        # and removed from include_overrides
        self.assertNotIn("tags", curation.include_overrides)
        self.assertIn("tags", curation.exclude_overrides)

    def test_store_manual_add_initializes_overrides(self) -> None:
        data = {
            "title": "Fresh Game",
            "tags": [["tag", "tag1"]],
            "authors": [["author", "Author One"]],
            "links": [],
        }
        rev = store_manual_add(data, self.user, apply=True)
        curation = rev.game.curation
        self.assertIn("tags", curation.include_overrides)
        self.assertIn("personalities", curation.include_overrides)

    def test_accept_proposed_edit_updates_overrides(self) -> None:
        game, curation = self._create_game_and_curation()
        # User proposes edit adding tag1
        data = {
            "game_id": game.pk,
            "title": game.title,
            "tags": [["tag", "tag1"]],
            "authors": [],
            "links": [],
        }
        proposed_rev = store_manual_edit(game, data, self.user, apply=False)
        curation.refresh_from_db()
        # Not updated while proposed
        self.assertEqual(curation.include_overrides, {})

        # Accept proposed edit
        _accept_edit(proposed_rev, curation, "", self.user)
        curation.refresh_from_db()
        self.assertIn("tags", curation.include_overrides)

    def test_format_overrides_for_display(self) -> None:
        overrides = {
            "tags": [["tag", self.tag1.id]],
            "personalities": {"author": [self.alias1.id]},
            "urls": [["play_online", "Play", self.url1.id]],
        }
        display = format_overrides_for_display(overrides)
        self.assertTrue(display.has_content)
        self.assertEqual(len(display.tags), 1)
        self.assertEqual(display.tags[0].name, "tag1")
        self.assertEqual(len(display.personalities), 1)
        self.assertEqual(display.personalities[0].name, "Author One")
        self.assertEqual(len(display.urls), 1)
        self.assertEqual(display.urls[0].url, "http://example.com/play")

    def test_format_overrides_yaml(self) -> None:
        overrides = {
            "tags": [["tag", self.tag1.id]],
            "personalities": {"author": [self.alias1.id]},
            "urls": [["play_online", "Play", self.url1.id]],
        }
        yaml_text = format_overrides_yaml(overrides)
        self.assertIn("personalities:", yaml_text)
        self.assertIn("author:", yaml_text)
        self.assertIn(f'- {self.alias1.id}  # "Author One"', yaml_text)
        self.assertIn("tags:", yaml_text)
        self.assertIn(f'- ["tag", {self.tag1.id}]  # "tag1"', yaml_text)
        self.assertIn("urls:", yaml_text)
        self.assertIn("http://example.com/play", yaml_text)

    def test_curation_history_detail_renders_overrides(self) -> None:
        game, curation = self._create_game_and_curation()
        curation.include_overrides = {"tags": [["tag", self.tag1.id]]}
        curation.exclude_overrides = {"tags": [["tag", self.tag2.id]]}
        curation.save()

        self.client.force_login(self.user)
        resp = self.client.get(
            reverse("curation_history_detail", args=[game.pk])
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn("Переопределения", content)
        self.assertIn("curation-overrides-diff", content)
        self.assertIn("curation-overrides-diff-cell--exclude", content)
        self.assertIn("curation-overrides-diff-cell--include", content)
        self.assertIn("tag1", content)
        self.assertIn("tag2", content)

    def test_merge_and_remove_overrides_dicts(self) -> None:
        dict1 = {
            "tags": [["tag", self.tag1.id]],
            "personalities": {"author": [self.alias1.id]},
            "urls": [["play_online", "Play", self.url1.id]],
        }
        dict2 = {
            "tags": [["tag", self.tag1.id], ["genre", self.tag_genre.id]],
            "personalities": {"author": [self.alias2.id]},
        }
        merged = merge_overrides_dicts(dict1, dict2)
        self.assertEqual(len(merged["tags"]), 2)
        self.assertEqual(len(merged["personalities"]["author"]), 2)
        self.assertEqual(len(merged["urls"]), 1)

        to_remove = {
            "tags": [["tag", self.tag1.id]],
            "personalities": {"author": [self.alias1.id]},
        }
        cleaned = remove_from_overrides_dict(merged, to_remove)
        self.assertEqual(len(cleaned["tags"]), 1)
        self.assertEqual(cleaned["tags"][0], ["genre", self.tag_genre.id])
        self.assertEqual(cleaned["personalities"]["author"], [self.alias2.id])
        self.assertEqual(len(cleaned["urls"]), 1)

    def test_merge_game_into_game_overrides(self) -> None:
        target_game, target_curation = self._create_game_and_curation(
            "Target Game"
        )
        target_curation.include_overrides = {"tags": [["tag", self.tag1.id]]}
        target_curation.exclude_overrides = {"tags": [["tag", self.tag2.id]]}
        target_curation.save()

        source_game, source_curation = self._create_game_and_curation(
            "Source Game"
        )
        source_curation.include_overrides = {
            "tags": [["tag", self.tag2.id], ["genre", self.tag_genre.id]]
        }
        source_curation.exclude_overrides = {"tags": [["tag", self.tag1.id]]}
        source_curation.save()

        merge_game_into_game(
            target_game=target_game,
            source_game=source_game,
            actor=self.user,
            remap_contests=False,
        )

        target_curation.refresh_from_db()
        # Target's exclude for tag2 overrides source's include for tag2.
        # Target's include for tag1 overrides source's exclude for tag1.
        self.assertEqual(
            target_curation.include_overrides.get("tags"),
            [["tag", self.tag1.id], ["genre", self.tag_genre.id]],
        )
        self.assertEqual(
            target_curation.exclude_overrides.get("tags"),
            [["tag", self.tag2.id]],
        )

    def test_game_clone_action_initializes_curation_overrides(self) -> None:
        game, curation = self._create_game_and_curation("Original To Clone")
        info = GameInfo(
            name="Original To Clone",
            tags=[Tag("tag", None, self.tag1.id, None)],
            personalities={
                "author": [Person(alias_id=self.alias1.id, name="")]
            },
            urls=[GameUrl("play_online", self.url1.id, "Play", None)],
        )
        _, canonical = info.save(game)
        rev = GameRevision.objects.create(
            game=game,
            created_at=timezone.now(),
            created_by=self.user,
            origin=GameRevision.Origin.MANUAL_EDIT,
            status=GameRevision.Status.ACCEPTED,
            published_at=timezone.now(),
            published_by=self.user,
            canonical_text=canonical,
        )
        game.published_revision = rev
        game.published_revision_id = rev.pk
        game.save(update_fields=["published_revision"])

        factory = RequestFactory()
        request = factory.post(f"/moder/game/{game.id}/clone/")
        request.user = self.user

        action = GameCloneAction(request, game)
        action.DoAction("Клонировать", {}, execute=True)

        cloned = Game.objects.exclude(id=game.id).latest("id")
        self.assertTrue(hasattr(cloned, "curation"))
        self.assertEqual(cloned.curation.state, GameCuration.State.SETTLED)
        inc = cloned.curation.include_overrides
        self.assertIn(["tag", self.tag1.id], inc.get("tags", []))
        self.assertIn(
            self.alias1.id, inc.get("personalities", {}).get("author", [])
        )
        self.assertTrue(any(u[2] == self.url1.id for u in inc.get("urls", [])))

    def test_manual_reconcile_apply_game_info_updates_overrides(self) -> None:
        game, curation = self._create_game_and_curation("Reconcile Target")
        curation.include_overrides = {}
        curation.exclude_overrides = {}
        curation.save()

        # Apply edit via manual reconcile
        col = {
            "title": "Reconcile Target",
            "release_date": "",
            "tags": [[self.tag_cat.symbolic_id, self.tag1.id]],
            "authors": [["author", self.alias1.id]],
            "links": [],
            "description_attributions": [],
            "description": "Updated description",
        }
        _apply_game_info(col, game, curation, self.user)

        curation.refresh_from_db()
        self.assertIn("tags", curation.include_overrides)
        self.assertIn(
            ["tag", self.tag1.id], curation.include_overrides["tags"]
        )
        self.assertIn(
            "author", curation.include_overrides.get("personalities", {})
        )
