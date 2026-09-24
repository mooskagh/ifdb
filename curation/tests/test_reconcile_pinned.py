from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now

from core.models import User
from curation.manual_reconcile import column_for_game, save_reconcile_payload
from curation.models import GameCuration
from games.models import (
    URL,
    Game,
    GameTag,
    GameTagCategory,
    GameURL,
    GameURLCategory,
)
from play.models import Playable
from play.services import format_pinned_url_error


class ReconcilePinnedURLTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="reconcile_curator",
            email="curator@example.com",
            password="secretpassword",
        )
        self.cat = GameURLCategory.objects.create(
            symbolic_id="playable_game", title="Playable game"
        )
        self.game1 = Game.objects.create(
            title="Game 1", state=Game.State.PUBLISHED, creation_time=now()
        )
        self.game2 = Game.objects.create(
            title="Game 2", state=Game.State.PUBLISHED, creation_time=now()
        )
        GameCuration.objects.create(
            game=self.game1, state=GameCuration.State.SETTLED
        )
        GameCuration.objects.create(
            game=self.game2, state=GameCuration.State.SETTLED
        )

        u1 = URL.objects.create(
            original_url="https://play.example.com/g1", creation_date=now()
        )
        self.gu1 = GameURL.objects.create(
            game=self.game1, category=self.cat, url=u1
        )
        self.p1 = Playable.objects.create(
            game=self.game1,
            game_url=self.gu1,
            slug="game-one",
            template="p",
            template_version="1",
        )

    def test_column_for_game_and_delete_rejection(self) -> None:
        col = column_for_game(self.game1)
        link = col["links"][0]
        self.assertEqual(link["game_url_id"], self.gu1.id)
        self.assertEqual(
            link["playables"], [{"id": self.p1.id, "slug": "game-one"}]
        )

        # Deleting the link must fail
        col["links"] = []
        with self.assertRaises(ValueError) as ctx:
            save_reconcile_payload({"columns": [col]}, self.user)
        self.assertEqual(str(ctx.exception), format_pinned_url_error(self.gu1))

    def test_reconcile_moves_pinned_url_with_confirmation(self) -> None:
        col1 = column_for_game(self.game1)
        col2 = column_for_game(self.game2)
        moved_link = col1["links"].pop(0)

        # Unconfirmed move fails
        moved_link["confirmed_move"] = False
        col2["links"].append(moved_link)
        with self.assertRaises(ValueError) as ctx:
            save_reconcile_payload({"columns": [col1, col2]}, self.user)
        self.assertIn("требует подтверждения", str(ctx.exception))

        # Confirmed move succeeds
        moved_link["confirmed_move"] = True
        save_reconcile_payload({"columns": [col1, col2]}, self.user)
        self.p1.refresh_from_db()
        self.gu1.refresh_from_db()
        self.assertEqual(self.p1.game_id, self.game2.id)
        self.assertEqual(self.gu1.game_id, self.game2.id)

    def test_reconcile_legacy_tuple_payload(self) -> None:
        # Same game retains pinned URL
        col = column_for_game(self.game1)
        col["links"] = [
            [self.gu1.category_id, "", "https://play.example.com/g1"]
        ]
        save_reconcile_payload({"columns": [col]}, self.user)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.game_id, self.game1.id)

        # Moving to another game via legacy tuple is not authorized
        col1 = column_for_game(self.game1)
        col2 = column_for_game(self.game2)
        col1["links"] = []
        col2["links"] = [
            [self.gu1.category_id, "", "https://play.example.com/g1"]
        ]
        with self.assertRaises(ValueError) as ctx:
            save_reconcile_payload({"columns": [col1, col2]}, self.user)
        self.assertEqual(str(ctx.exception), format_pinned_url_error(self.gu1))

    def test_reconcile_game_deletion_requires_moving_playables(self) -> None:
        col1 = column_for_game(self.game1)
        col1["delete"] = True
        with self.assertRaises(ValueError):
            save_reconcile_payload({"columns": [col1]}, self.user)

    def test_reconcile_ignores_blank_tags(self) -> None:
        cat = GameTagCategory.objects.create(
            symbolic_id="genre_cat", name="Жанр", allow_new_tags=False
        )
        col = column_for_game(self.game1)
        col["tags"] = [[cat.id, ""], [cat.id, "   "]]
        save_reconcile_payload({"columns": [col]}, self.user)
        self.game1.refresh_from_db()
        self.assertEqual(self.game1.tags.count(), 0)

    def test_reconcile_restricted_tag_not_found_raises_value_error(
        self,
    ) -> None:
        cat = GameTagCategory.objects.create(
            symbolic_id="genre_cat2", name="Жанр", allow_new_tags=False
        )
        col = column_for_game(self.game1)
        col["tags"] = [[cat.id, "Несуществующий жанр"]]
        with self.assertRaises(ValueError) as ctx:
            save_reconcile_payload({"columns": [col]}, self.user)
        self.assertIn("Несуществующий жанр", str(ctx.exception))
        self.assertIn("не найден в категории", str(ctx.exception))

    def test_reconcile_restricted_tag_exact_match(self) -> None:
        cat = GameTagCategory.objects.create(
            symbolic_id="genre_cat3", name="Жанр", allow_new_tags=False
        )
        tag = GameTag.objects.create(
            category=cat, name="Детектив", symbolic_id="g_detective"
        )
        col = column_for_game(self.game1)
        col["tags"] = [[cat.id, "Детектив"]]
        save_reconcile_payload({"columns": [col]}, self.user)
        self.game1.refresh_from_db()
        self.assertIn(tag, self.game1.tags.all())

        # Non-matching case raises ValueError
        col["tags"] = [[cat.id, "детектив"]]
        with self.assertRaises(ValueError):
            save_reconcile_payload({"columns": [col]}, self.user)

    def test_reconcile_view_returns_400_json_on_value_error(self) -> None:
        cat = GameTagCategory.objects.create(
            symbolic_id="genre_cat4", name="Жанр", allow_new_tags=False
        )
        col = column_for_game(self.game1)
        col["tags"] = [[cat.id, "Несуществующий жанр"]]
        self.client.force_login(self.user)
        url = reverse("curation_history_reconcile", args=[self.game1.id])
        resp = self.client.post(
            url,
            data={"columns": [col]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())
        self.assertIn("Несуществующий жанр", resp.json()["error"])
