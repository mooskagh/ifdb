import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from django.test import SimpleTestCase

from play.blueprint import (
    TELEMETRY_SCRIPT,
    GenerateSpec,
    discover_blueprints,
)
from play.blueprints.instead_js import accepts, generate, get_spec

_SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>INSTEAD.js</title>
    <script>
        var INSTEADjs = {
            mute: true,
            preload: true
        };
    </script>
</head>
<body>
    <div id="manager"></div>
    <div id="instead"></div>
</body>
</html>
"""


def _write_release_archive(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as zf:
        zf.writestr("instead-js/index.html", _SAMPLE_HTML)
        zf.writestr("instead-js/instead.js", "console.log('instead');")
        zf.writestr("instead-js/style.css", "body { margin: 0; }")
        zf.writestr("instead-js/stead3.json", "{}")
        zf.writestr("instead-js/themes/default/theme.ini", "name = default")
        zf.writestr("instead-js/games/games_list.json", "{}")
        zf.writestr("instead-js/games/tutorial3/main.lua", "-- tutorial")
        zf.writestr("instead-js/README", "readme")


def _write_game_zip(path: Path, member_name: str, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as zf:
        zf.writestr(member_name, content)


class InsteadJsTests(SimpleTestCase):
    def test_discovered_by_discover_blueprints(self) -> None:
        blueprints = {b.name: b.blueprint for b in discover_blueprints()}
        self.assertIn("instead_js", blueprints)
        self.assertEqual(
            blueprints["instead_js"].get_spec().name, "INSTEAD.js"
        )

    def test_versions_sorting(self) -> None:
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            runtime = assets / "runtime"
            runtime.mkdir()
            for version in ("1.10", "1.2", "2.5.0"):
                (runtime / f"instead-js-{version}.zip").touch()
            (runtime / "instead-js-invalid.zip").touch()

            with patch("play.blueprints.instead_js.ASSETS_DIR", assets):
                self.assertEqual(get_spec().versions, ["1.2", "1.10", "2.5.0"])

    def test_accepts(self) -> None:
        cases = (
            ("main.lua", True),
            ("main3.lua", True),
            ("mygame/main.lua", True),
            ("mygame/main3.lua", True),
            ("other.lua", False),
            ("nested/sub/main.lua", False),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for idx, (member, expected) in enumerate(cases):
                game_file = root / f"game_{idx}.zip"
                _write_game_zip(game_file, member, "return true")
                with self.subTest(member=member):
                    self.assertEqual(accepts(game_file), expected)

            not_zip = root / "not_zip.txt"
            not_zip.write_text("hello")
            self.assertFalse(accepts(not_zip))

    def test_generates_stead3_game(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            release_zip = assets / "runtime" / "instead-js-2.5.0.zip"
            _write_release_archive(release_zip)

            game_file = root / "game.zip"
            with ZipFile(game_file, "w") as zf:
                zf.writestr(
                    "main3.lua",
                    (
                        "$Name: Space Odyssey$\n"
                        "$Author: Arthur$\n"
                        "$Version: 1.0$\n"
                    ),
                )
                zf.writestr("img/intro.png", b"\x89PNG")
                zf.writestr("theme.ini", "name = custom")

            destination = root / "output"
            spec = GenerateSpec(
                version="2.5.0",
                config={"mute": False},
                destination=destination,
                game_file=game_file,
                title="Space Odyssey Deluxe",
            )

            with patch("play.blueprints.instead_js.ASSETS_DIR", assets):
                result = generate(spec)

            self.assertIsNotNone(result)
            self.assertEqual(result.player_name, "INSTEAD.js")
            self.assertEqual(
                result.player_url, "https://github.com/instead-hub/instead-js"
            )

            index_html = (destination / "index.html").read_text(
                encoding="utf-8"
            )
            self.assertIn(TELEMETRY_SCRIPT, index_html)
            self.assertIn(
                "<title>Space Odyssey Deluxe - INSTEAD.js</title>", index_html
            )
            self.assertIn("mute: false", index_html)

            # Runtime files present, tutorial3 excluded
            self.assertTrue((destination / "instead.js").is_file())
            self.assertTrue((destination / "style.css").is_file())
            self.assertTrue((destination / "stead3.json").is_file())
            self.assertTrue(
                (destination / "themes" / "default" / "theme.ini").is_file()
            )
            self.assertFalse((destination / "games" / "tutorial3").exists())
            self.assertFalse((destination / "README").exists())

            # Game files unpacked into games/game
            game_dir = destination / "games" / "game"
            self.assertTrue((game_dir / "main3.lua").is_file())
            self.assertTrue((game_dir / "img" / "intro.png").is_file())
            self.assertTrue((game_dir / "theme.ini").is_file())

            # Manifest generated correctly
            manifest_file = destination / "games" / "games_list.json"
            self.assertTrue(manifest_file.is_file())
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertIn("game", manifest)
            game_entry = manifest["game"]
            self.assertEqual(game_entry["name"], "Space Odyssey Deluxe")
            self.assertEqual(game_entry["details"]["author"], "Arthur")
            self.assertEqual(game_entry["details"]["version"], "1.0")
            self.assertEqual(game_entry["stead"], 3)
            self.assertTrue(game_entry["theme"])
            self.assertEqual(game_entry["preload"], ["img/intro.png"])

    def test_generates_stead2_game_with_flattening(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            release_zip = assets / "runtime" / "instead-js-2.5.0.zip"
            _write_release_archive(release_zip)

            game_file = root / "game.zip"
            with ZipFile(game_file, "w") as zf:
                zf.writestr(
                    "nested_folder/main.lua",
                    "$Name(ru): Таинственный остров$\n",
                )

            destination = root / "output"
            spec = GenerateSpec(
                version="2.5.0",
                config={},
                destination=destination,
                game_file=game_file,
            )

            with patch("play.blueprints.instead_js.ASSETS_DIR", assets):
                generate(spec)

            manifest_file = destination / "games" / "games_list.json"
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["game"]["name"], "Таинственный остров")
            self.assertEqual(manifest["game"]["stead"], 2)
            self.assertFalse(manifest["game"]["theme"])
            self.assertEqual(manifest["game"]["preload"], [])

    def test_rejects_invalid_config(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            release_zip = assets / "runtime" / "instead-js-2.5.0.zip"
            _write_release_archive(release_zip)

            game_file = root / "game.zip"
            _write_game_zip(game_file, "main.lua", "return true")

            spec = GenerateSpec(
                version="2.5.0",
                config={"bad_key": 123},
                destination=root / "out",
                game_file=game_file,
            )
            with patch("play.blueprints.instead_js.ASSETS_DIR", assets):
                with self.assertRaises(ValueError) as ctx:
                    generate(spec)
                self.assertIn("Unsupported config keys", str(ctx.exception))

    def test_generates_with_bundled_assets(self) -> None:
        self.assertIn("2.5.0", get_spec().versions)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            game_file = root / "game.zip"
            with ZipFile(game_file, "w") as zf:
                zf.writestr(
                    "main3.lua",
                    "$Name: Bundled Test$\n$Author: Test$\n",
                )

            destination = root / "output"
            spec = GenerateSpec(
                version="2.5.0",
                config={},
                destination=destination,
                game_file=game_file,
                title="Bundled Test",
            )
            result = generate(spec)
            self.assertIsNotNone(result)
            self.assertEqual(result.player_name, "INSTEAD.js")
            index_html = (destination / "index.html").read_text(
                encoding="utf-8"
            )
            self.assertIn(TELEMETRY_SCRIPT, index_html)
            self.assertTrue(
                (destination / "games" / "games_list.json").is_file()
            )
            self.assertTrue(
                (destination / "games" / "game" / "main3.lua").is_file()
            )
