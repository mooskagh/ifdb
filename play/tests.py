from django.db import models
from django.test import TestCase
from django.utils.timezone import now

from games.models import Game

from .models import Playable


class ModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.game = Game.objects.create(title="A game", creation_time=now())

    def test_playable(self):
        playable = Playable.objects.create(
            slug="demo",
            game=self.game,
            template="instead",
        )

        self.assertEqual(str(playable), "demo")
        self.assertEqual(playable.template, "instead")
        self.assertIsInstance(
            Playable._meta.get_field("template"), models.SlugField
        )
        self.assertEqual(playable.config, {})
        self.assertIsNotNone(playable.created)
        self.assertIsNotNone(playable.updated)
        self.assertEqual(Playable._meta.default_permissions, ())

    def test_config_default_is_independent(self):
        first = Playable.objects.create(
            slug="first",
            game=self.game,
            template="instead",
        )
        second = Playable.objects.create(
            slug="second",
            game=self.game,
            template="instead",
        )

        first.config["theme"] = "dark"
        first.save()
        second.refresh_from_db()

        self.assertEqual(second.config, {})
