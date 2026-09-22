from django.test import TestCase
from django.utils.timezone import now

from core.models import User
from curation.merge import merge_game_into_game
from games.models import URL, Game, GameURL, GameURLCategory
from play.models import Playable


class MergePlayablesTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="merge_curator",
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
        return Game.objects.create(
            title=title,
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )

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

    def test_merge_moves_pinned_url_and_playables_non_duplicate(self) -> None:
        source = self._create_game("Source Game")
        target = self._create_game("Target Game")
        gu = self._create_game_url(source, "https://example.com/unique")
        p = self._create_playable(source, gu, slug="unique-play")

        merge_game_into_game(
            target_game=target,
            source_game=source,
            actor=self.user,
            remap_contests=False,
        )

        p.refresh_from_db()
        gu.refresh_from_db()

        self.assertEqual(p.game_id, target.id)
        self.assertEqual(p.game_url_id, gu.id)
        self.assertEqual(gu.game_id, target.id)
        self.assertFalse(source.playable_set.exists())
        self.assertFalse(source.gameurl_set.exists())
        self.assertEqual(target.playable_set.count(), 1)
        self.assertEqual(target.gameurl_set.count(), 1)

    def test_merge_handles_duplicate_pinned_url_repointing_playables(
        self,
    ) -> None:
        source = self._create_game("Source Game")
        target = self._create_game("Target Game")
        source_gu = self._create_game_url(
            source, "https://example.com/shared", category=self.cat_play
        )
        target_gu = self._create_game_url(
            target, "https://example.com/shared", category=self.cat_play
        )
        p = self._create_playable(source, source_gu, slug="shared-play")

        merge_game_into_game(
            target_game=target,
            source_game=source,
            actor=self.user,
            remap_contests=False,
        )

        p.refresh_from_db()
        target_gu.refresh_from_db()

        self.assertEqual(p.game_id, target.id)
        self.assertEqual(p.game_url_id, target_gu.id)
        self.assertFalse(GameURL.objects.filter(pk=source_gu.id).exists())
        self.assertFalse(source.playable_set.exists())
        self.assertEqual(target.playable_set.count(), 1)
        self.assertEqual(target.gameurl_set.count(), 1)

    def test_merge_moves_unlinked_playable(self) -> None:
        source = self._create_game("Source Game")
        target = self._create_game("Target Game")
        p = self._create_playable(source, game_url=None, slug="unlinked-play")

        merge_game_into_game(
            target_game=target,
            source_game=source,
            actor=self.user,
            remap_contests=False,
        )

        p.refresh_from_db()

        self.assertEqual(p.game_id, target.id)
        self.assertIsNone(p.game_url_id)
        self.assertFalse(source.playable_set.exists())
        self.assertEqual(target.playable_set.count(), 1)

    def test_merge_all_combinations_together(self) -> None:
        source = self._create_game("Source Game")
        target = self._create_game("Target Game")

        # Source: 1 unique pinned, 1 duplicate pinned, 1 unlinked
        src_unique_gu = self._create_game_url(
            source, "https://example.com/src-unique"
        )
        p_unique = self._create_playable(
            source, src_unique_gu, slug="src-unique-play"
        )

        src_dup_gu = self._create_game_url(source, "https://example.com/dup")
        self._create_game_url(target, "https://example.com/dup")
        p_dup = self._create_playable(source, src_dup_gu, slug="dup-play")

        p_unlinked = self._create_playable(
            source, game_url=None, slug="unlinked-play"
        )

        # Target also has an existing unrelated URL
        self._create_game_url(target, "https://example.com/tgt-unrelated")

        merge_game_into_game(
            target_game=target,
            source_game=source,
            actor=self.user,
            remap_contests=False,
        )

        for p in (p_unique, p_dup, p_unlinked):
            p.refresh_from_db()
            self.assertEqual(p.game_id, target.id)
            if p.game_url is not None:
                self.assertEqual(p.game_url.game_id, target.id)

        self.assertFalse(source.playable_set.exists())
        self.assertEqual(target.playable_set.count(), 3)
