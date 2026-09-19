import tomllib
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from django.test import SimpleTestCase

from play.blueprint import (
    TELEMETRY_SCRIPT,
    Compatibility,
    GenerateSpec,
    discover_blueprints,
)
from play.blueprints.qspider import accepts, generate, get_spec
from play.blueprints.qspider.detection import (
    detect_qsp_mode,
    find_primary_qsp_file,
    is_qsp_header,
    is_tads2_header,
)

_SAMPLE_HTML = b"""<!doctype html>
<html>
  <head>
    <title>qSpider</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
"""

_RUNTIME_FILES = (
    ("index.html", _SAMPLE_HTML),
    ("assets/index.js", b"console.log('qspider');"),
    ("assets/index.css", b"body { margin: 0; }"),
    ("assets/qsp-engine.wasm", b"\x00asm\x01\x00\x00\x00"),
    ("themes/classic.html", b"<div>classic</div>"),
    ("themes/classic.css", b".classic {}"),
    ("themes/aero.html", b"<div>aero</div>"),
    ("themes/aero.css", b".aero {}"),
    ("favicon.ico", b"ico"),
)


def _write_release(assets: Path, filename: str = "qspider-1.3.1.zip") -> None:
    runtime = assets / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        for name, content in _RUNTIME_FILES:
            archive.writestr(name, content)
    (runtime / filename).write_bytes(data.getvalue())


