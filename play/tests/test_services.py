from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils.timezone import now

from games.models import URL, Game, GameURL, GameURLCategory
from play.models import Playable
from play.services import (
    format_pinned_url_error,
    get_pinned_playables,
    is_game_url_pinned,
    move_game_url,
    transfer_game_playables,
)


class PlayableServicesTest(TestCase):
    def setUp(self) -> None:
        self.game1 = Game.objects.create(
            title="Game One", state=Game.State.PUBLISHED, creation_time=now()
        )
        self.game2 = Game.objects.create(
            title="Game Two", state=Game.State.PUBLISHED, creation_time=now()
        )
        self.cat = GameURLCategory.objects.create(
            symbolic_id="download_direct", title="Direct Download"
        )
        self.url1 = URL.objects.create(
            original_url="https://example.com/file1.zip", creation_date=now()
        )
        self.game_url1 = GameURL.objects.create(
            game=self.game1, category=self.cat, url=self.url1
        )

    def test_pinned_helpers(self) -> None:
        self.assertFalse(is_game_url_pinned(self.game_url1))
        self.assertFalse(is_game_url_pinned(self.game_url1.pk))
        self.assertEqual(get_pinned_playables(self.game_url1), [])

        playable = Playable.objects.create(
            game=self.game1,
            game_url=self.game_url1,
            slug="test-slug",
            template="parchment",
            template_version="1",
        )

        self.assertTrue(is_game_url_pinned(self.game_url1))
        self.assertTrue(is_game_url_pinned(self.game_url1.pk))
        self.assertEqual(get_pinned_playables(self.game_url1), [playable])

        error_msg = format_pinned_url_error(self.game_url1)
        self.assertIn(
            "URL нельзя удалить: из него создан сайт test-slug.", error_msg
        )

        # Multiple playables
        Playable.objects.create(
            game=self.game1,
            game_url=self.game_url1,
            slug="test-slug-2",
            template="qspider",
            template_version="1",
        )
        error_msg_multi = format_pinned_url_error(self.game_url1)
        self.assertIn(
            "URL нельзя удалить: из него созданы сайты", error_msg_multi
        )
        self.assertIn("test-slug.", error_msg_multi)
        self.assertIn("test-slug-2.", error_msg_multi)

    def test_move_game_url_non_duplicate(self) -> None:
        playable = Playable.objects.create(
            game=self.game1,
            game_url=self.game_url1,
            slug="moving-slug",
            template="parchment",
            template_version="1",
        )

        res = move_game_url(self.game_url1, self.game2)
        self.assertEqual(res.pk, self.game_url1.pk)

        self.game_url1.refresh_from_db()
        playable.refresh_from_db()

        self.assertEqual(self.game_url1.game_id, self.game2.pk)
        self.assertEqual(playable.game_id, self.game2.pk)
        self.assertEqual(playable.game_url_id, self.game_url1.pk)

    def test_move_game_url_with_duplicate(self) -> None:
        dest_url = GameURL.objects.create(
            game=self.game2, category=self.cat, url=self.url1
        )
        playable = Playable.objects.create(
            game=self.game1,
            game_url=self.game_url1,
            slug="moving-slug-dup",
            template="parchment",
            template_version="1",
        )

        res = move_game_url(self.game_url1, self.game2)
        self.assertEqual(res.pk, dest_url.pk)

        self.assertFalse(GameURL.objects.filter(pk=self.game_url1.pk).exists())
        playable.refresh_from_db()
        self.assertEqual(playable.game_id, self.game2.pk)
        self.assertEqual(playable.game_url_id, dest_url.pk)

    def test_transfer_game_playables(self) -> None:
        p_with_url = Playable.objects.create(
            game=self.game1,
            game_url=self.game_url1,
            slug="p1",
            template="parchment",
            template_version="1",
        )
        p_without_url = Playable.objects.create(
            game=self.game1,
            game_url=None,
            slug="p2",
            template="parchment",
            template_version="1",
        )

        transfer_game_playables(self.game1, self.game2)

        p_with_url.refresh_from_db()
        p_without_url.refresh_from_db()
        self.game_url1.refresh_from_db()

        self.assertEqual(p_with_url.game_id, self.game2.pk)
        self.assertEqual(self.game_url1.game_id, self.game2.pk)
        self.assertEqual(p_without_url.game_id, self.game2.pk)

    def test_playable_clean_validation(self) -> None:
        # Valid when matching
        p_valid = Playable(
            game=self.game1,
            game_url=self.game_url1,
            slug="valid",
            template="parchment",
            template_version="1",
        )
        p_valid.clean()

        # Valid when game_url is None
        p_none = Playable(
            game=self.game1,
            game_url=None,
            slug="none",
            template="parchment",
            template_version="1",
        )
        p_none.clean()

        # Invalid when mismatch
        p_invalid = Playable(
            game=self.game2,
            game_url=self.game_url1,
            slug="invalid",
            template="parchment",
            template_version="1",
        )
        with self.assertRaises(ValidationError) as ctx:
            p_invalid.clean()
        self.assertIn("game_url", ctx.exception.message_dict)
