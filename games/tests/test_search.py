from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from games.models import URL, Game, GameURL, GameURLCategory
from games.search import SB_UserFlags
from play.models import Playable


class UserFlagsSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def test_user_flags_field_names(self) -> None:
        flags = SB_UserFlags()
        self.assertIn(
            f"Можно поиграть на {settings.PLAYABLE_BASE_DOMAIN}",
            flags.FIELDS,
        )
        self.assertIn("Можно поиграть на других сайтах", flags.FIELDS)
        self.assertIn(
            f"Нельзя поиграть на {settings.PLAYABLE_BASE_DOMAIN}",
            flags.FIELDS,
        )
        self.assertIn("Нельзя поиграть нигде", flags.FIELDS)
        idx_playable = flags.FIELDS.index(
            f"Можно поиграть на {settings.PLAYABLE_BASE_DOMAIN}"
        )
        idx_other = flags.FIELDS.index("Можно поиграть на других сайтах")
        idx_cant_playable = flags.FIELDS.index(
            f"Нельзя поиграть на {settings.PLAYABLE_BASE_DOMAIN}"
        )
        idx_cant_anywhere = flags.FIELDS.index("Нельзя поиграть нигде")
        self.assertEqual(idx_playable + 1, idx_other)
        self.assertEqual(idx_other + 1, idx_cant_playable)
        self.assertEqual(idx_cant_playable + 1, idx_cant_anywhere)
        self.assertNotIn("Можно запустить лунчатором", flags.FIELDS)

    def test_filter_by_playable_on_domain(self) -> None:
        now = timezone.now()
        game_playable = Game.objects.create(
            title="Game Playable",
            state=Game.State.PUBLISHED,
            creation_time=now,
        )
        Playable.objects.create(
            game=game_playable,
            state=Playable.State.READY,
            visible=True,
            slug="playable-slug",
        )

        game_not_ready = Game.objects.create(
            title="Game Not Ready",
            state=Game.State.PUBLISHED,
            creation_time=now,
        )
        Playable.objects.create(
            game=game_not_ready,
            state=Playable.State.BUILDING,
            visible=True,
            slug="not-ready-slug",
        )

        game_invisible = Game.objects.create(
            title="Game Invisible",
            state=Game.State.PUBLISHED,
            creation_time=now,
        )
        Playable.objects.create(
            game=game_invisible,
            state=Playable.State.READY,
            visible=False,
            slug="invisible-slug",
        )

        game_no_slug = Game.objects.create(
            title="Game No Slug",
            state=Game.State.PUBLISHED,
            creation_time=now,
        )
        Playable.objects.create(
            game=game_no_slug,
            state=Playable.State.READY,
            visible=True,
            slug="",
        )

        cat_play_online = GameURLCategory.objects.get(
            symbolic_id="play_online"
        )
        url_ext = URL.objects.create(
            original_url="https://external.example.com/play",
            creation_date=now,
        )
        game_other_site = Game.objects.create(
            title="Game Other Site",
            state=Game.State.PUBLISHED,
            creation_time=now,
        )
        GameURL.objects.create(
            game=game_other_site,
            category=cat_play_online,
            url=url_ext,
        )

        # Filter by "Можно поиграть на play.crem.xyz" (index 5)
        flags_playable = SB_UserFlags()
        flags_playable.items[5] = True
        qs_playable = flags_playable.ModifyQuery(Game.objects.all()).distinct()
        self.assertIn(game_playable, qs_playable)
        self.assertNotIn(game_not_ready, qs_playable)
        self.assertNotIn(game_invisible, qs_playable)
        self.assertNotIn(game_no_slug, qs_playable)
        self.assertNotIn(game_other_site, qs_playable)

        # Filter by "Можно поиграть на других сайтах" (index 6)
        flags_other = SB_UserFlags()
        flags_other.items[6] = True
        qs_other = flags_other.ModifyQuery(Game.objects.all()).distinct()
        self.assertIn(game_other_site, qs_other)
        self.assertNotIn(game_playable, qs_other)

        game_both = Game.objects.create(
            title="Game Both",
            state=Game.State.PUBLISHED,
            creation_time=now,
        )
        Playable.objects.create(
            game=game_both,
            state=Playable.State.READY,
            visible=True,
            slug="both-slug",
        )
        GameURL.objects.create(
            game=game_both,
            category=cat_play_online,
            url=url_ext,
        )

        game_neither = Game.objects.create(
            title="Game Neither",
            state=Game.State.PUBLISHED,
            creation_time=now,
        )

        game_multi_playable = Game.objects.create(
            title="Game Multi Playable",
            state=Game.State.PUBLISHED,
            creation_time=now,
        )
        Playable.objects.create(
            game=game_multi_playable,
            state=Playable.State.ERROR,
            visible=True,
            slug=None,
        )
        Playable.objects.create(
            game=game_multi_playable,
            state=Playable.State.READY,
            visible=True,
            slug="multi-ready-slug",
        )

        # Filter by "Нельзя поиграть на play.crem.xyz" (index 7)
        flags_cant_playable = SB_UserFlags()
        flags_cant_playable.items[7] = True
        qs_cant_playable = flags_cant_playable.ModifyQuery(
            Game.objects.all()
        ).distinct()
        self.assertNotIn(game_playable, qs_cant_playable)
        self.assertNotIn(game_both, qs_cant_playable)
        self.assertNotIn(game_multi_playable, qs_cant_playable)
        self.assertIn(game_not_ready, qs_cant_playable)
        self.assertIn(game_invisible, qs_cant_playable)
        self.assertIn(game_no_slug, qs_cant_playable)
        self.assertIn(game_other_site, qs_cant_playable)
        self.assertIn(game_neither, qs_cant_playable)

        # Filter by "Нельзя поиграть нигде" (index 8)
        flags_cant_anywhere = SB_UserFlags()
        flags_cant_anywhere.items[8] = True
        qs_cant_anywhere = flags_cant_anywhere.ModifyQuery(
            Game.objects.all()
        ).distinct()
        self.assertNotIn(game_playable, qs_cant_anywhere)
        self.assertNotIn(game_both, qs_cant_anywhere)
        self.assertNotIn(game_multi_playable, qs_cant_anywhere)
        self.assertNotIn(game_other_site, qs_cant_anywhere)
        self.assertIn(game_not_ready, qs_cant_anywhere)
        self.assertIn(game_invisible, qs_cant_anywhere)
        self.assertIn(game_no_slug, qs_cant_anywhere)
        self.assertIn(game_neither, qs_cant_anywhere)