class QSpiderTests(SimpleTestCase):
    def test_versions_are_sorted_and_unrelated_files_are_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            runtime = assets / "runtime"
            runtime.mkdir()
            for version in ("1.1.0", "1.2.0", "1.3.1"):
                (runtime / f"qspider-{version}.zip").touch()
            (runtime / "qspider-player-standalone-1.0.0.zip").touch()
            (runtime / "qspider-not-a-version.zip").touch()
            (runtime / "other-file.txt").touch()

            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                spec = get_spec()
                self.assertEqual(
                    spec.versions,
                    ["1.0.0", "1.1.0", "1.2.0", "1.3.1"],
                )
                self.assertEqual(spec.name, "qSpider")

    def test_accepts_supported_standalone_extensions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for ext in (".qsp", ".aqsp", ".qsps", ".QSP", ".AQSP", ".Qsps"):
                file_path = root / f"game{ext}"
                file_path.write_bytes(
                    b"Q\x00S\x00P\x00G\x00A\x00M\x00E\x00\r\x00\n\x00-data"
                )
                with self.subTest(ext=ext):
                    self.assertEqual(accepts(file_path), Compatibility.FULL)

    def test_accepts_legacy_gam_with_qsp_header_or_tags(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            # Standalone .gam with QSP header
            qsp_gam = root / "game.gam"
            qsp_gam.write_bytes(b"QSPGAME\r\n0.0.6\r\n")
            self.assertEqual(accepts(qsp_gam), Compatibility.FULL)

            # Standalone .gam with password marker
            pw_gam = root / "game_pw.gam"
            pw_gam.write_bytes(b"39\r\nIj\r\n3.0.0\r\n")
            self.assertEqual(accepts(pw_gam), Compatibility.FULL)

            # Standalone .gam with QSP tag
            tagged_gam = root / "tagged.gam"
            tagged_gam.write_bytes(b"random-data")
            self.assertEqual(
                accepts(tagged_gam, tags=["QSP"]), Compatibility.FULL
            )

    def test_rejects_tads_gam_and_unsupported_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            # TADS 2 .gam header
            tads_gam = root / "tads.gam"
            tads_gam.write_bytes(b"TADS2 bin\n\r\x1a\x00v2.2.0")
            self.assertEqual(accepts(tads_gam), Compatibility.NONE)

            # .gam with TADS tag
            tagged_tads = root / "tads_tag.gam"
            tagged_tads.write_bytes(b"data")
            self.assertEqual(
                accepts(tagged_tads, tags=["TADS"]), Compatibility.NONE
            )

            # Nonexistent file
            self.assertEqual(
                accepts(root / "nonexistent.qsp"), Compatibility.NONE
            )

            # Other unsupported files
            for ext in (".txt", ".pdf", ".exe", ""):
                f = root / f"file{ext}"
                f.write_bytes(b"data")
                with self.subTest(ext=ext):
                    self.assertEqual(accepts(f), Compatibility.NONE)

    def test_accepts_archives_with_supported_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                ("game.qsp", None),
                ("game.aqsp", "readme.txt"),
                ("subdir/story.qsps", "subdir/manual.txt"),
                ("GAME.QSP", None),
                ("game.cfg", "story.dat"),
            )
            for i, (game_entry, extra_entry) in enumerate(cases):
                zip_path = root / f"archive_{i}.zip"
                with ZipFile(zip_path, "w") as zf:
                    zf.writestr(game_entry, b"data")
                    if extra_entry:
                        zf.writestr(extra_entry, b"docs")
                with self.subTest(game_entry=game_entry):
                    self.assertEqual(accepts(zip_path), Compatibility.FULL)

    def test_archive_with_gam_respects_tads_vs_qsp(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            # Archive with QSP .gam
            qsp_zip = root / "qsp.zip"
            with ZipFile(qsp_zip, "w") as zf:
                zf.writestr("story.gam", b"QSPGAME\r\n0.0.6")
            self.assertEqual(accepts(qsp_zip), Compatibility.FULL)

            # Archive with TADS .gam
            tads_zip = root / "tads.zip"
            with ZipFile(tads_zip, "w") as zf:
                zf.writestr("story.gam", b"TADS2 bin\n\r\x1a\x00v2.2.0")
            self.assertEqual(accepts(tads_zip), Compatibility.NONE)

            # Archive with TADS tag
            tagged_zip = root / "tagged.zip"
            with ZipFile(tagged_zip, "w") as zf:
                zf.writestr("story.gam", b"some-data")
            self.assertEqual(
                accepts(tagged_zip, tags=["TADS"]), Compatibility.NONE
            )

    def test_detection_helpers(self) -> None:
        self.assertTrue(is_tads2_header(b"TADS2 bin\n\r\x1a\x00v2.2.0"))
        self.assertFalse(is_tads2_header(b"QSPGAME\r\n"))

        self.assertTrue(
            is_qsp_header(
                b"Q\x00S\x00P\x00G\x00A\x00M\x00E\x00\r\x00\n\x002025"
            )
        )
        self.assertTrue(is_qsp_header(b"QSPGAME\r\n0.0.6"))
        self.assertTrue(is_qsp_header(b"39\r\nIj\r\n3.0.0"))
        self.assertFalse(is_qsp_header(b"TADS2 bin\n\r\x1a\x00"))

        # Mode detection
        self.assertEqual(detect_qsp_mode(tags=["AeroQSP"]), "aero")
        self.assertEqual(detect_qsp_mode(Path("game.aqsp")), "aero")
        self.assertEqual(
            detect_qsp_mode(members=["game.qsp", "config.xml"]), "aero"
        )
        self.assertEqual(
            detect_qsp_mode(Path("game.qsp"), members=["game.qsp"]), "classic"
        )

        # Primary file finding
        self.assertEqual(
            find_primary_qsp_file([
                "libs/menu.qsp",
                "libs/screen.qsp",
                "main.qsp",
            ]),
            "main.qsp",
        )
        self.assertEqual(
            find_primary_qsp_file(
                ["test.qsp", "tower.qsp"], preferred_stem="tower"
            ),
            "tower.qsp",
        )

    def test_generates_from_standalone_qsp(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)

            game_file = root / "story.qsp"
            game_file.write_bytes(
                b"Q\x00S\x00P\x00G\x00A\x00M\x00E\x00\r\x00\n\x00binary"
            )
            destination = root / "generated"

            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                generate(
                    GenerateSpec(
                        "1.3.1",
                        {},
                        destination,
                        game_file,
                        title="Тестовая Башня",
                    )
                )

            self.assertTrue(destination.is_dir())
            index_path = destination / "index.html"
            self.assertTrue(index_path.exists())
            index_content = index_path.read_text()
            self.assertIn("<title>Тестовая Башня</title>", index_content)

            game_cfg = destination / "game" / "game.cfg"
            self.assertTrue(game_cfg.exists())
            cfg_data = tomllib.loads(game_cfg.read_text(encoding="utf-8"))
            self.assertIn("game", cfg_data)
            game_entry = cfg_data["game"][0]
            self.assertEqual(game_entry["title"], "Тестовая Башня")
            self.assertEqual(game_entry["file"], "story.qsp")
            self.assertEqual(game_entry["mode"], "classic")

            installed_game = destination / "game" / "story.qsp"
            self.assertTrue(installed_game.exists())
            self.assertEqual(
                installed_game.read_bytes(), game_file.read_bytes()
            )

    def test_generates_from_archive_and_flattens_single_dir(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)

            archive_path = root / "game_archive.zip"
            with ZipFile(archive_path, "w") as zf:
                zf.writestr("RootFolder/main.qsp", b"qsp-content")
                zf.writestr("RootFolder/images/pic.png", b"png-data")
                zf.writestr("RootFolder/readme.txt", b"docs")

            destination = root / "generated"
            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                generate(GenerateSpec("1.3.1", {}, destination, archive_path))

            # Verify single dir was flattened
            installed_game = destination / "game" / "main.qsp"
            self.assertTrue(installed_game.exists())
            installed_pic = destination / "game" / "images" / "pic.png"
            self.assertTrue(installed_pic.exists())

            game_cfg = destination / "game" / "game.cfg"
            cfg_data = tomllib.loads(game_cfg.read_text(encoding="utf-8"))
            self.assertEqual(cfg_data["game"][0]["file"], "main.qsp")

    def test_generates_aero_mode(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)

            archive_path = root / "aero_game.zip"
            with ZipFile(archive_path, "w") as zf:
                zf.writestr("game.qsp", b"qsp-content")
                zf.writestr(
                    "config.xml",
                    b'<game width="800" height="600"></game>',
                )

            destination = root / "generated"
            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                generate(GenerateSpec("1.3.1", {}, destination, archive_path))

            game_cfg = destination / "game" / "game.cfg"
            cfg_data = tomllib.loads(game_cfg.read_text(encoding="utf-8"))
            self.assertEqual(cfg_data["game"][0]["mode"], "aero")

    def test_generates_respects_config_overrides(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)

            game_file = root / "story.qsp"
            game_file.write_bytes(b"qsp-data")
            destination = root / "generated"

            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                generate(
                    GenerateSpec(
                        "1.3.1",
                        {
                            "mode": "aero",
                            "title": "Override Title",
                            "save_slots": 5,
                        },
                        destination,
                        game_file,
                    )
                )

            game_cfg = destination / "game" / "game.cfg"
            cfg_data = tomllib.loads(game_cfg.read_text(encoding="utf-8"))
            game_entry = cfg_data["game"][0]
            self.assertEqual(game_entry["mode"], "aero")
            self.assertEqual(game_entry["title"], "Override Title")
            self.assertEqual(game_entry["save_slots"], 5)

    def test_generates_validates_config(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)
            game_file = root / "story.qsp"
            game_file.write_bytes(b"qsp")
            destination = root / "generated"

            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                # Invalid config key
                with self.assertRaises(ValueError):
                    generate(
                        GenerateSpec(
                            "1.3.1", {"invalid_key": 1}, destination, game_file
                        )
                    )

                # Invalid mode
                with self.assertRaises(ValueError):
                    generate(
                        GenerateSpec(
                            "1.3.1",
                            {"mode": "unknown_mode"},
                            destination,
                            game_file,
                        )
                    )

                # Invalid save_slots
                with self.assertRaises(ValueError):
                    generate(
                        GenerateSpec(
                            "1.3.1", {"save_slots": -1}, destination, game_file
                        )
                    )

                # Unknown version
                with self.assertRaises(ValueError):
                    generate(GenerateSpec("9.9.9", {}, destination, game_file))

    def test_discovered_by_discover_blueprints(self) -> None:
        blueprints = discover_blueprints()
        names = [info.name for info in blueprints]
        self.assertIn("qspider", names)
        qspider_info = next(
            info for info in blueprints if info.name == "qspider"
        )
        spec = qspider_info.blueprint.get_spec()
        self.assertEqual(spec.name, "qSpider")
        self.assertIn("1.3.1", spec.versions)

    def test_real_qspider_asset_can_be_generated(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            game_file = root / "sample.qsp"
            game_file.write_bytes(
                b"Q\x00S\x00P\x00G\x00A\x00M\x00E\x00\r\x00\n\x00binary-test"
            )
            destination = root / "generated"

            generate(
                GenerateSpec(
                    "1.3.1",
                    {},
                    destination,
                    game_file,
                    title="Real Asset Test",
                )
            )

            self.assertTrue((destination / "index.html").is_file())
            self.assertTrue((destination / "assets").is_dir())
            self.assertTrue((destination / "themes").is_dir())
            self.assertTrue((destination / "game" / "sample.qsp").is_file())
            self.assertTrue((destination / "game" / "game.cfg").is_file())
            index_content = (destination / "index.html").read_text(
                encoding="utf-8"
            )
            self.assertIn(TELEMETRY_SCRIPT, index_content)
            self.assertIn("<title>Real Asset Test</title>", index_content)

    def test_case_insensitive_aliases_created(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)

            archive_path = root / "game_with_assets.zip"
            # Encode a sample QSP file that references Content/Way01.jpg
            # QSP encryption is (ord(c) - 5) % 65536
            qsp_code = "'<img src=\"Content/Way01.jpg\" />'\r\n"
            enc_code = "".join(chr((ord(c) - 5) % 65536) for c in qsp_code)
            qsp_content = (
                b"Q\x00S\x00P\x00G\x00A\x00M\x00E\x00\r\x00\n\x00"
                + enc_code.encode("utf-16le")
            )

            with ZipFile(archive_path, "w") as zf:
                zf.writestr("game.qsp", qsp_content)
                zf.writestr("Content/way01.JPG", b"jpeg-data")
                zf.writestr("Content/Bark.MP3", b"mp3-data")
                zf.writestr("Sounds/intro.wav", b"wav-data")

            destination = root / "output"
            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                generate(
                    GenerateSpec(
                        version="1.3.1",
                        config={},
                        destination=destination,
                        game_file=archive_path,
                        title="Case Test",
                    )
                )

            game_dir = destination / "game"
            # 1. Lowercase directory symlinks:
            # sounds -> Sounds, content -> Content
            self.assertTrue((game_dir / "sounds").is_dir())
            self.assertTrue((game_dir / "content").is_dir())

            # 2. Lowercase extension and full lowercase symlinks for files:
            self.assertTrue((game_dir / "Content" / "way01.jpg").is_file())
            self.assertTrue((game_dir / "Content" / "way01.jpg").is_symlink())
            self.assertEqual(
                (game_dir / "Content" / "way01.jpg").read_bytes(), b"jpeg-data"
            )

            # Bark.mp3 (lower extension) and bark.mp3 (full lowercase)
            self.assertTrue((game_dir / "Content" / "Bark.mp3").is_file())
            self.assertTrue((game_dir / "Content" / "Bark.mp3").is_symlink())
            self.assertTrue((game_dir / "Content" / "bark.mp3").is_file())
            self.assertTrue((game_dir / "Content" / "bark.mp3").is_symlink())

            # 3. Referenced path Content/Way01.jpg created via QSP path scan
            self.assertTrue((game_dir / "Content" / "Way01.jpg").is_file())
            self.assertTrue((game_dir / "Content" / "Way01.jpg").is_symlink())

            # 4. Access via lowercased directory symlink
            self.assertTrue((game_dir / "content" / "way01.jpg").is_file())
            self.assertEqual(
                (game_dir / "content" / "way01.jpg").read_bytes(), b"jpeg-data"
            )
            self.assertTrue((game_dir / "sounds" / "intro.wav").is_file())
            self.assertEqual(
                (game_dir / "sounds" / "intro.wav").read_bytes(), b"wav-data"
            )

    def test_dich_zip_case_insensitivity(self) -> None:
        dich_path = Path("files/uploads/Дичь.zip")
        if not dich_path.is_file():
            self.skipTest("Дичь.zip not available in files/uploads/")

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "dich_playable"
            generate(
                GenerateSpec(
                    version="1.3.1",
                    config={},
                    destination=destination,
                    game_file=dich_path,
                    title="Дичь",
                )
            )

            content_dir = destination / "game" / "content"
            self.assertTrue(content_dir.is_dir())

            # Original file exists
            self.assertTrue((content_dir / "way01.JPG").is_file())
            # Lowercase symlink exists and points to way01.JPG
            self.assertTrue((content_dir / "way01.jpg").is_file())
            self.assertTrue((content_dir / "way01.jpg").is_symlink())
            self.assertEqual(
                (content_dir / "way01.jpg").resolve(),
                (content_dir / "way01.JPG").resolve(),
            )

            # Bark.mp3 has bark.mp3 symlink
            self.assertTrue((content_dir / "bark.mp3").is_file())
            self.assertTrue((content_dir / "bark.mp3").is_symlink())

    def test_aero_utf16_config_xml_dimensions_and_normalization(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)

            # Create an .aqsp with UTF-16LE config.xml
            aqsp_path = root / "witch.aqsp"
            utf16_xml = (
                b"\xff\xfe"
                + '<game width="1000" height="700" title="В тени"/>\n'.encode(
                    "utf-16le"
                )
            )
            with ZipFile(aqsp_path, "w") as zf:
                zf.writestr("witch.qsp", b"QSPGAME\r\n")
                zf.writestr("config.xml", utf16_xml)

            destination = root / "generated"
            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                generate(
                    GenerateSpec(
                        version="1.3.1",
                        config={},
                        destination=destination,
                        game_file=aqsp_path,
                        title="В тени",
                    )
                )

            # Check game.cfg
            cfg_path = destination / "game" / "game.cfg"
            self.assertTrue(cfg_path.is_file())
            cfg_data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
            game = cfg_data["game"][0]
            self.assertEqual(game["mode"], "aero")
            self.assertIn("aero", game)
            self.assertEqual(game["aero"]["width"], 1000)
            self.assertEqual(game["aero"]["height"], 700)

            # Check config.xml on disk is normalized to UTF-8
            # without BOM or nulls
            xml_on_disk = destination / "game" / "config.xml"
            self.assertTrue(xml_on_disk.is_file())
            raw_bytes = xml_on_disk.read_bytes()
            self.assertFalse(raw_bytes.startswith(b"\xff\xfe"))
            self.assertFalse(raw_bytes.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\x00", raw_bytes)
            self.assertIn(
                'width="1000"', xml_on_disk.read_text(encoding="utf-8")
            )

    def test_aero_utf8_bom_and_cp1251_config_xml(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)

            # 1. UTF-8 with BOM
            aqsp_bom = root / "game_bom.aqsp"
            with ZipFile(aqsp_bom, "w") as zf:
                zf.writestr("game.qsp", b"QSPGAME\r\n")
                zf.writestr(
                    "config.xml",
                    b"\xef\xbb\xbf" + b'<game width="900" height="680"/>',
                )

            dest_bom = root / "dest_bom"
            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                generate(
                    GenerateSpec(
                        version="1.3.1",
                        config={},
                        destination=dest_bom,
                        game_file=aqsp_bom,
                        title="BOM Game",
                    )
                )

            cfg_data = tomllib.loads(
                (dest_bom / "game" / "game.cfg").read_text(encoding="utf-8")
            )
            self.assertEqual(cfg_data["game"][0]["aero"]["width"], 900)
            self.assertEqual(cfg_data["game"][0]["aero"]["height"], 680)

            # 2. CP1251 encoding
            aqsp_cp = root / "game_cp.aqsp"
            with ZipFile(aqsp_cp, "w") as zf:
                zf.writestr("game.qsp", b"QSPGAME\r\n")
                zf.writestr(
                    "CONFIG.XML",
                    '<game width="1024" height="768" title="Тест"/>'.encode(
                        "cp1251"
                    ),
                )

            dest_cp = root / "dest_cp"
            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                generate(
                    GenerateSpec(
                        version="1.3.1",
                        config={},
                        destination=dest_cp,
                        game_file=aqsp_cp,
                        title="CP Game",
                    )
                )

            cfg_data_cp = tomllib.loads(
                (dest_cp / "game" / "game.cfg").read_text(encoding="utf-8")
            )
            self.assertEqual(cfg_data_cp["game"][0]["aero"]["width"], 1024)
            self.assertEqual(cfg_data_cp["game"][0]["aero"]["height"], 768)
            # Lowercase config.xml symlink exists
            self.assertTrue((dest_cp / "game" / "config.xml").is_file())

    def test_aero_explicit_dimensions_override(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)

            aqsp_path = root / "game.aqsp"
            with ZipFile(aqsp_path, "w") as zf:
                zf.writestr("game.qsp", b"QSPGAME\r\n")
                zf.writestr("config.xml", b'<game width="800" height="600"/>')

            destination = root / "generated"
            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                generate(
                    GenerateSpec(
                        version="1.3.1",
                        config={"width": 1280, "height": 720},
                        destination=destination,
                        game_file=aqsp_path,
                        title="Override Game",
                    )
                )

            cfg_data = tomllib.loads(
                (destination / "game" / "game.cfg").read_text(encoding="utf-8")
            )
            self.assertEqual(cfg_data["game"][0]["aero"]["width"], 1280)
            self.assertEqual(cfg_data["game"][0]["aero"]["height"], 720)

    def test_aero_invalid_dimensions_raise_error(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            _write_release(assets)
            game_file = root / "game.qsp"
            game_file.write_bytes(b"QSPGAME\r\n")

            with patch("play.blueprints.qspider.ASSETS_DIR", assets):
                with self.assertRaises(ValueError):
                    generate(
                        GenerateSpec(
                            version="1.3.1",
                            config={"width": -10},
                            destination=root / "dest",
                            game_file=game_file,
                            title="Invalid",
                        )
                    )
                with self.assertRaises(ValueError):
                    generate(
                        GenerateSpec(
                            version="1.3.1",
                            config={"height": "invalid"},
                            destination=root / "dest",
                            game_file=game_file,
                            title="Invalid",
                        )
                    )

    def test_real_witch_aqsp_generates_correct_dimensions(self) -> None:
        witch_path = Path("files/backups/witch.1.1.aqsp")
        if not witch_path.is_file():
            self.skipTest("witch.1.1.aqsp not available in files/backups/")

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "witch_playable"
            generate(
                GenerateSpec(
                    version="1.3.1",
                    config={},
                    destination=destination,
                    game_file=witch_path,
                    title="В тени Сумрачного леса",
                )
            )

            cfg_data = tomllib.loads(
                (destination / "game" / "game.cfg").read_text(encoding="utf-8")
            )
            game = cfg_data["game"][0]
            self.assertEqual(game["mode"], "aero")
            self.assertEqual(game["aero"]["width"], 1000)
            self.assertEqual(game["aero"]["height"], 700)

            # Verify config.xml is clean UTF-8
            raw_xml = (destination / "game" / "config.xml").read_bytes()
            self.assertFalse(raw_xml.startswith(b"\xff\xfe"))
            self.assertNotIn(b"\x00", raw_xml)
            text_xml = (destination / "game" / "config.xml").read_text(
                encoding="utf-8"
            )
            self.assertIn("1000", text_xml)
            self.assertIn("700", text_xml)
