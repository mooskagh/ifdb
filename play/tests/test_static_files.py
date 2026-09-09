from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from django.core.files.storage import FileSystemStorage
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils.timezone import now

from games.models import URL, Game, GameURL, GameURLCategory
from play.blueprint import GenerateSpec, discover_blueprints
from play.blueprints.static_files import (
    accepts,
    generate,
    get_spec,
)
from play.models import Playable
from play.tasks import generate_playable


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    with ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


class StaticFilesTests(SimpleTestCase):
    def test_get_spec(self) -> None:
        spec = get_spec()
        self.assertEqual(spec.name, "Static files")
        self.assertEqual(spec.versions, ["1"])

    def test_discovered_by_discover_blueprints(self) -> None:
        names = [info.name for info in discover_blueprints()]
        self.assertIn("static_files", names)
        static_bp = next(
            info.blueprint
            for info in discover_blueprints()
            if info.name == "static_files"
        )
        self.assertEqual(static_bp.get_spec().name, "Static files")

    def test_accepts_root_index(self) -> None:
        cases = (
            {"index.html": b"<h1>Hello</h1>"},
            {"index.htm": b"<h1>Hello</h1>"},
            {
                "index.html": b"<h1>Hello</h1>",
                "style.css": b"body {}",
                "assets/img.png": b"fake_png",
            },
            {
                "index.htm": b"<h1>Hello</h1>",
                "assets/img.png": b"fake_png",
            },
            {
                "index.html": b"<h1>Hello</h1>",
                "__MACOSX/._index.html": b"apple_double",
                ".DS_Store": b"ds_store",
            },
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for idx, members in enumerate(cases):
                archive_path = root / f"game_{idx}.zip"
                _write_zip(archive_path, members)
                with self.subTest(idx=idx, members=list(members.keys())):
                    self.assertTrue(accepts(archive_path))

    def test_accepts_single_root_directory_with_index(self) -> None:
        cases = (
            {"my_game/index.html": b"<h1>Hello</h1>"},
            {"my_game/index.htm": b"<h1>Hello</h1>"},
            {
                "my_game/": b"",
                "my_game/index.html": b"<h1>Hello</h1>",
                "my_game/style.css": b"body {}",
            },
            {
                "my_game/index.html": b"<h1>Hello</h1>",
                "my_game/sub/script.js": b"console.log('hi');",
            },
            {
                "__MACOSX/._my_game": b"apple_double",
                ".DS_Store": b"ds_store",
                "my_game/": b"",
                "my_game/index.html": b"<h1>Hello</h1>",
                "my_game/.DS_Store": b"ds_store",
            },
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for idx, members in enumerate(cases):
                archive_path = root / f"game_dir_{idx}.zip"
                _write_zip(archive_path, members)
                with self.subTest(idx=idx, members=list(members.keys())):
                    self.assertTrue(accepts(archive_path))

    def test_accepts_root_single_html(self) -> None:
        cases = (
            {"game.html": b"<h1>Game</h1>"},
            {"story.htm": b"<h1>Story</h1>"},
            {
                "game.html": b"<h1>Game</h1>",
                "style.css": b"body {}",
                "assets/img.png": b"fake_png",
            },
            {
                "story.htm": b"<h1>Story</h1>",
                "assets/img.png": b"fake_png",
            },
            {
                "game.html": b"<h1>Game</h1>",
                "__MACOSX/._game.html": b"apple_double",
                ".DS_Store": b"ds_store",
            },
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for idx, members in enumerate(cases):
                archive_path = root / f"single_html_{idx}.zip"
                _write_zip(archive_path, members)
                with self.subTest(idx=idx, members=list(members.keys())):
                    self.assertTrue(accepts(archive_path))

    def test_accepts_single_root_directory_with_single_html(self) -> None:
        cases = (
            {"my_game/play.html": b"<h1>Play</h1>"},
            {"my_game/story.htm": b"<h1>Story</h1>"},
            {
                "my_game/": b"",
                "my_game/play.html": b"<h1>Play</h1>",
                "my_game/style.css": b"body {}",
            },
            {
                "my_game/play.html": b"<h1>Play</h1>",
                "my_game/sub/script.js": b"console.log('hi');",
            },
            {
                "__MACOSX/._my_game": b"apple_double",
                ".DS_Store": b"ds_store",
                "my_game/": b"",
                "my_game/play.html": b"<h1>Play</h1>",
                "my_game/.DS_Store": b"ds_store",
            },
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for idx, members in enumerate(cases):
                archive_path = root / f"single_html_dir_{idx}.zip"
                _write_zip(archive_path, members)
                with self.subTest(idx=idx, members=list(members.keys())):
                    self.assertTrue(accepts(archive_path))

    def test_rejects_unsupported_archives(self) -> None:
        cases: tuple[dict[str, bytes], ...] = (
            # Missing index.html / index.htm and no html files
            {"main.lua": b"return true"},
            {"readme.txt": b"info"},
            # Nested index inside subdirectory of single directory
            {"my_game/nested/index.html": b"<h1>Nested</h1>"},
            # Nested single html inside subdirectory of single directory
            {"my_game/nested/game.html": b"<h1>Nested</h1>"},
            # Multiple non-index html files at root
            {
                "game1.html": b"<h1>1</h1>",
                "game2.html": b"<h1>2</h1>",
            },
            # Multiple non-index html files in single directory
            {
                "my_game/game1.html": b"<h1>1</h1>",
                "my_game/game2.html": b"<h1>2</h1>",
            },
            # Non-index html at root with another html in subdirectory
            {
                "game.html": b"<h1>Root</h1>",
                "sub/other.html": b"<h1>Other</h1>",
            },
            # Non-index html in single dir with another html in subfolder
            {
                "my_game/game.html": b"<h1>Root</h1>",
                "my_game/sub/other.html": b"<h1>Other</h1>",
            },
            # Multiple directories at root
            {
                "dir1/index.html": b"<h1>Hello</h1>",
                "dir2/something.txt": b"hello",
            },
            # File and directory at root
            {
                "my_game/index.html": b"<h1>Hello</h1>",
                "readme.txt": b"info",
            },
            # Directory named index.html
            {
                "index.html/": b"",
                "index.html/file.txt": b"content",
            },
            # Directory named index.html inside root dir
            {
                "my_game/index.html/": b"",
                "my_game/index.html/file.txt": b"content",
            },
            # Empty archive
            {},
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for idx, members in enumerate(cases):
                archive_path = root / f"unsupported_{idx}.zip"
                _write_zip(archive_path, members)
                with self.subTest(idx=idx, members=list(members.keys())):
                    self.assertFalse(accepts(archive_path))

            # Not a zip file
            corrupt = root / "not_a_zip.zip"
            corrupt.write_bytes(b"not an archive")
            self.assertFalse(accepts(corrupt))

            # Nonexistent file
            self.assertFalse(accepts(root / "nonexistent.zip"))

    def test_generates_from_root_archive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "game.zip"
            _write_zip(
                archive_path,
                {
                    "index.html": b"<h1>Root Game</h1>",
                    "style.css": b"body { color: red; }",
                    "assets/logo.png": b"png_data",
                    "__MACOSX/._index.html": b"apple",
                    ".DS_Store": b"ds",
                },
            )
            destination = root / "playable"
            generate(GenerateSpec("1", {}, destination, archive_path))

            self.assertTrue((destination / "index.html").exists())
            self.assertEqual(
                (destination / "index.html").read_text(),
                "<h1>Root Game</h1>",
            )
            self.assertTrue((destination / "style.css").exists())
            self.assertTrue((destination / "assets" / "logo.png").exists())
            self.assertFalse((destination / "__MACOSX").exists())
            self.assertFalse((destination / ".DS_Store").exists())

    def test_generates_from_single_subdirectory_archive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "game.zip"
            _write_zip(
                archive_path,
                {
                    "my_package/": b"",
                    "my_package/index.htm": b"<h1>Subdir Game</h1>",
                    "my_package/game.js": b"console.log('play');",
                    "my_package/data/level.json": b"{}",
                    "my_package/.DS_Store": b"ds",
                    "__MACOSX/._my_package": b"apple",
                },
            )
            destination = root / "playable"
            generate(GenerateSpec("1", {}, destination, archive_path))

            # my_package is unwrapped: index.htm is directly at root
            self.assertFalse((destination / "my_package").exists())
            self.assertTrue((destination / "index.htm").exists())
            self.assertEqual(
                (destination / "index.htm").read_text(),
                "<h1>Subdir Game</h1>",
            )
            self.assertTrue((destination / "game.js").exists())
            self.assertTrue((destination / "data" / "level.json").exists())
            self.assertFalse((destination / "__MACOSX").exists())
            self.assertFalse((destination / ".DS_Store").exists())

    def test_generates_from_root_archive_renames_single_html(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "game.zip"
            _write_zip(
                archive_path,
                {
                    "my_game.html": b"<h1>Renamed Root Game</h1>",
                    "style.css": b"body { color: blue; }",
                    "assets/logo.png": b"png_data",
                },
            )
            destination = root / "playable"
            generate(GenerateSpec("1", {}, destination, archive_path))

            self.assertTrue((destination / "index.html").exists())
            self.assertFalse((destination / "my_game.html").exists())
            self.assertEqual(
                (destination / "index.html").read_text(),
                "<h1>Renamed Root Game</h1>",
            )
            self.assertTrue((destination / "style.css").exists())
            self.assertTrue((destination / "assets" / "logo.png").exists())

    def test_generates_from_single_subdirectory_archive_renames_single_html(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "game.zip"
            _write_zip(
                archive_path,
                {
                    "my_package/": b"",
                    "my_package/story.htm": b"<h1>Renamed Subdir Game</h1>",
                    "my_package/game.js": b"console.log('play');",
                },
            )
            destination = root / "playable"
            generate(GenerateSpec("1", {}, destination, archive_path))

            self.assertFalse((destination / "my_package").exists())
            self.assertTrue((destination / "index.html").exists())
            self.assertFalse((destination / "story.htm").exists())
            self.assertEqual(
                (destination / "index.html").read_text(),
                "<h1>Renamed Subdir Game</h1>",
            )
            self.assertTrue((destination / "game.js").exists())

    def test_generates_into_existing_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "game.zip"
            _write_zip(archive_path, {"index.html": b"<h1>Updated</h1>"})
            destination = root / "playable"
            destination.mkdir()
            (destination / "old.txt").write_text("old file")

            generate(GenerateSpec("1", {}, destination, archive_path))
            self.assertTrue((destination / "index.html").exists())
            self.assertFalse((destination / "old.txt").exists())

    def test_generate_rejects_non_empty_config(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "game.zip"
            _write_zip(archive_path, {"index.html": b"<h1>Game</h1>"})
            destination = root / "playable"
            with self.assertRaises(ValueError):
                generate(
                    GenerateSpec(
                        "1", {"key": "val"}, destination, archive_path
                    )
                )

    def test_generate_rejects_unsupported_archive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "bad.zip"
            _write_zip(archive_path, {"readme.txt": b"no html"})
            destination = root / "playable"
            with self.assertRaises(ValueError):
                generate(GenerateSpec("1", {}, destination, archive_path))


class StaticFilesTaskTests(TestCase):
    game: Game

    @classmethod
    def setUpTestData(cls) -> None:
        cls.game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Static test game",
            creation_time=now(),
        )

    def test_generate_playable_static_files_root(self) -> None:
        with (
            TemporaryDirectory() as media_root,
            TemporaryDirectory() as playables_dir,
        ):
            fs = FileSystemStorage(media_root)
            game_file_path = Path(media_root) / "game.zip"
            _write_zip(
                game_file_path,
                {
                    "index.html": b"<h1>Root Game</h1>",
                    "style.css": b"body {}",
                },
            )

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
                template="static_files",
                template_version="1",
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
                        return_value=True,
                    ) as mock_caddy,
                    patch(
                        "play.tasks.generate_playable_domain",
                        return_value="static-game",
                    ),
                ):
                    generate_playable(playable.pk)

            playable.refresh_from_db()
            self.assertEqual(playable.state, Playable.State.READY)
            self.assertEqual(playable.slug, "static-game")
            mock_caddy.assert_called_once_with(playable)

            dest = Path(playables_dir) / str(playable.pk)
            self.assertTrue((dest / "index.html").exists())
            self.assertEqual(
                (dest / "index.html").read_text(), "<h1>Root Game</h1>"
            )
            self.assertTrue((dest / "style.css").exists())

    def test_generate_playable_static_files_subdir(self) -> None:
        with (
            TemporaryDirectory() as media_root,
            TemporaryDirectory() as playables_dir,
        ):
            fs = FileSystemStorage(media_root)
            game_file_path = Path(media_root) / "game.zip"
            _write_zip(
                game_file_path,
                {
                    "my_sub/index.html": b"<h1>Sub Game</h1>",
                    "my_sub/app.js": b"alert(1)",
                },
            )

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
                template="static_files",
                template_version="1",
                config={},
            )

            with override_settings(
                PLAYABLE_DIR=playables_dir,
                UPLOADS_FS=fs,
                CADDY_ADMIN_URL=None,
            ):
                with (
                    patch("games.models.URL.GetFs", return_value=fs),
                    patch(
                        "play.tasks.generate_playable_domain",
                        return_value="sub-game",
                    ),
                ):
                    generate_playable(playable.pk)

            playable.refresh_from_db()
            self.assertEqual(playable.state, Playable.State.READY)
            dest = Path(playables_dir) / str(playable.pk)
            self.assertFalse((dest / "my_sub").exists())
            self.assertTrue((dest / "index.html").exists())
            self.assertEqual(
                (dest / "index.html").read_text(), "<h1>Sub Game</h1>"
            )
            self.assertTrue((dest / "app.js").exists())
