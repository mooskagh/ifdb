import stat
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
from play.blueprint import (
    BlueprintInfo,
    BlueprintModule,
    BlueprintSpec,
    GenerateSpec,
    discover_blueprints,
)
from play.models import Playable
from play.tasks import ensure_group_readable, generate_playable


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
                CADDY_ADMIN_URL="http://localhost:2019",
            ):
                with (
                    patch("games.models.URL.GetFs", return_value=fs),
                    patch("play.tasks.configure_caddy_playable") as mock_caddy,
                    patch(
                        "play.tasks.generate_playable_domain",
                        return_value="auto-slug",
                    ) as mock_gen_domain,
                ):
                    mock_caddy.return_value = True
                    generate_playable(playable.pk)

            playable.refresh_from_db()
            self.assertEqual(playable.state, Playable.State.READY)
            self.assertEqual(playable.slug, "auto-slug")
            mock_gen_domain.assert_called_once_with(
                playable.game, current_playable_pk=playable.pk
            )
            mock_caddy.assert_called_once_with(playable)
            dest = Path(playables_dir) / str(playable.pk)
            self.assertTrue((dest / "index.html").exists())
            self.assertTrue((dest / "game.zip").exists())

            # Verify group permissions on directory and files
            dest_mode = dest.stat().st_mode & 0o777
            self.assertEqual(
                dest_mode & (stat.S_IRGRP | stat.S_IXGRP),
                stat.S_IRGRP | stat.S_IXGRP,
            )
            self.assertEqual(dest_mode & stat.S_IWOTH, 0)

            index_mode = (dest / "index.html").stat().st_mode & 0o777
            self.assertEqual(index_mode & stat.S_IRGRP, stat.S_IRGRP)
            self.assertEqual(index_mode & stat.S_IWOTH, 0)

    def test_generate_playable_with_preset_slug(self) -> None:
        with TemporaryDirectory() as temp_dir:
            uploads_dir = Path(temp_dir) / "uploads"
            uploads_dir.mkdir()
            playables_dir = Path(temp_dir) / "playables"
            playables_dir.mkdir()

            fs = FileSystemStorage(location=str(uploads_dir))
            game_file_path = uploads_dir / "game.zip"
            with ZipFile(game_file_path, "w") as zf:
                zf.writestr("main3.lua", "-- instead game")

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
                slug="preset-slug",
                config={},
            )

            with override_settings(
                PLAYABLE_DIR=playables_dir,
                UPLOADS_FS=fs,
                CADDY_ADMIN_URL="http://localhost:2019",
            ):
                with (
                    patch("games.models.URL.GetFs", return_value=fs),
                    patch("play.tasks.configure_caddy_playable") as mock_caddy,
                    patch(
                        "play.tasks.generate_playable_domain"
                    ) as mock_gen_domain,
                ):
                    mock_caddy.return_value = True
                    generate_playable(playable.pk)

            playable.refresh_from_db()
            self.assertEqual(playable.state, Playable.State.READY)
            self.assertEqual(playable.slug, "preset-slug")
            mock_gen_domain.assert_not_called()
            mock_caddy.assert_called_once_with(playable)
            dest = Path(playables_dir) / str(playable.pk)
            self.assertTrue((dest / "index.html").exists())

    def test_generate_playable_caddy_failure(self) -> None:
        with (
            TemporaryDirectory() as media_root,
            TemporaryDirectory() as playables_dir,
        ):
            fs = FileSystemStorage(media_root)
            game_file_path = Path(media_root) / "game.zip"
            with ZipFile(game_file_path, "w") as z:
                z.writestr("main.lua", "return true")

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
                CADDY_ADMIN_URL="http://localhost:2019",
            ):
                with (
                    patch("games.models.URL.GetFs", return_value=fs),
                    patch(
                        "play.tasks.configure_caddy_playable",
                        return_value=False,
                    ) as mock_caddy,
                    patch(
                        "play.tasks.generate_playable_domain",
                        return_value="fail-slug",
                    ),
                ):
                    with self.assertRaises(RuntimeError):
                        generate_playable(playable.pk)

            playable.refresh_from_db()
            self.assertEqual(playable.state, Playable.State.ERROR)
            mock_caddy.assert_called_once_with(playable)

    def test_generate_playable_caddy_disabled(self) -> None:
        with (
            TemporaryDirectory() as media_root,
            TemporaryDirectory() as playables_dir,
        ):
            fs = FileSystemStorage(media_root)
            game_file_path = Path(media_root) / "game.zip"
            with ZipFile(game_file_path, "w") as z:
                z.writestr("main.lua", "return true")

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
                CADDY_ADMIN_URL=None,
            ):
                with (
                    patch("games.models.URL.GetFs", return_value=fs),
                    patch("play.tasks.configure_caddy_playable") as mock_caddy,
                    patch(
                        "play.tasks.generate_playable_domain",
                        return_value="no-caddy-slug",
                    ),
                ):
                    generate_playable(playable.pk)

            playable.refresh_from_db()
            self.assertEqual(playable.state, Playable.State.READY)
            mock_caddy.assert_not_called()

    def test_ensure_group_readable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir) / "playable"
            base_dir.mkdir(mode=0o700)
            sub_dir = base_dir / "assets"
            sub_dir.mkdir(mode=0o700)

            file_normal = sub_dir / "data.txt"
            file_normal.write_text("hello")
            file_normal.chmod(0o600)

            file_exec = sub_dir / "script.sh"
            file_exec.write_text("#!/bin/sh")
            file_exec.chmod(0o700)

            ensure_group_readable(base_dir)

            base_mode = base_dir.stat().st_mode & 0o777
            self.assertEqual(base_mode, 0o750)

            sub_mode = sub_dir.stat().st_mode & 0o777
            self.assertEqual(sub_mode, 0o750)

            normal_mode = file_normal.stat().st_mode & 0o777
            self.assertEqual(normal_mode, 0o640)

            exec_mode = file_exec.stat().st_mode & 0o777
            self.assertEqual(exec_mode, 0o740)

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
