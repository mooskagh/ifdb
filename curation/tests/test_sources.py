from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from curation.models import GameCuration, GameSource
from games.gameinfo import GameInfo, GameUrl
from games.models import Game, GameRevision, GameURLCategory

APERO_URL = "https://apero.ru/Текстовые-игры/Игра"


@patch("curation.tasks.fetch_sources.delay")
class AdoptLinkSourcesTest(TestCase):
    def setUp(self) -> None:
        for slug in ("game_page", "poster"):
            GameURLCategory.objects.create(symbolic_id=slug, title=slug)
        self.user = get_user_model().objects.create(username="u")

    def _publish(self, origin: str, *urls: tuple[str, str]) -> Game:
        game = Game.objects.create(title="G", creation_time=timezone.now())
        info = GameInfo(
            name="G",
            urls=[GameUrl(cat, None, None, url) for cat, url in urls],
        )
        revision = GameRevision(
            game=game,
            created_at=timezone.now(),
            origin=origin,
            canonical_text=info.to_canonical(),
        )
        with self.captureOnCommitCallbacks(execute=True):
            game.publish_revision(revision, actor=self.user)
        return game

    def test_manual_edit_adopts_source_link(self, _delay: MagicMock) -> None:
        game = self._publish(
            GameRevision.Origin.MANUAL_EDIT,
            ("game_page", APERO_URL),
            ("poster", "https://ifwiki.ru/files/p.png"),
        )
        source = GameSource.objects.get()
        self.assertEqual(source.game, game)
        self.assertEqual(source.type, GameSource.SourceType.APERO)

    def test_auto_import_does_not_adopt(self, _delay: MagicMock) -> None:
        self._publish(
            GameRevision.Origin.AUTO_IMPORT, ("game_page", APERO_URL)
        )
        self.assertFalse(GameSource.objects.exists())

    def test_source_of_other_game_flags_instead_of_moving(
        self, _delay: MagicMock
    ) -> None:
        other = Game.objects.create(title="O", creation_time=timezone.now())
        GameSource.objects.create(
            game=other,
            type=GameSource.SourceType.APERO,
            url=APERO_URL.replace("https", "http"),
        )
        game = self._publish(
            GameRevision.Origin.MANUAL_EDIT, ("game_page", APERO_URL)
        )
        self.assertEqual(GameSource.objects.get().game, other)
        curation = GameCuration.objects.get(game=game)
        self.assertEqual(curation.state, GameCuration.State.NEEDS_ATTENTION)
        self.assertIn(f"#{other.pk}", curation.note)
