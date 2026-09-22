from django.test import TestCase
from django.utils.timezone import now

from core.models import User
from curation.manual_reconcile import (
    column_for_game,
    save_reconcile_payload,
)
from curation.models import GameCuration
from games.models import URL, Game, GameURL, GameURLCategory
from play.models import Playable
from play.services import format_pinned_url_error


class ReconcilePinnedURLTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="reconcile_curator",
            email="curator@example.com",
            password="secretpassword",
        )
        self.cat_web, _ = GameURLCategory.objects.get_or_create(
            symbolic_id="web_site",
            defaults={"title": "Web site", "order": 1},
        )
        self.cat_play, _ = GameURLCategory.objects.get_or_create(
            symbolic_id="playable_game",
            defaults={"title": "Playable game", "order": 2},
        )

    def _create_game(self, title: str = "Test Game") -> Game:
        game = Game.objects.create(
            title=title,
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        GameCuration.objects.create(
            game=game,
            state=GameCuration.State.SETTLED,
        )
        return game

    def _create_game_url(
        self,
        game: Game,
        url_str: str,
        category: GameURLCategory | None = None,
        description: str = "",
    ) -> GameURL:
        url_obj, _ = URL.objects.get_or_create(
            original_url=url_str,
            defaults={"creation_date": now()},
        )
        return GameURL.objects.create(
            game=game,
            url=url_obj,
            category=category or self.cat_play,
            description=description,
        )

    def _create_playable(
        self, game: Game, game_url: GameURL | None = None, slug: str = "play-1"
    ) -> Playable:
        return Playable.objects.create(
            game=game,
            game_url=game_url,
            slug=slug,
            template="parchment",
            template_version="1",
        )

    def test_column_for_game_includes_pinned_playables(self) -> None:
        game = self._create_game("Game 1")
        gu = self._create_game_url(game, "https://play.example.com/g1")
        playable = self._create_playable(game, gu, slug="game-one")

        col = column_for_game(game)
        self.assertEqual(len(col["links"]), 1)
        link = col["links"][0]
        self.assertEqual(link["game_url_id"], gu.id)
        self.assertEqual(link["category"], gu.category_id)
        self.assertEqual(link["url"], "https://play.example.com/g1")
        self.assertFalse(link["confirmed_move"])
        self.assertEqual(
            link["playables"],
            [{"id": playable.id, "slug": "game-one"}],
        )

    def test_reconcile_rejects_removing_pinned_url(self) -> None:
        game = self._create_game("Game 1")
        gu = self._create_game_url(game, "https://play.example.com/g1")
        self._create_playable(game, gu, slug="game-one")

        col = column_for_game(game)
        col["links"] = []  # User tries to delete the link

        with self.assertRaises(ValueError) as ctx:
            save_reconcile_payload({"columns": [col]}, self.user)
        self.assertEqual(str(ctx.exception), format_pinned_url_error(gu))

    def test_reconcile_rejects_moving_pinned_url_without_confirmation(
        self,
    ) -> None:
        game1 = self._create_game("Game 1")
        game2 = self._create_game("Game 2")
        gu = self._create_game_url(game1, "https://play.example.com/g1")
        self._create_playable(game1, gu, slug="game-one")

        col1 = column_for_game(game1)
        col2 = column_for_game(game2)

        # Move link from col1 to col2 without confirmed_move
        moved_link = col1["links"].pop(0)
        moved_link["confirmed_move"] = False
        col2["links"].append(moved_link)

        with self.assertRaises(ValueError) as ctx:
            save_reconcile_payload({"columns": [col1, col2]}, self.user)
        self.assertIn("требует подтверждения", str(ctx.exception))
        self.assertIn("game-one", str(ctx.exception))

    def test_reconcile_confirmed_move_to_existing_game(self) -> None:
        game1 = self._create_game("Game 1")
        game2 = self._create_game("Game 2")
        gu = self._create_game_url(game1, "https://play.example.com/g1")
        p1 = self._create_playable(game1, gu, slug="game-one")
        p2 = self._create_playable(game1, gu, slug="game-one-alt")

        col1 = column_for_game(game1)
        col2 = column_for_game(game2)

        moved_link = col1["links"].pop(0)
        moved_link["confirmed_move"] = True
        col2["links"].append(moved_link)

        save_reconcile_payload({"columns": [col1, col2]}, self.user)

        p1.refresh_from_db()
        p2.refresh_from_db()
        gu.refresh_from_db()

        self.assertEqual(p1.game_id, game2.id)
        self.assertEqual(p1.game_url_id, gu.id)
        self.assertEqual(p2.game_id, game2.id)
        self.assertEqual(p2.game_url_id, gu.id)
        self.assertEqual(gu.game_id, game2.id)

        self.assertFalse(game1.gameurl_set.exists())
        self.assertFalse(game1.playable_set.exists())
        self.assertEqual(game2.gameurl_set.count(), 1)
        self.assertEqual(game2.playable_set.count(), 2)

    def test_reconcile_confirmed_move_to_new_game(self) -> None:
        game1 = self._create_game("Game 1")
        gu = self._create_game_url(game1, "https://play.example.com/g1")
        p1 = self._create_playable(game1, gu, slug="game-one")

        col1 = column_for_game(game1)
        moved_link = col1["links"].pop(0)
        moved_link["confirmed_move"] = True

        new_col = {
            "client_id": "new-column-1",
            "history_id": None,
            "game_id": None,
            "title": "Brand New Game",
            "release_date": "",
            "tags": [],
            "authors": [],
            "links": [moved_link],
            "description_attributions": [],
            "description": "",
            "sources": [],
            "delete": False,
            "clear_overrides": False,
        }

        save_reconcile_payload({"columns": [col1, new_col]}, self.user)

        new_game = Game.objects.get(title="Brand New Game")
        p1.refresh_from_db()
        gu.refresh_from_db()

        self.assertEqual(p1.game_id, new_game.id)
        self.assertEqual(p1.game_url_id, gu.id)
        self.assertEqual(gu.game_id, new_game.id)
        self.assertFalse(game1.gameurl_set.exists())
        self.assertFalse(game1.playable_set.exists())

    def test_reconcile_legacy_tuple_retains_pinned_url_in_same_game(
        self,
    ) -> None:
        game = self._create_game("Game 1")
        gu = self._create_game_url(game, "https://play.example.com/g1")
        p = self._create_playable(game, gu, slug="game-one")

        col = column_for_game(game)
        # Supply legacy tuple format
        col["links"] = [
            [gu.category_id, "Description", "https://play.example.com/g1"]
        ]

        save_reconcile_payload({"columns": [col]}, self.user)

        p.refresh_from_db()
        gu.refresh_from_db()
        self.assertEqual(p.game_id, game.id)
        self.assertEqual(p.game_url_id, gu.id)
        self.assertEqual(gu.game_id, game.id)
        self.assertEqual(gu.description, "Description")

    def test_reconcile_legacy_tuple_cannot_move_pinned_url(self) -> None:
        game1 = self._create_game("Game 1")
        game2 = self._create_game("Game 2")
        gu = self._create_game_url(game1, "https://play.example.com/g1")
        self._create_playable(game1, gu, slug="game-one")

        col1 = column_for_game(game1)
        col2 = column_for_game(game2)

        col1["links"] = []
        col2["links"] = [
            [gu.category_id, "Description", "https://play.example.com/g1"]
        ]

        with self.assertRaises(ValueError) as ctx:
            save_reconcile_payload({"columns": [col1, col2]}, self.user)
        self.assertEqual(str(ctx.exception), format_pinned_url_error(gu))

    def test_reconcile_deleting_game_with_pinned_url_moved_succeeds(
        self,
    ) -> None:
        game1 = self._create_game("Game 1")
        game2 = self._create_game("Game 2")
        gu = self._create_game_url(game1, "https://play.example.com/g1")
        p = self._create_playable(game1, gu, slug="game-one")

        col1 = column_for_game(game1)
        col2 = column_for_game(game2)

        col1["delete"] = True
        moved_link = col1["links"].pop(0)
        moved_link["confirmed_move"] = True
        col2["links"].append(moved_link)

        save_reconcile_payload({"columns": [col1, col2]}, self.user)

        p.refresh_from_db()
        gu.refresh_from_db()
        game1.refresh_from_db()

        self.assertEqual(p.game_id, game2.id)
        self.assertEqual(gu.game_id, game2.id)
        self.assertEqual(game1.state, Game.State.ABANDONED)

    def test_reconcile_deleting_game_with_unmoved_playable_fails(self) -> None:
        game1 = self._create_game("Game 1")
        gu = self._create_game_url(game1, "https://play.example.com/g1")
        self._create_playable(game1, gu, slug="game-one")

        col1 = column_for_game(game1)
        col1["delete"] = True

        with self.assertRaises(ValueError) as ctx:
            save_reconcile_payload({"columns": [col1]}, self.user)
        self.assertEqual(str(ctx.exception), format_pinned_url_error(gu))

        # Also test unlinked Playable (game_url is None)
        game2 = self._create_game("Game 2")
        self._create_playable(game2, game_url=None, slug="unlinked-play")
        col2 = column_for_game(game2)
        col2["delete"] = True

        with self.assertRaises(ValueError) as ctx:
            save_reconcile_payload({"columns": [col2]}, self.user)
        self.assertIn("Playables", str(ctx.exception))

    def test_reconcile_confirmed_move_when_destination_has_duplicate_url(
        self,
    ) -> None:
        game1 = self._create_game("Game 1")
        game2 = self._create_game("Game 2")
        gu1 = self._create_game_url(game1, "https://play.example.com/shared")
        gu2 = self._create_game_url(game2, "https://play.example.com/shared")
        p1 = self._create_playable(game1, gu1, slug="game-one")

        col1 = column_for_game(game1)
        col2 = column_for_game(game2)

        # Move gu1 to col2 with confirmation
        moved_link = col1["links"].pop(0)
        moved_link["confirmed_move"] = True
        col2["links"].append(moved_link)

        save_reconcile_payload({"columns": [col1, col2]}, self.user)

        p1.refresh_from_db()
        gu2.refresh_from_db()

        self.assertEqual(p1.game_id, game2.id)
        self.assertEqual(p1.game_url_id, gu2.id)
        self.assertFalse(GameURL.objects.filter(pk=gu1.id).exists())
        self.assertEqual(game2.gameurl_set.count(), 1)
