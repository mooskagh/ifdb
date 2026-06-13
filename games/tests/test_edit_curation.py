import json
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now

from curation.models import GameEdit, GameHistory, GameSource, GameSourceFetch
from games.models import (
    URL,
    Game,
    GameAuthor,
    GameAuthorRole,
    GameDescriptionAttribution,
    GameURL,
    GameURLCategory,
    PersonalityAlias,
)


class GameEditCurationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="user", email="user@example.com", password="pw"
        )
        self.client.force_login(self.user)

    def _payload(self, game, title="New Title"):
        return {
            "game_id": game.id,
            "title": title,
            "desc": "New description",
            "release_date": "",
            "authors": [],
            "tags": [],
            "links": [],
            "description_attributions": [],
        }

    def _add_payload(self, title="New Game"):
        data = self._payload(Game(title="", creation_time=now()), title)
        del data["game_id"]
        return data

    def test_edit_page_button_says_propose_without_edit_perm(self):
        game = Game.objects.create(
            title="Old Title",
            creation_time=now(),
            edit_perm="@admin",
        )

        response = self.client.get(reverse("edit_game", args=[game.id]))

        self.assertContains(response, "Предложить")
        self.assertNotContains(response, ">Сохранить</button>")

    def test_edit_page_button_says_save_with_edit_perm(self):
        game = Game.objects.create(title="Old Title", creation_time=now())

        response = self.client.get(reverse("edit_game", args=[game.id]))

        self.assertContains(response, "Сохранить")

    def test_store_proposes_without_edit_perm(self):
        game = Game.objects.create(
            title="Old Title",
            creation_time=now(),
            edit_perm="@admin",
        )

        self.client.post(
            reverse("store_game"),
            {"json": json.dumps(self._payload(game))},
        )

        game.refresh_from_db()
        history = GameHistory.objects.get(game=game)
        edit = GameEdit.objects.get(history=history)
        self.assertEqual(game.title, "Old Title")
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(edit.status, GameEdit.EditStatus.PROPOSED)
        self.assertEqual(edit.origin, GameEdit.Origin.USER_SUGGESTION)
        self.assertEqual(edit.proposed_by, self.user)
        self.assertIsNone(edit.approver)

    def test_store_saves_with_edit_perm(self):
        game = Game.objects.create(title="Old Title", creation_time=now())

        self.client.post(
            reverse("store_game"),
            {"json": json.dumps(self._payload(game))},
        )

        game.refresh_from_db()
        history = GameHistory.objects.get(game=game)
        edit = GameEdit.objects.get(history=history)
        self.assertEqual(game.title, "New Title")
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(edit.status, GameEdit.EditStatus.APPLIED)
        self.assertEqual(edit.origin, GameEdit.Origin.MANUAL_EDIT)
        self.assertEqual(edit.proposed_by, self.user)
        self.assertEqual(edit.approver, self.user)

    def test_add_page_button_says_propose_without_moder_perm(self):
        response = self.client.get(reverse("add_game"))

        self.assertContains(response, "Предложить")
        self.assertNotContains(response, ">Сохранить</button>")

    def test_add_page_button_says_save_with_moder_perm(self):
        self.user.groups.add(Group.objects.create(name="moder"))

        response = self.client.get(reverse("add_game"))

        self.assertContains(response, "Сохранить")

    def test_add_proposes_unlinked_history_without_moder_perm(self):
        response = self.client.post(
            reverse("store_game"),
            {"json": json.dumps(self._add_payload())},
        )

        history = GameHistory.objects.get()
        edit = GameEdit.objects.get(history=history)
        self.assertRedirects(response, reverse("list_games"))
        self.assertIsNone(history.game)
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(edit.status, GameEdit.EditStatus.PROPOSED)
        self.assertEqual(edit.origin, GameEdit.Origin.USER_SUGGESTION)
        self.assertEqual(edit.proposed_by, self.user)
        self.assertIsNone(edit.approver)
        self.assertEqual(Game.objects.count(), 0)

    def test_accepting_proposed_add_creates_game(self):
        self.client.post(
            reverse("store_game"),
            {"json": json.dumps(self._add_payload())},
        )
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        edit = GameEdit.objects.get()

        self.client.post(
            reverse("curation_edit_diff", args=[edit.pk]), {"action": "accept"}
        )

        edit.refresh_from_db()
        history = edit.history
        history.refresh_from_db()
        self.assertEqual(edit.status, GameEdit.EditStatus.APPLIED)
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertIsNotNone(history.game)
        self.assertEqual(history.game.title, "New Game")
        self.assertEqual(history.game.added_by, self.user)

    def test_applied_edit_can_be_rolled_back_to_selected_fields(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        game = Game.objects.create(
            title="New Title",
            description="New description",
            creation_time=now(),
        )
        history = GameHistory.objects.create(
            game=game,
            creation_time=now(),
            state=GameHistory.State.SETTLED,
        )
        previous = GameEdit.objects.create(
            history=history,
            proposed_at=now(),
            approved_at=now(),
            status=GameEdit.EditStatus.APPLIED,
            origin=GameEdit.Origin.MANUAL_EDIT,
            canonical_text=(
                "---\n- name: Earlier Title\n---\nEarlier description"
            ),
        )
        fetch = self._source_fetch(history)
        previous.used_sources.add(fetch)
        edit = GameEdit.objects.create(
            history=history,
            proposed_at=now(),
            approved_at=now(),
            status=GameEdit.EditStatus.APPLIED,
            origin=GameEdit.Origin.MANUAL_EDIT,
            previous_canonical_text=(
                "---\n- name: Old Title\n---\nOld description"
            ),
            canonical_text="---\n- name: New Title\n---\nNew description",
        )

        response = self.client.get(
            reverse("curation_edit_diff", args=[edit.pk])
        )

        self.assertContains(response, "откатить")
        self.assertContains(response, "edit_diff.js")
        self.assertContains(response, 'name="include_title" checked')
        self.assertContains(response, 'name="include_release_date" disabled')

        response = self.client.post(
            reverse("curation_edit_diff", args=[edit.pk]),
            {
                "action": "rollback",
                "include_title": "on",
                "include_sources": "on",
            },
        )

        new_edit = GameEdit.objects.latest("pk")
        self.assertRedirects(
            response, reverse("curation_edit_diff", args=[new_edit.pk])
        )
        self.assertEqual(new_edit.status, GameEdit.EditStatus.PROPOSED)
        self.assertEqual(new_edit.origin, GameEdit.Origin.ROLLBACK)
        self.assertEqual(new_edit.proposed_by, self.user)
        self.assertIn("Old Title", new_edit.canonical_text)
        self.assertIn("New description", new_edit.canonical_text)
        self.assertNotIn("Old description", new_edit.canonical_text)
        self.assertEqual(list(new_edit.used_sources.all()), [fetch])

    def test_rollback_description_does_not_rollback_attributions(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        attribution = GameDescriptionAttribution.objects.create(
            name="Current source"
        )
        game = Game.objects.create(
            title="Title",
            description="New description",
            creation_time=now(),
        )
        game.description_attributions.add(attribution)
        history = GameHistory.objects.create(
            game=game,
            creation_time=now(),
            state=GameHistory.State.SETTLED,
        )
        edit = GameEdit.objects.create(
            history=history,
            proposed_at=now(),
            approved_at=now(),
            status=GameEdit.EditStatus.APPLIED,
            origin=GameEdit.Origin.MANUAL_EDIT,
            previous_canonical_text="---\n- name: Title\n---\nOld description",
            canonical_text=(
                "---\n- name: Title\n- attributions:\n"
                f"  - {attribution.pk}\n---\nNew description"
            ),
        )

        response = self.client.get(
            reverse("curation_edit_diff", args=[edit.pk])
        )

        self.assertContains(response, 'name="include_description" checked')
        self.assertContains(response, 'name="include_sources" checked')

        response = self.client.post(
            reverse("curation_edit_diff", args=[edit.pk]),
            {
                "action": "rollback",
                "include_description": "on",
            },
        )

        new_edit = GameEdit.objects.latest("pk")
        self.assertRedirects(
            response, reverse("curation_edit_diff", args=[new_edit.pk])
        )
        self.assertIn("Old description", new_edit.canonical_text)
        self.assertIn("attributions", new_edit.canonical_text)
        self.assertIn(str(attribution.pk), new_edit.canonical_text)

    def test_rejected_edit_can_be_cloned_to_selected_fields(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        game = Game.objects.create(
            title="Current Title",
            description="Current description",
            creation_time=now(),
        )
        history = GameHistory.objects.create(
            game=game,
            creation_time=now(),
            state=GameHistory.State.SETTLED,
        )
        edit = GameEdit.objects.create(
            history=history,
            proposed_at=now(),
            approved_at=now(),
            status=GameEdit.EditStatus.REJECTED,
            origin=GameEdit.Origin.USER_SUGGESTION,
            canonical_text=(
                "---\n- name: Rejected Title\n---\nRejected description"
            ),
        )
        fetch = self._source_fetch(history)
        edit.used_sources.add(fetch)

        response = self.client.get(
            reverse("curation_edit_diff", args=[edit.pk])
        )

        self.assertContains(response, "применить эту правку")
        self.assertContains(response, 'name="include_description" checked')

        response = self.client.post(
            reverse("curation_edit_diff", args=[edit.pk]),
            {
                "action": "clone",
                "include_description": "on",
            },
        )

        new_edit = GameEdit.objects.latest("pk")
        self.assertRedirects(
            response, reverse("curation_edit_diff", args=[new_edit.pk])
        )
        self.assertEqual(new_edit.status, GameEdit.EditStatus.PROPOSED)
        self.assertEqual(new_edit.origin, GameEdit.Origin.REAPPLICATION)
        self.assertIn("Current Title", new_edit.canonical_text)
        self.assertIn("Rejected description", new_edit.canonical_text)
        self.assertNotIn("Rejected Title", new_edit.canonical_text)
        self.assertEqual(list(new_edit.used_sources.all()), [fetch])

    def test_add_saves_with_moder_perm(self):
        self.user.groups.add(Group.objects.create(name="moder"))

        response = self.client.post(
            reverse("store_game"),
            {"json": json.dumps(self._add_payload())},
        )

        game = Game.objects.get()
        history = GameHistory.objects.get(game=game)
        edit = GameEdit.objects.get(history=history)
        self.assertRedirects(response, reverse("show_game", args=[game.id]))
        self.assertEqual(game.title, "New Game")
        self.assertEqual(game.added_by, self.user)
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(edit.status, GameEdit.EditStatus.APPLIED)
        self.assertEqual(edit.origin, GameEdit.Origin.MANUAL_EDIT)
        self.assertEqual(edit.proposed_by, self.user)
        self.assertEqual(edit.approver, self.user)

    def _source_fetch(self, history):
        source = GameSource.objects.create(
            history=history,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/game",
            created_at=now(),
        )
        return GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash="hash",
            first_fetch=now(),
            last_fetch=now(),
        )

    def test_game_page_renders_unlinked_author_alias(self):
        game = Game.objects.create(title="Old Title", creation_time=now())
        role = GameAuthorRole.objects.get(symbolic_id="author")
        alias = PersonalityAlias.objects.create(name="Unlinked Author")
        GameAuthor.objects.create(game=game, role=role, author=alias)

        response = self.client.get(reverse("show_game", args=[game.id]))

        self.assertContains(response, "Unlinked Author")

    def test_game_page_moder_panel_links_to_curation_history(self):
        self.user.groups.add(Group.objects.create(name="gardener"))
        game = Game.objects.create(title="Old Title", creation_time=now())
        history = GameHistory.objects.create(game=game, creation_time=now())

        response = self.client.get(reverse("show_game", args=[game.id]))

        self.assertContains(response, "Огород")
        self.assertNotContains(response, "Объединить")
        self.assertContains(
            response, reverse("curation_history_detail", args=[history.pk])
        )

    def test_game_page_moder_panel_omits_curation_without_history(self):
        self.user.groups.add(Group.objects.create(name="gardener"))
        game = Game.objects.create(title="Old Title", creation_time=now())

        response = self.client.get(reverse("show_game", args=[game.id]))

        self.assertNotContains(response, "Огород")

    def test_superuser_nav_shows_needs_attention_count(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        GameHistory.objects.create(
            creation_time=now(), state=GameHistory.State.NEEDS_ATTENTION
        )
        GameHistory.objects.create(creation_time=now())

        response = self.client.get(reverse("list_games"))

        self.assertContains(
            response,
            (
                f'<a class="top-nav-attention " '
                f'href="{reverse("curation_history_list")}">ОГОРОД (1)</a>'
            ),
        )

    def test_selected_superuser_nav_keeps_normal_style_with_count(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        GameHistory.objects.create(
            creation_time=now(), state=GameHistory.State.NEEDS_ATTENTION
        )

        response = self.client.get(reverse("curation_history_list"))

        self.assertContains(
            response,
            (
                f'<a class="top-nav-attention current" '
                f'href="{reverse("curation_history_list")}">ОГОРОД (1)</a>'
            ),
        )

    def test_superuser_nav_omits_needs_attention_count_when_zero(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        GameHistory.objects.create(creation_time=now())

        response = self.client.get(reverse("list_games"))

        self.assertNotContains(response, "top-nav-attention")
        self.assertContains(response, ">ОГОРОД</a>")

    def test_non_superuser_nav_omits_needs_attention_count(self):
        self.user.groups.add(Group.objects.create(name="gardener"))
        GameHistory.objects.create(
            creation_time=now(), state=GameHistory.State.NEEDS_ATTENTION
        )

        response = self.client.get(reverse("list_games"))

        self.assertNotContains(response, "top-nav-attention")

    def test_game_page_renders_media_without_description(self):
        game = Game.objects.create(title="Old Title", creation_time=now())
        category = GameURLCategory.objects.get(symbolic_id="poster")
        url = URL.objects.create(
            original_url="https://example.com/poster.png",
            creation_date=now(),
        )
        GameURL.objects.create(game=game, category=category, url=url)

        response = self.client.get(reverse("show_game", args=[game.id]))

        self.assertEqual(response.status_code, 200)
