from django.test import TestCase
from django.utils.timezone import now

from games.models import Game

from .models import Playable, Template


class ModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.game = Game.objects.create(title="A game", creation_time=now())
        cls.template = Template.objects.create(slug="instead", name="Instead")

    def test_template(self):
        self.assertEqual(str(self.template), "Instead")
        self.assertEqual(Template._meta.default_permissions, ())

    def test_playable(self):
        playable = Playable.objects.create(
            slug="demo",
            game=self.game,
            template=self.template,
        )

        self.assertEqual(str(playable), "demo")
        self.assertEqual(playable.config, {})
        self.assertIsNotNone(playable.created)
        self.assertIsNotNone(playable.updated)
        self.assertEqual(Playable._meta.default_permissions, ())

    def test_config_default_is_independent(self):
        first = Playable.objects.create(
            slug="first",
            game=self.game,
            template=self.template,
        )
        second = Playable.objects.create(
            slug="second",
            game=self.game,
            template=self.template,
        )

        first.config["theme"] = "dark"
        first.save()
        second.refresh_from_db()

        self.assertEqual(second.config, {})
