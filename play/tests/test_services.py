from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils.timezone import now

from games.models import URL, Game, GameURL, GameURLCategory
from play.models import Playable
from play.services import (
    format_pinned_url_error,
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
        cat = GameURLCategory.objects.create(
            symbolic_id="download_direct", title="Direct Download"
        )
        url = URL.objects.create(
            original_url="https://example.com/file1.zip", creation_date=now()
        )
        self.game_url1 = GameURL.objects.create(
            game=self.game1, category=cat, url=url
        )

    def test_format_pinned_url_error(self) -> None:
        Playable.objects.create(
            game=self.game1,
            game_url=self.game_url1,
            slug="test-slug",
            template="parchment",
            template_version="1",
        )
        self.assertIn(
            "URL нельзя удалить: из него создан сайт test-slug.",
            format_pinned_url_error(self.game_url1),
        )

    def test_move_game_url_and_duplicates(self) -> None:
        p1 = Playable.objects.create(
            game=self.game1,
            game_url=self.game_url1,
            slug="slug-1",
            template="parchment",
            template_version="1",
        )
        # Move without duplicate
        move_game_url(self.game_url1, self.game2)
        p1.refresh_from_db()
        self.assertEqual(p1.game_id, self.game2.pk)

        # Move back with existing destination duplicate
        dest_gu = GameURL.objects.create(
            game=self.game1,
            category=self.game_url1.category,
            url=self.game_url1.url,
        )
        move_game_url(self.game_url1, self.game1)
        p1.refresh_from_db()
        self.assertEqual(p1.game_id, self.game1.pk)
        self.assertEqual(p1.game_url_id, dest_gu.pk)

    def test_transfer_game_playables(self) -> None:
        p_url = Playable.objects.create(
            game=self.game1,
            game_url=self.game_url1,
            slug="p-url",
            template="parchment",
            template_version="1",
        )
        p_no_url = Playable.objects.create(
            game=self.game1,
            game_url=None,
            slug="p-no-url",
            template="parchment",
            template_version="1",
        )
        transfer_game_playables(self.game1, self.game2)
        p_url.refresh_from_db()
        p_no_url.refresh_from_db()
        self.assertEqual(p_url.game_id, self.game2.pk)
        self.assertEqual(p_no_url.game_id, self.game2.pk)

    def test_playable_clean_validation(self) -> None:
        p_valid = Playable(
            game=self.game1,
            game_url=self.game_url1,
            slug="valid",
            template="t",
            template_version="1",
        )
        p_valid.clean()

        p_invalid = Playable(
            game=self.game2,
            game_url=self.game_url1,
            slug="invalid",
            template="t",
            template_version="1",
        )
        with self.assertRaises(ValidationError):
            p_invalid.clean()
