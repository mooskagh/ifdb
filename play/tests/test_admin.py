from django.contrib.admin.sites import site
from django.test import TestCase

from games.admin import GameAdmin, InlinePlayableAdmin
from games.models import Game
from play.admin import PlayableAdmin
from play.models import Playable


class PlayableAdminTests(TestCase):
    def test_playable_admin_registered(self) -> None:
        self.assertIn(Playable, site._registry)
        admin_instance = site._registry[Playable]
        self.assertIsInstance(admin_instance, PlayableAdmin)
        self.assertIn("slug", admin_instance.list_display)
        self.assertIn("state", admin_instance.list_display)
        self.assertIn("created", admin_instance.readonly_fields)
        self.assertIn("updated", admin_instance.readonly_fields)

    def test_game_admin_has_playable_inline(self) -> None:
        self.assertIn(Game, site._registry)
        game_admin = site._registry[Game]
        self.assertIsInstance(game_admin, GameAdmin)
        self.assertIn(InlinePlayableAdmin, game_admin.inlines)
