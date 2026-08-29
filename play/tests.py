from pkgutil import ModuleInfo
from types import ModuleType
from unittest.mock import patch

from django.db import models
from django.test import SimpleTestCase, TestCase
from django.utils.timezone import now

from games.models import Game

from .blueprint import BlueprintBase, BlueprintInfo, discover_blueprints
from .blueprints.sample import Blueprint as SampleBlueprint
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


class BlueprintDiscoveryTests(SimpleTestCase):
    def test_discovers_sample_blueprint(self):
        self.assertIn(
            BlueprintInfo("sample", SampleBlueprint), discover_blueprints()
        )
        self.assertEqual(SampleBlueprint().name(), "Sample")

    @staticmethod
    def blueprint_module(name):
        module = ModuleType(f"play.blueprints.{name}")
        module.Blueprint = type(
            "Blueprint",
            (BlueprintBase,),
            {"__module__": module.__name__},
        )
        return module

    @patch("play.blueprint.import_module")
    @patch("play.blueprint.iter_modules")
    def test_discovers_blueprint_packages(
        self, iter_modules_mock, import_mock
    ):
        iter_modules_mock.return_value = [
            ModuleInfo(None, "zeta", True),
            ModuleInfo(None, "file", False),
            ModuleInfo(None, "alpha", True),
        ]
        modules = {
            f"play.blueprints.{name}": self.blueprint_module(name)
            for name in ("alpha", "zeta")
        }
        alpha = modules["play.blueprints.alpha"]
        alpha.Blueprint = type(
            "Blueprint",
            (alpha.Blueprint,),
            {"__module__": alpha.__name__},
        )
        import_mock.side_effect = modules.__getitem__

        self.assertEqual(
            discover_blueprints(),
            [
                BlueprintInfo(
                    "alpha", modules["play.blueprints.alpha"].Blueprint
                ),
                BlueprintInfo(
                    "zeta", modules["play.blueprints.zeta"].Blueprint
                ),
            ],
        )

    @patch("play.blueprint.import_module")
    @patch("play.blueprint.iter_modules")
    def test_skips_packages_without_local_subclass(
        self, iter_modules_mock, import_mock
    ):
        iter_modules_mock.return_value = [
            ModuleInfo(None, "missing", True),
            ModuleInfo(None, "unrelated", True),
            ModuleInfo(None, "imported", True),
        ]
        missing = ModuleType("play.blueprints.missing")
        unrelated = ModuleType("play.blueprints.unrelated")
        unrelated.Blueprint = type(
            "Blueprint", (), {"__module__": unrelated.__name__}
        )
        imported = ModuleType("play.blueprints.imported")
        imported.Blueprint = BlueprintBase
        modules = {
            module.__name__: module
            for module in (missing, unrelated, imported)
        }
        import_mock.side_effect = modules.__getitem__

        self.assertEqual(discover_blueprints(), [])

    @patch("play.blueprint.import_module", side_effect=ImportError("broken"))
    @patch(
        "play.blueprint.iter_modules",
        return_value=[ModuleInfo(None, "broken", True)],
    )
    def test_import_errors_propagate(self, _iter_modules_mock, _import_mock):
        with self.assertRaisesRegex(ImportError, "broken"):
            discover_blueprints()
