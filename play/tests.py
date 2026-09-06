from importlib.machinery import FileFinder
from pathlib import Path
from pkgutil import ModuleInfo
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import cast
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

from django.core.files.storage import FileSystemStorage
from django.db import models
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils.timezone import now

from games.models import URL, Game, GameURL, GameURLCategory
from play.tasks import generate_playable

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
        cls.game = Game.objects.create(
            state=Game.State.PUBLISHED, title="A game", creation_time=now()
        )

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

    def test_playable_nullable_slug_and_state(self) -> None:
        p1 = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.5.2",
        )
        p2 = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="3.5.2",
        )
        self.assertIsNone(p1.slug)
        self.assertIsNone(p2.slug)
        self.assertEqual(str(p1), f"playable-{p1.pk}")
        self.assertEqual(p1.state, Playable.State.PENDING)


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


class TaskTests(TestCase):
    game: Game

    @classmethod
    def setUpTestData(cls) -> None:
        cls.game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Task test game",
            creation_time=now(),
        )

    def test_generate_playable_success(self) -> None:
        with (
            TemporaryDirectory() as media_root,
            TemporaryDirectory() as playables_dir,
        ):
            fs = FileSystemStorage(media_root)
            game_file_path = Path(media_root) / "game.zip"
            with ZipFile(game_file_path, "w") as z:
                z.writestr("main.lua", b"return true")

            url = URL.objects.create(
                original_url="https://example.com/game.zip",
                local_filename="game.zip",
                creation_date=now(),
            )
            cat, _ = GameURLCategory.objects.get_or_create(
                symbolic_id="download_direct",
                defaults={"title": "Direct download"},
            )
            game_url = GameURL.objects.create(
                game=self.game,
                url=url,
                category=cat,
            )
            playable = Playable.objects.create(
                game=self.game,
                game_url=game_url,
                template="instead_em",
                template_version="3.5.2",
                config={},
            )

            with override_settings(
                PLAYABLE_DIR=playables_dir,
                UPLOADS_FS=fs,
            ):
                with patch("games.models.URL.GetFs", return_value=fs):
                    generate_playable(playable.pk)

            playable.refresh_from_db()
            self.assertEqual(playable.state, Playable.State.READY)
            dest = Path(playables_dir) / str(playable.pk)
            self.assertTrue((dest / "index.html").exists())
            self.assertTrue((dest / "game.zip").exists())

    def test_generate_playable_failure(self) -> None:
        playable = Playable.objects.create(
            game=self.game,
            template="nonexistent_blueprint",
            template_version="1.0",
        )
        with self.assertRaises(ValueError):
            generate_playable(playable.pk)

        playable.refresh_from_db()
        self.assertEqual(playable.state, Playable.State.ERROR)
