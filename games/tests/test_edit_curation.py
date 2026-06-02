import json
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now

from curation.models import GameEdit, GameHistory
from games.models import Game, GameAuthor, GameAuthorRole, PersonalityAlias


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

    def test_game_page_renders_unlinked_author_alias(self):
        game = Game.objects.create(title="Old Title", creation_time=now())
        role = GameAuthorRole.objects.get(symbolic_id="author")
        alias = PersonalityAlias.objects.create(name="Unlinked Author")
        GameAuthor.objects.create(game=game, role=role, author=alias)

        response = self.client.get(reverse("show_game", args=[game.id]))

        self.assertContains(response, "Unlinked Author")
