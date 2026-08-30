from importlib.machinery import FileFinder
from pkgutil import ModuleInfo
from types import ModuleType
from typing import cast
from unittest.mock import MagicMock, patch

from django.db import models
from django.test import SimpleTestCase, TestCase
from django.utils.timezone import now

from games.models import Game

from .blueprint import (
    BlueprintInfo,
    BlueprintModule,
    BlueprintSpec,
    GenerateSpec,
    discover_blueprints,
)
from .models import Playable


class ModelTests(TestCase):
    game: Game

    @classmethod
    def setUpTestData(cls) -> None:
        cls.game = Game.objects.create(title="A game", creation_time=now())

    def test_playable(self) -> None:
        playable = Playable.objects.create(
            slug="demo",
            game=self.game,
            template="instead",
            template_version="1.0",
        )

        self.assertEqual(str(playable), "demo")
        self.assertEqual(playable.template, "instead")
        self.assertEqual(playable.template_version, "1.0")
        self.assertEqual(playable.template_config, {})
        self.assertIsInstance(
            Playable._meta.get_field("template"), models.SlugField
        )
        self.assertIsInstance(
            Playable._meta.get_field("template_version"), models.CharField
        )
        self.assertIsInstance(
            Playable._meta.get_field("template_config"), models.JSONField
        )
        self.assertEqual(playable.config, {})
        self.assertIsNotNone(playable.created)
        self.assertIsNotNone(playable.updated)
        self.assertEqual(Playable._meta.default_permissions, ())

    def test_config_default_is_independent(self) -> None:
        first = Playable.objects.create(
            slug="first",
            game=self.game,
            template="instead",
            template_version="1.0",
        )
        second = Playable.objects.create(
            slug="second",
            game=self.game,
            template="instead",
            template_version="1.0",
        )

        first.config["theme"] = "dark"
        first.template_config["layout"] = "compact"
        first.save()
        second.refresh_from_db()

        self.assertEqual(second.config, {})
        self.assertEqual(second.template_config, {})


class BlueprintTests(SimpleTestCase):
    @staticmethod
    def module_info(name: str, ispkg: bool) -> ModuleInfo:
        return ModuleInfo(FileFinder("."), name, ispkg)

    @staticmethod
    def example_module() -> ModuleType:
        module = ModuleType("play.blueprints.example")
        spec = BlueprintSpec(name="Example", versions=["1"])

        def get_spec() -> BlueprintSpec:
            return spec

        def generate(_spec: GenerateSpec) -> None:
            pass

        setattr(module, "get_spec", get_spec)
        setattr(module, "generate", generate)
        return module

    @patch("play.blueprint.import_module")
    @patch("play.blueprint.iter_modules")
    def test_discovers_blueprint_packages(
        self, iter_modules_mock: MagicMock, import_mock: MagicMock
    ) -> None:
        module = self.example_module()
        iter_modules_mock.return_value = [
            self.module_info("example", True),
            self.module_info("not_a_package", False),
        ]
        import_mock.return_value = module

        self.assertEqual(
            discover_blueprints(),
            [BlueprintInfo("example", cast(BlueprintModule, module))],
        )
