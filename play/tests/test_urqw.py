import json
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
from play.blueprints.urqw import accepts, generate, get_spec
from play.blueprints.urqw.detection import (
    detect_encoding,
    detect_urq_mode,
)


class UrqWTests(SimpleTestCase):
    def test_versions_are_sorted_and_unrelated_files_are_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            assets = Path(directory)
            runtime = assets / "runtime"
            runtime.mkdir()
            for version in ("2026-08-01", "2026-08-21", "2027-01-01"):
                (runtime / f"urqw-{version}.zip").touch()
            (runtime / "urqw-not-a-version.zip").touch()
            (runtime / "other-file.txt").touch()

            with patch("play.blueprints.urqw.ASSETS_DIR", assets):
                spec = get_spec()
                self.assertEqual(
                    spec.versions,
                    ["2026-08-01", "2026-08-21", "2027-01-01"],
                )
                self.assertEqual(spec.name, "UrqW")

    def test_accepts_supported_standalone_extensions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for ext in (
                ".qst",
                ".qs1",
                ".qs2",
                ".qsz",
                ".QST",
                ".QSZ",
                ".Qs1",
            ):
                file_path = root / f"game{ext}"
                file_path.write_bytes(b"#start\nHello URQ")
                with self.subTest(ext=ext):
                    self.assertEqual(accepts(file_path), Compatibility.FULL)

    def test_accepts_archives_with_supported_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                ("game.qst", None),
                ("game.qsz", "readme.txt"),
                ("subdir/story.qs1", "subdir/manual.txt"),
                ("GAME.QST", None),
            )
            for i, (game_entry, extra_entry) in enumerate(cases):
                zip_path = root / f"archive_{i}.zip"
                with ZipFile(zip_path, "w") as zf:
                    zf.writestr(game_entry, b"#start\nHello world")
                    if extra_entry:
                        zf.writestr(extra_entry, b"docs")
                with self.subTest(game_entry=game_entry):
                    self.assertEqual(accepts(zip_path), Compatibility.FULL)

    def test_accepts_fireurq_tags_and_syntax(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            # Standalone file with FireURQ tag
            game_file = root / "game.qst"
            game_file.write_bytes(b"#start\nRegular game")
            self.assertEqual(
                accepts(game_file, tags=["FireURQ"]),
                Compatibility.PARTIAL,
            )

            # Archive with FireURQ tag
            zip_file = root / "game.zip"
            with ZipFile(zip_file, "w") as zf:
                zf.writestr("story.qst", b"#start\nRegular game")
            self.assertEqual(
                accepts(zip_file, tags=["platform:FireURQ"]),
                Compatibility.PARTIAL,
            )

            # Standalone file with FireURQ syntax (no tags)
            fireurq_syntax_file = root / "fire.qst"
            fireurq_syntax_file.write_bytes(
                b"#start\n{color:red}Red text{/color}"
            )
            self.assertEqual(
                accepts(fireurq_syntax_file),
                Compatibility.PARTIAL,
            )

            # Archive with FireURQ syntax inside
            fireurq_zip = root / "fire.zip"
            with ZipFile(fireurq_zip, "w") as zf:
                zf.writestr("fire.qst", b"#start\ntextpane_color = 1")
            self.assertEqual(
                accepts(fireurq_zip),
                Compatibility.PARTIAL,
            )

    def test_rejects_unsupported_files_and_archives(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            # Unsupported standalone files
            for ext in (".txt", ".pdf", ".exe", ".z5", ".lua", ""):
                file_path = root / f"file{ext}"
                file_path.write_bytes(b"data")
                with self.subTest(ext=ext):
                    self.assertEqual(accepts(file_path), Compatibility.NONE)

            # Nonexistent file
            self.assertEqual(
                accepts(root / "nonexistent.qst"), Compatibility.NONE
            )

            # Archive without URQ files
            unsupported_zip = root / "unsupported.zip"
            with ZipFile(unsupported_zip, "w") as zf:
                zf.writestr("readme.txt", b"just text")
            self.assertEqual(accepts(unsupported_zip), Compatibility.NONE)

            # Archive with macOS metadata only
            macos_zip = root / "macos.zip"
            with ZipFile(macos_zip, "w") as zf:
                zf.writestr("__MACOSX/._story.qst", b"resource fork")
            self.assertEqual(accepts(macos_zip), Compatibility.NONE)

            # Corrupted archive
            bad_zip = root / "bad.zip"
            bad_zip.write_bytes(b"not a valid zip")
            self.assertEqual(accepts(bad_zip), Compatibility.NONE)

    def test_detect_encoding(self) -> None:
        # UTF-8 with BOM
        bom_utf8 = "\ufeff#start\nПривет мир".encode("utf-8")
        self.assertEqual(detect_encoding(bom_utf8), "UTF-8")

        # UTF-8 plain
        plain_utf8 = "#start\nПривет мир".encode("utf-8")
        self.assertEqual(detect_encoding(plain_utf8), "UTF-8")

        # Windows-1251
        cp1251_bytes = "#start\nПривет мир".encode("cp1251")
        self.assertEqual(detect_encoding(cp1251_bytes), "CP1251")

        # CP866 with box-drawing characters
        cp866_bytes = "╔════════╗\n║ Привет ║\n╚════════╝".encode("cp866")
        self.assertEqual(detect_encoding(cp866_bytes), "CP866")

    def test_detect_urq_mode(self) -> None:
        # Tag detection
        self.assertEqual(detect_urq_mode(tags=["RipURQ"]), ("ripurq", False))
        self.assertEqual(detect_urq_mode(tags=["DOS URQ"]), ("dosurq", False))
        self.assertEqual(detect_urq_mode(tags=["URQ DOS"]), ("dosurq", False))
        self.assertEqual(detect_urq_mode(tags=["AkURQ"]), ("akurq", False))
        self.assertEqual(detect_urq_mode(tags=["FireURQ"]), ("akurq", True))
        self.assertEqual(detect_urq_mode(tags=["UrqW"]), ("urqw", False))
        self.assertEqual(detect_urq_mode(tags=["UrqW 1.0"]), ("urqw1", False))
        self.assertEqual(detect_urq_mode(tags=["UrqW 2.0"]), ("urqw", False))

        # Syntax heuristics
        self.assertEqual(detect_urq_mode("urqw_version = 1"), ("urqw", False))
        self.assertEqual(
            detect_urq_mode('urq_mode = "urqw1"'), ("urqw1", False)
        )
        self.assertEqual(detect_urq_mode("urq_type = 2"), ("akurq", False))
        self.assertEqual(detect_urq_mode("urq_delay = 50"), ("dosurq", False))
        self.assertEqual(
            detect_urq_mode("[[next_room|Next]]"), ("urqw", False)
        )
        self.assertEqual(
            detect_urq_mode("if count_1.1 < 1 then p [[next_room|Next]]"),
            ("urqw1", False),
        )
        self.assertEqual(
            detect_urq_mode(
                "if count_1.1 < 1 then btn 1, Next", tags=["UrqW"]
            ),
            ("urqw1", False),
        )
        self.assertEqual(detect_urq_mode("count_items = 1"), ("dosurq", False))
        self.assertEqual(
            detect_urq_mode("textpane_color = 1"), ("akurq", True)
        )
        self.assertEqual(
            detect_urq_mode("{color:red}text{/color}"), ("akurq", True)
        )

        # Default fallback is urqw
        self.assertEqual(detect_urq_mode("#start\nHello"), ("urqw", False))

    def test_generates_from_standalone_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            game_file = root / "story.qst"
            game_file.write_bytes("#start\nПривет мир!\n".encode("cp1251"))
            destination = root / "generated"

            generate(
                GenerateSpec(
                    "2026-11-08",
                    {},
                    destination,
                    game_file,
                    title="Тестовая Игра",
                )
            )

            self.assertTrue(destination.is_dir())
            index_path = destination / "index.html"
            self.assertTrue(index_path.exists())
            index_html = index_path.read_text()
            self.assertIn(TELEMETRY_SCRIPT, index_html)
            self.assertIn('var urqw_default_game = "game";', index_html)
            self.assertIn('urqw_version="2.0"', index_html)

            self.assertTrue((destination / "rss.svg").is_file())
            for font in (
                "glyphicons-halflings-regular.woff2",
                "glyphicons-halflings-regular.woff",
                "glyphicons-halflings-regular.ttf",
            ):
                self.assertTrue((destination / "fonts" / font).is_file())

            quests_zip = destination / "quests" / "game.zip"
            self.assertTrue(quests_zip.exists())

            with ZipFile(quests_zip) as zf:
                names = zf.namelist()
                self.assertIn("manifest.json", names)
                self.assertIn("story.qst", names)
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["manifest_version"], 1)
                self.assertEqual(manifest["urqw_title"], "Тестовая Игра")
                self.assertEqual(manifest["game_encoding"], "CP1251")
                self.assertEqual(manifest["urq_mode"], "urqw")
                self.assertTrue(manifest["html_support"])

    def test_generates_transcodes_cp866_to_utf8(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            game_file = root / "dos_story.qst"
            game_file.write_bytes(
                "╔════════╗\n║ Привет ║\n╚════════╝".encode("cp866")
            )
            destination = root / "generated"

            generate(
                GenerateSpec(
                    "2026-11-08",
                    {},
                    destination,
                    game_file,
                )
            )

            quests_zip = destination / "quests" / "game.zip"
            with ZipFile(quests_zip) as zf:
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["game_encoding"], "UTF-8")
                # Ensure transcoded content decodes cleanly in UTF-8
                qst_data = zf.read("dos_story.qst")
                decoded = qst_data.decode("utf-8")
                self.assertIn("Привет", decoded)

    def test_generates_from_archive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "bundle.zip"
            with ZipFile(archive_path, "w") as zf:
                zf.writestr("bundle/story.qst", b"#start\nHello from zip")
                zf.writestr("bundle/images/pic.png", b"fake image")

            destination = root / "generated"
            generate(
                GenerateSpec(
                    "2026-11-08",
                    {},
                    destination,
                    archive_path,
                )
            )

            quests_zip = destination / "quests" / "game.zip"
            self.assertTrue(quests_zip.exists())
            with ZipFile(quests_zip) as zf:
                names = zf.namelist()
                self.assertIn("manifest.json", names)
                self.assertIn("story.qst", names)
                self.assertIn("images/pic.png", names)

    def test_preserves_existing_manifest_and_unwraps_urqw_subdir(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "repo.zip"
            author_manifest = {
                "manifest_version": 1,
                "urqw_title": "Author Title",
                "urqw_game_ifid": "A4ACD6904673881B3220776584033B0D",
                "urqw_game_lang": "ru",
                "game_encoding": "UTF-8",
                "urq_mode": "urqw1",
            }
            with ZipFile(archive_path, "w") as zf:
                zf.writestr("repo/README.md", b"# Repo docs")
                zf.writestr(
                    "repo/urqw/manifest.json",
                    json.dumps(author_manifest).encode("utf-8"),
                )
                zf.writestr("repo/urqw/main.qst", b":start\npln Hello\nend\n")
                zf.writestr(
                    "repo/urqw/A4ACD6904673881B3220776584033B0D.iFiction",
                    b"<ifindex></ifindex>",
                )

            destination = root / "generated"
            generate(
                GenerateSpec(
                    "2026-11-08",
                    {},
                    destination,
                    archive_path,
                )
            )

            index_html = (destination / "index.html").read_text()
            self.assertIn("<title>Author Title</title>", index_html)

            quests_zip = destination / "quests" / "game.zip"
            with ZipFile(quests_zip) as zf:
                names = zf.namelist()
                self.assertIn("manifest.json", names)
                self.assertIn("main.qst", names)
                self.assertIn(
                    "A4ACD6904673881B3220776584033B0D.iFiction", names
                )
                self.assertNotIn("README.md", names)
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["urqw_title"], "Author Title")
                self.assertEqual(
                    manifest["urqw_game_ifid"],
                    "A4ACD6904673881B3220776584033B0D",
                )
                self.assertEqual(manifest["urqw_game_lang"], "ru")
                self.assertEqual(manifest["urq_mode"], "urqw1")
                self.assertEqual(manifest["game_encoding"], "UTF-8")
                self.assertTrue(manifest["html_support"])

    def test_generates_from_nested_qsz(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            qsz_path = root / "game.qsz"
            with ZipFile(qsz_path, "w") as zf:
                zf.writestr("game.qst", b"#start\nNested qsz")
                zf.writestr("sound.mp3", b"fake sound")

            destination = root / "generated"
            generate(
                GenerateSpec(
                    "2026-11-08",
                    {},
                    destination,
                    qsz_path,
                )
            )

            quests_zip = destination / "quests" / "game.zip"
            self.assertTrue(quests_zip.exists())
            with ZipFile(quests_zip) as zf:
                names = zf.namelist()
                self.assertIn("manifest.json", names)
                self.assertIn("game.qst", names)
                self.assertIn("sound.mp3", names)

    def test_config_overrides(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            game_file = root / "test.qst"
            game_file.write_bytes(b"#start\nOverridden")
            destination = root / "generated"

            generate(
                GenerateSpec(
                    "2026-11-08",
                    {
                        "urq_mode": "urqw1",
                        "game_encoding": "UTF-8",
                        "html_support": False,
                        "title": "Configured Title",
                    },
                    destination,
                    game_file,
                )
            )

            quests_zip = destination / "quests" / "game.zip"
            with ZipFile(quests_zip) as zf:
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["urq_mode"], "urqw1")
                self.assertEqual(manifest["game_encoding"], "UTF-8")
                self.assertFalse(manifest["html_support"])
                self.assertEqual(manifest["urqw_title"], "Configured Title")

    def test_bundled_runtime_assets(self) -> None:
        spec = get_spec()
        self.assertIn("2026-08-21", spec.versions)
        self.assertIn("2026-11-08", spec.versions)
        self.assertEqual(spec.versions[-1], "2026-11-08")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            game_file = root / "legacy.qst"
            game_file.write_bytes(
                b":1.1\nif count_1.1 < 1 then p [[next|1.1]]\nend\n"
            )

            # 2026-08-21 downgrades urqw1 to urqw and provides fallback fonts
            dest_old = root / "gen_old"
            generate(GenerateSpec("2026-08-21", {}, dest_old, game_file))
            self.assertTrue(
                (
                    dest_old / "fonts" / "glyphicons-halflings-regular.woff2"
                ).is_file()
            )
            with ZipFile(dest_old / "quests" / "game.zip") as zf:
                manifest_old = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest_old["urq_mode"], "urqw")

            # 2026-11-08 keeps urqw1 compatibility mode
            dest_new = root / "gen_new"
            generate(GenerateSpec("2026-11-08", {}, dest_new, game_file))
            self.assertTrue(
                (
                    dest_new / "fonts" / "glyphicons-halflings-regular.woff2"
                ).is_file()
            )
            with ZipFile(dest_new / "quests" / "game.zip") as zf:
                manifest_new = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest_new["urq_mode"], "urqw1")

    def test_invalid_config_raises(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            game_file = root / "test.qst"
            game_file.write_bytes(b"#start\nTest")
            destination = root / "generated"

            # Invalid mode
            with self.assertRaises(ValueError):
                generate(
                    GenerateSpec(
                        "2026-11-08",
                        {"urq_mode": "invalid_mode"},
                        destination,
                        game_file,
                    )
                )

            # Unknown config key
            with self.assertRaises(ValueError):
                generate(
                    GenerateSpec(
                        "2026-11-08",
                        {"unknown_key": "val"},
                        destination,
                        game_file,
                    )
                )

    def test_unknown_version_raises(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            game_file = root / "test.qst"
            game_file.write_bytes(b"#start\nTest")
            destination = root / "generated"

            with self.assertRaises(ValueError):
                generate(
                    GenerateSpec(
                        "9999.99",
                        {},
                        destination,
                        game_file,
                    )
                )

    def test_discovered_by_discover_blueprints(self) -> None:
        blueprints = discover_blueprints()
        names = {info.name for info in blueprints}
        self.assertIn("urqw", names)
        urqw_info = next(info for info in blueprints if info.name == "urqw")
        spec = urqw_info.blueprint.get_spec()
        self.assertEqual(spec.name, "UrqW")
        self.assertIn("2026-08-21", spec.versions)
        self.assertIn("2026-11-08", spec.versions)

    def test_real_backup_generation(self) -> None:
        sample_qst = Path("files/backups/000000.qst")
        if not sample_qst.is_file():
            self.skipTest("files/backups/000000.qst not found")

        self.assertEqual(accepts(sample_qst), Compatibility.FULL)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "urqw_out"
            generate(
                GenerateSpec(
                    "2026-11-08",
                    {},
                    destination,
                    sample_qst,
                    title="000000",
                )
            )
            quests_zip = destination / "quests" / "game.zip"
            self.assertTrue(quests_zip.exists())
            with ZipFile(quests_zip) as zf:
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["urqw_title"], "000000")
                self.assertIn(manifest["game_encoding"], ("CP1251", "UTF-8"))
                self.assertIn(
                    manifest["urq_mode"],
                    ("akurq", "ripurq", "dosurq", "urqw", "urqw1"),
                )

    def test_real_backup_generation_thrief(self) -> None:
        sample_zip = Path("files/backups/thrief.zip")
        if not sample_zip.is_file():
            self.skipTest("files/backups/thrief.zip not found")

        self.assertEqual(accepts(sample_zip), Compatibility.FULL)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "urqw_out"
            generate(
                GenerateSpec(
                    "2026-11-08",
                    {},
                    destination,
                    sample_zip,
                    title="Квартирный вор",
                )
            )
            quests_zip = destination / "quests" / "game.zip"
            self.assertTrue(quests_zip.exists())
            with ZipFile(quests_zip) as zf:
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["urqw_title"], "Квартирный вор")
                self.assertEqual(manifest["game_encoding"], "CP1251")
                self.assertEqual(manifest["urq_mode"], "ripurq")
                names = zf.namelist()
                self.assertTrue(any(n.endswith(".qst") for n in names))

    def test_real_backup_generation_francis_spaight(self) -> None:
        sample_zip = Path("files/backups/francis_spaight.zip")
        if not sample_zip.is_file():
            self.skipTest("files/backups/francis_spaight.zip not found")

        self.assertEqual(
            accepts(sample_zip, tags=["UrqW"]), Compatibility.FULL
        )
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "urqw_out"
            generate(
                GenerateSpec(
                    "2026-11-08",
                    {},
                    destination,
                    sample_zip,
                    title="Френсис Спейт",
                    tags=["UrqW"],
                )
            )
            quests_zip = destination / "quests" / "game.zip"
            self.assertTrue(quests_zip.exists())
            with ZipFile(quests_zip) as zf:
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["urqw_title"], "Френсис Спейт")
                self.assertEqual(manifest["game_encoding"], "CP1251")
                self.assertEqual(manifest["urq_mode"], "urqw1")
