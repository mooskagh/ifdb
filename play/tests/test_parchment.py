from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from django.test import SimpleTestCase

from play.blueprint import GenerateSpec, discover_blueprints
from play.blueprints.parchment import (
    accepts,
    generate,
    get_spec,
)

_SAMPLE_PARCHMENT_HTML = b"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Parchment 2026.8.23</title>
    <script>parchment_options = {
  "single_file": 1
}</script>
<script>/* interpreter code */</script>
</head>
<body></body>
</html>"""


def _write_release(
    assets: Path, filename: str = "parchment-single-file-2026-08-23.zip"
) -> None:
    runtime = assets / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr("parchment.html", _SAMPLE_PARCHMENT_HTML)
    (runtime / filename).write_bytes(data.getvalue())


def _create_fixture(
    root: Path,
) -> tuple[Path, Path]:
    assets = root / "assets"
    assets.mkdir()
    _write_release(assets)
    game_file = root / "story.z5"
    game_file.write_bytes(b"\x05\x00sample-zcode")
    return assets, game_file


class ParchmentTests(SimpleTestCase):
    def test_versions_are_sorted_and_unrelated_files_are_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            runtime = assets / "runtime"
            runtime.mkdir()
            for version in ("2026-08-01", "2026-08-23", "2027-01-01"):
                (runtime / f"parchment-single-file-{version}.zip").touch()
            (runtime / "parchment-not-a-version.zip").touch()
            (runtime / "other-file.txt").touch()

            with patch("play.blueprints.parchment.ASSETS_DIR", assets):
                self.assertEqual(
                    get_spec().versions,
                    ["2026-08-01", "2026-08-23", "2027-01-01"],
                )
                self.assertEqual(get_spec().name, "Parchment")

    def test_accepts_supported_standalone_extensions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for ext in (
                ".z3",
                ".z4",
                ".z5",
                ".z8",
                ".zblorb",
                ".zlb",
                ".ulx",
                ".gblorb",
                ".glb",
                ".Z5",
                ".ZBLORB",
                ".Gblorb",
                ".ULX",
                ".Glb",
            ):
                file_path = root / f"game{ext}"
                file_path.write_bytes(b"game-data")
                with self.subTest(ext=ext):
                    self.assertTrue(accepts(file_path))

    def test_accepts_archives_with_supported_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                ("game.z5", None),
                ("game.ulx", "readme.txt"),
                ("subdir/story.gblorb", "subdir/manual.pdf"),
                ("GAME.ZBLORB", None),
            )
            for i, (game_entry, extra_entry) in enumerate(cases):
                zip_path = root / f"archive_{i}.zip"
                with ZipFile(zip_path, "w") as zf:
                    zf.writestr(game_entry, b"game-data")
                    if extra_entry:
                        zf.writestr(extra_entry, b"docs")
                with self.subTest(game_entry=game_entry):
                    self.assertTrue(accepts(zip_path))

    def test_rejects_unsupported_files_and_archives(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            # Unsupported standalone files
            for ext in (".txt", ".pdf", ".exe", ".t3", ".gam", ""):
                file_path = root / f"file{ext}"
                file_path.write_bytes(b"data")
                with self.subTest(ext=ext):
                    self.assertFalse(accepts(file_path))

            # Nonexistent file
            self.assertFalse(accepts(root / "nonexistent.z5"))

            # Archive with only unsupported files
            unsupported_zip = root / "unsupported.zip"
            with ZipFile(unsupported_zip, "w") as zf:
                zf.writestr("readme.txt", b"just text")
                zf.writestr("walkthrough.pdf", b"pdf data")
            self.assertFalse(accepts(unsupported_zip))

            # Archive with macOS metadata files only
            macos_zip = root / "macos.zip"
            with ZipFile(macos_zip, "w") as zf:
                zf.writestr("__MACOSX/._story.z5", b"resource fork")
                zf.writestr(".DS_Store", b"ds store")
            self.assertFalse(accepts(macos_zip))

            # Corrupted archive
            bad_zip = root / "bad.zip"
            bad_zip.write_bytes(b"not a valid zip content")
            self.assertFalse(accepts(bad_zip))

    def test_generates_from_standalone_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets, game_file = _create_fixture(root)
            destination = root / "generated"

            with patch("play.blueprints.parchment.ASSETS_DIR", assets):
                generate(
                    GenerateSpec("2026-08-23", {}, destination, game_file)
                )

            self.assertTrue(destination.is_dir())
            index_path = destination / "index.html"
            self.assertTrue(index_path.exists())
            index_content = index_path.read_text()
            self.assertIn('"story": "game.z5"', index_content)
            self.assertIn('"single_file": 1', index_content)

            installed_game = destination / "game.z5"
            self.assertTrue(installed_game.exists())
            self.assertEqual(
                installed_game.read_bytes(), game_file.read_bytes()
            )

    def test_generates_from_standalone_file_uppercase_extension(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            _write_release(assets)
            game_file = root / "ADVENT.ZBLORB"
            game_file.write_bytes(b"zblorb-data")
            destination = root / "generated"

            with patch("play.blueprints.parchment.ASSETS_DIR", assets):
                generate(
                    GenerateSpec("2026-08-23", {}, destination, game_file)
                )

            installed_game = destination / "game.zblorb"
            self.assertTrue(installed_game.exists())
            index_content = (destination / "index.html").read_text()
            self.assertIn('"story": "game.zblorb"', index_content)

    def test_generates_from_archive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            _write_release(assets)

            archive_path = root / "game_bundle.zip"
            game_content = b"ulx-game-data"
            with ZipFile(archive_path, "w") as zf:
                zf.writestr("bundle/nested/STORY.ULX", game_content)
                zf.writestr("bundle/readme.txt", b"instructions")
                zf.writestr("bundle/cover.png", b"image data")

            destination = root / "generated"
            with patch("play.blueprints.parchment.ASSETS_DIR", assets):
                generate(
                    GenerateSpec("2026-08-23", {}, destination, archive_path)
                )

            installed_game = destination / "game.ulx"
            self.assertTrue(installed_game.exists())
            self.assertEqual(installed_game.read_bytes(), game_content)

            index_content = (destination / "index.html").read_text()
            self.assertIn('"story": "game.ulx"', index_content)

    def test_generates_into_existing_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets, game_file = _create_fixture(root)
            destination = root / "generated"
            destination.mkdir()
            (destination / "old_file.txt").write_text("old content")

            with patch("play.blueprints.parchment.ASSETS_DIR", assets):
                generate(
                    GenerateSpec("2026-08-23", {}, destination, game_file)
                )

            self.assertTrue((destination / "index.html").exists())
            self.assertTrue((destination / "game.z5").exists())
            self.assertFalse((destination / "old_file.txt").exists())

    def test_generate_rejects_config(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets, game_file = _create_fixture(root)
            destination = root / "generated"

            with patch("play.blueprints.parchment.ASSETS_DIR", assets):
                with self.assertRaises(ValueError):
                    generate(
                        GenerateSpec(
                            "2026-08-23",
                            {"key": "val"},
                            destination,
                            game_file,
                        )
                    )

    def test_generate_unknown_version(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets, game_file = _create_fixture(root)
            destination = root / "generated"

            with patch("play.blueprints.parchment.ASSETS_DIR", assets):
                with self.assertRaises(ValueError):
                    generate(
                        GenerateSpec("9999.0", {}, destination, game_file)
                    )

    def test_generate_archive_without_game_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            _write_release(assets)
            empty_zip = root / "empty.zip"
            with ZipFile(empty_zip, "w") as zf:
                zf.writestr("readme.txt", b"hello")
            destination = root / "generated"

            with patch("play.blueprints.parchment.ASSETS_DIR", assets):
                with self.assertRaises(ValueError):
                    generate(
                        GenerateSpec("2026-08-23", {}, destination, empty_zip)
                    )

    def test_discovered_by_discover_blueprints(self) -> None:
        blueprints = discover_blueprints()
        names = {info.name for info in blueprints}
        self.assertIn("parchment", names)
        parchment_info = next(
            info for info in blueprints if info.name == "parchment"
        )
        spec = parchment_info.blueprint.get_spec()
        self.assertEqual(spec.name, "Parchment")
        self.assertIn("2026-08-23", spec.versions)

    def test_real_parchment_asset_can_be_generated(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            game_file = root / "test.z5"
            game_file.write_bytes(b"\x05sample")
            destination = root / "generated"

            generate(GenerateSpec("2026-08-23", {}, destination, game_file))

            index_path = destination / "index.html"
            self.assertTrue(index_path.exists())
            html = index_path.read_text()
            self.assertIn('"story": "game.z5"', html)
            self.assertIn('"single_file": 1', html)
            self.assertTrue((destination / "game.z5").exists())
