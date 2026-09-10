from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.utils import timezone

from games.models import URL
from games.tools import CreateUrl


class UrlLocalFileResolutionTests(TestCase):
    def test_resolve_local_file_for_upload(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fs = FileSystemStorage(location=tmp_dir, base_url="/f/uploads/")
            filename = fs.save("game.zip", ContentFile(b"ZIP DATA"))
            with override_settings(UPLOADS_FS=fs):
                url = URL.objects.create(
                    original_url="https://db.crem.xyz/f/uploads/game.zip",
                    creation_date=timezone.now(),
                )
                self.assertIsNone(url.local_filename)
                self.assertFalse(url.is_uploaded)

                self.assertTrue(url.resolve_local_file())
                url.refresh_from_db()

                self.assertEqual(url.local_filename, filename)
                self.assertTrue(url.is_uploaded)
                self.assertEqual(url.local_url, "/f/uploads/game.zip")
                self.assertEqual(url.file_size, len(b"ZIP DATA"))
                self.assertEqual(url.content_type, "application/zip")
                self.assertFalse(url.ok_to_clone)

    def test_resolve_local_file_with_url_encoding(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fs = FileSystemStorage(location=tmp_dir, base_url="/f/uploads/")
            name = "SKIT — iПоколение.zip"
            filename = fs.save(name, ContentFile(b"ZIP DATA"))
            with override_settings(UPLOADS_FS=fs):
                url = URL.objects.create(
                    original_url="https://db.crem.xyz/f/uploads/SKIT%20%E2%80%94%20i%D0%9F%D0%BE%D0%BA%D0%BE%D0%BB%D0%B5%D0%BD%D0%B8%D0%B5.zip",
                    creation_date=timezone.now(),
                )
                self.assertTrue(url.resolve_local_file())
                url.refresh_from_db()

                self.assertEqual(url.local_filename, filename)
                self.assertTrue(url.is_uploaded)

    def test_create_url_resolves_local_upload_without_cloning(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fs = FileSystemStorage(location=tmp_dir, base_url="/f/uploads/")
            fs.save("uploaded.zip", ContentFile(b"ZIP DATA"))
            with override_settings(UPLOADS_FS=fs):
                with patch("games.tools.clone_file.delay") as mock_clone:
                    url = CreateUrl(
                        "https://zok.cx/f/uploads/uploaded.zip",
                        ok_to_clone=True,
                    )
                    self.assertEqual(url.local_filename, "uploaded.zip")
                    self.assertTrue(url.is_uploaded)
                    mock_clone.assert_not_called()
