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
    discover_blueprints,
)
from .blueprints import sample as sample_blueprint
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

    def test_config_default_is_independent(self) -> None:
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


class BlueprintDiscoveryTests(SimpleTestCase):
    def test_discovers_sample_blueprint(self) -> None:
        self.assertIn(
            BlueprintInfo("sample", sample_blueprint), discover_blueprints()
        )
        self.assertEqual(sample_blueprint.spec.name, "Sample")

    @staticmethod
    def blueprint_module(name: str) -> BlueprintModule:
        module = ModuleType(f"play.blueprints.{name}")
        setattr(module, "spec", BlueprintSpec(name=name))
        return cast(BlueprintModule, module)

    @staticmethod
    def module_info(name: str, ispkg: bool) -> ModuleInfo:
        return ModuleInfo(FileFinder("."), name, ispkg)

    @patch("play.blueprint.import_module")
    @patch("play.blueprint.iter_modules")
    def test_discovers_blueprint_packages(
        self, iter_modules_mock: MagicMock, import_mock: MagicMock
    ) -> None:
        iter_modules_mock.return_value = [
            self.module_info("zeta", True),
            self.module_info("file", False),
            self.module_info("alpha", True),
        ]
        modules = {
            f"play.blueprints.{name}": self.blueprint_module(name)
            for name in ("alpha", "zeta")
        }
        import_mock.side_effect = modules.__getitem__

        self.assertEqual(
            discover_blueprints(),
            [
                BlueprintInfo("alpha", modules["play.blueprints.alpha"]),
                BlueprintInfo("zeta", modules["play.blueprints.zeta"]),
            ],
        )

    @patch("play.blueprint.import_module")
    @patch("play.blueprint.iter_modules")
    def test_skips_packages_without_valid_spec(
        self, iter_modules_mock: MagicMock, import_mock: MagicMock
    ) -> None:
        iter_modules_mock.return_value = [
            self.module_info("missing", True),
            self.module_info("invalid", True),
        ]
        missing = ModuleType("play.blueprints.missing")
        invalid = ModuleType("play.blueprints.invalid")
        setattr(invalid, "spec", object())
        modules = {module.__name__: module for module in (missing, invalid)}
        import_mock.side_effect = modules.__getitem__

        self.assertEqual(discover_blueprints(), [])

    @patch("play.blueprint.import_module", side_effect=ImportError("broken"))
    @patch(
        "play.blueprint.iter_modules",
        return_value=[ModuleInfo(FileFinder("."), "broken", True)],
    )
    def test_import_errors_propagate(
        self, _iter_modules_mock: MagicMock, _import_mock: MagicMock
    ) -> None:
        with self.assertRaisesRegex(ImportError, "broken"):
            discover_blueprints()
