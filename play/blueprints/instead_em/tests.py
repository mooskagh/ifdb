from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from django.test import SimpleTestCase

from play.blueprint import GenerateSpec

from . import accepts, generate, get_spec

_DEFAULT_HTML = (
    b'<!doctype html>\n<!--    <meta name="gamefile" content="game.zip"> -->\n'
)
_RUNTIME_MEMBER_NAMES = (
    "instead-em/instead-em.data",
    "instead-em/instead-em.html",
    "instead-em/instead-em.js",
    "instead-em/instead-em.wasm",
    "instead-em/loader-em.js",
    "instead-em/loading-bar.css",
    "instead-em/loading-bar.min.js",
    "instead-em/sdl_instead.svg",
    "instead-em/README",
)


def _runtime_entries() -> list[tuple[str, bytes]]:
    return [
        (
            name,
            _DEFAULT_HTML
            if name.endswith("instead-em.html")
            else name.encode(),
        )
        for name in _RUNTIME_MEMBER_NAMES
    ]


def _write_release(assets: Path, version: str = "1.0") -> None:
    runtime = assets / "runtime"
    runtime.mkdir()
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        for name, content in _runtime_entries():
            archive.writestr(name, content)
    (runtime / f"instead-em-{version}.zip").write_bytes(data.getvalue())


def _write_game(game_file: Path, member_name: str = "main.lua") -> None:
    with ZipFile(game_file, "w") as archive:
        archive.writestr(member_name, b"return true")


def _create_fixture(root: Path) -> tuple[Path, Path]:
    assets = root / "assets"
    assets.mkdir()
    (assets / "viewport.css").write_text("canvas { max-width: 100%; }")
    (assets / "viewport.js").write_text("fitCanvas();")
    _write_release(assets)
    game_file = root / "game.zip"
    _write_game(game_file)
    return assets, game_file


class InsteadEmTests(SimpleTestCase):
    def test_versions_are_sorted_and_unrelated_files_are_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            runtime = assets / "runtime"
            runtime.mkdir()
            for version in ("1.10", "1.2", "2.0"):
                (runtime / f"instead-em-{version}.zip").touch()
            (runtime / "instead-em-not-a-version.zip").touch()
            (assets / "README.md").touch()

            with patch("play.blueprints.instead_em.ASSETS_DIR", assets):
                self.assertEqual(
                    get_spec().versions,
                    ["1.2", "1.10", "2.0"],
                )

    def test_accepts_supported_game_archives(self) -> None:
        cases = (
            ("main.lua", "game.zip"),
            ("main3.lua", "game-main3"),
            ("root/main.lua", "game-root"),
            ("root/main3.lua", "game-root-main3"),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for member_name, filename in cases:
                game_file = root / filename
                _write_game(game_file, member_name)
                with self.subTest(member_name=member_name):
                    self.assertTrue(accepts(game_file))

    def test_rejects_unsupported_game_archives(self) -> None:
        cases = (
            ("story.lua", "missing-gamefile.zip"),
            ("root/nested/main.lua", "nested-gamefile.zip"),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for member_name, filename in cases:
                game_file = root / filename
                _write_game(game_file, member_name)
                with self.subTest(member_name=member_name):
                    self.assertFalse(accepts(game_file))

            invalid_file = root / "not-a-zip"
            invalid_file.write_bytes(b"not a zip")
            self.assertFalse(accepts(invalid_file))

    def test_generates_launchable_game(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets, game_file = _create_fixture(root)
            destination = root / "generated"

            with patch("play.blueprints.instead_em.ASSETS_DIR", assets):
                generate(GenerateSpec("1.0", {}, destination, game_file))

            expected = {
                "index.html",
                "game.zip",
                "viewport.css",
                "viewport.js",
            }
            expected.update(
                Path(name).name
                for name in _RUNTIME_MEMBER_NAMES
                if not name.endswith("instead-em.html")
            )
            self.assertEqual(
                {path.name for path in destination.iterdir()}, expected
            )
            index = (destination / "index.html").read_bytes()
            self.assertIn(b'<meta name="gamefile" content="game.zip">', index)
            self.assertIn(b'href="viewport.css"', index)
            self.assertIn(b'src="viewport.js"', index)
            self.assertNotIn(b"instead-em.html", index)
            self.assertEqual(
                (destination / "game.zip").read_bytes(),
                game_file.read_bytes(),
            )

    def test_generates_into_an_empty_existing_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets, game_file = _create_fixture(root)
            destination = root / "generated"
            destination.mkdir()

            with patch("play.blueprints.instead_em.ASSETS_DIR", assets):
                generate(GenerateSpec("1.0", {}, destination, game_file))

            self.assertTrue((destination / "index.html").exists())
