import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from core.archives import (
    ArchiveToolNotFoundError,
    BadArchiveError,
    ZipArchive,
    extract_archive,
    list_archive_members,
    open_archive,
    repack_to_zip,
)

RAR_SAMPLE = Path("files/backups/0.3.rar")
UNAR_AVAILABLE = bool(shutil.which("unar") and shutil.which("lsar"))


class ArchivesTest(SimpleTestCase):
    def test_zip_archive_namelist_and_extract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "test.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("dir/file1.txt", "content1")
                zf.writestr("file2.txt", "content2")

            with open_archive(zip_path) as archive:
                self.assertIsInstance(archive, ZipArchive)
                self.assertEqual(
                    sorted(archive.namelist()), ["dir/file1.txt", "file2.txt"]
                )

            dest = temp_path / "extracted"
            extract_archive(zip_path, dest)
            self.assertEqual(
                (dest / "dir" / "file1.txt").read_text(), "content1"
            )
            self.assertEqual((dest / "file2.txt").read_text(), "content2")

    def test_zip_bad_archive_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_file = Path(temp_dir) / "bad.zip"
            bad_file.write_bytes(b"corrupted content")
            with self.assertRaises(BadArchiveError):
                open_archive(bad_file)

    def test_nonexistent_file_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            open_archive(Path("/nonexistent/path/archive.zip"))

    def test_missing_tools_raises_tool_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rar_file = Path(temp_dir) / "test.rar"
            rar_file.write_bytes(b"Rar!\x1a\x07\x00dummy")
            with patch("shutil.which", return_value=None):
                with self.assertRaises(ArchiveToolNotFoundError):
                    open_archive(rar_file)

    @unittest.skipUnless(
        UNAR_AVAILABLE and RAR_SAMPLE.is_file(),
        "unar/lsar or sample RAR not available",
    )
    def test_rar_archive_namelist_and_extract(self) -> None:
        with open_archive(RAR_SAMPLE) as archive:
            names = archive.namelist()
            self.assertIn("bunker-0.3/main.lua", names)

        with tempfile.TemporaryDirectory() as temp_dir:
            dest = Path(temp_dir) / "out"
            extract_archive(RAR_SAMPLE, dest)
            self.assertTrue((dest / "bunker-0.3" / "main.lua").is_file())

    @unittest.skipUnless(
        UNAR_AVAILABLE and RAR_SAMPLE.is_file(),
        "unar/lsar or sample RAR not available",
    )
    def test_repack_to_zip_from_rar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_zip = Path(temp_dir) / "repacked.zip"
            repack_to_zip(RAR_SAMPLE, dest_zip)
            self.assertTrue(zipfile.is_zipfile(dest_zip))

            members = list_archive_members(dest_zip)
            self.assertIn("bunker-0.3/main.lua", members)

    def test_repack_to_zip_from_zip_copies_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_zip = temp_path / "source.zip"
            with zipfile.ZipFile(source_zip, "w") as zf:
                zf.writestr("test.txt", "hello")

            dest_zip = temp_path / "dest.zip"
            repack_to_zip(source_zip, dest_zip)
            self.assertEqual(dest_zip.read_bytes(), source_zip.read_bytes())
