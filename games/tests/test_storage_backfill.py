import os
import tempfile
from datetime import datetime
from hashlib import sha256
from io import StringIO
from pathlib import Path

from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone as django_timezone

from games.models import (
    URL,
    Game,
    GameURL,
    GameURLCategory,
    StoredFile,
    URLFetch,
)


class StorageBackfillCommandTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_root = self.temp_dir.name
        self.uploads_dir = os.path.join(self.media_root, "uploads")
        self.backups_dir = os.path.join(self.media_root, "backups")
        os.makedirs(self.uploads_dir, exist_ok=True)
        os.makedirs(self.backups_dir, exist_ok=True)

        self.files_fs = FileSystemStorage(self.media_root, "/f/")
        self.uploads_fs = FileSystemStorage(self.uploads_dir, "/f/uploads/")
        self.backups_fs = FileSystemStorage(self.backups_dir, "/f/backups/")

        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_root,
            FILES_FS=self.files_fs,
            UPLOADS_FS=self.uploads_fs,
            BACKUPS_FS=self.backups_fs,
        )
        self.settings_override.enable()

    def tearDown(self) -> None:
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def _write_file(
        self, folder: str, relative_path: str, content: bytes
    ) -> Path:
        base_dir = (
            self.uploads_dir if folder == "uploads" else self.backups_dir
        )
        file_path = Path(base_dir) / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        return file_path

    def test_backfill_upload_and_backup(self) -> None:
        upload_content = b"Uploaded game content 12345"
        self._write_file("uploads", "my_game.zip", upload_content)
        upload_hash = sha256(upload_content).hexdigest()

        backup_content = b"Backup remote file 67890"
        self._write_file("backups", "archived_file.zip", backup_content)
        backup_hash = sha256(backup_content).hexdigest()

        upload_time = datetime(2024, 5, 1, 10, 0, 0)
        url_upload = URL.objects.create(
            original_url="/f/uploads/my_game.zip",
            local_filename="my_game.zip",
            local_url="/f/uploads/my_game.zip",
            is_uploaded=True,
            original_filename="Original Name.zip",
            content_type="application/zip",
            creation_date=upload_time,
        )

        url_backup = URL.objects.create(
            original_url="https://example.com/archived_file.zip",
            local_filename="archived_file.zip",
            local_url="/f/backups/archived_file.zip",
            is_uploaded=False,
            creation_date=datetime(2024, 1, 1),
        )

        out = StringIO()
        call_command("backfill_stored_files", stdout=out)

        # 1. Verify StoredFile for upload
        sf_upload = StoredFile.objects.get(content_hash=upload_hash)
        self.assertEqual(sf_upload.storage_path, "uploads/my_game.zip")
        self.assertEqual(sf_upload.file_size, len(upload_content))
        self.assertEqual(sf_upload.created_at, url_upload.creation_date)

        # 2. Verify URLFetch for upload
        fetch_upload = URLFetch.objects.get(url=url_upload)
        self.assertEqual(fetch_upload.stored_file, sf_upload)
        self.assertEqual(fetch_upload.first_fetch, upload_time)
        self.assertEqual(fetch_upload.last_fetch, upload_time)
        self.assertEqual(fetch_upload.original_filename, "Original Name.zip")
        self.assertEqual(fetch_upload.content_type, "application/zip")

        # 3. Verify StoredFile and URLFetch for backup
        sf_backup = StoredFile.objects.get(content_hash=backup_hash)
        self.assertEqual(sf_backup.storage_path, "backups/archived_file.zip")
        self.assertEqual(sf_backup.file_size, len(backup_content))

        fetch_backup = URLFetch.objects.get(url=url_backup)
        self.assertEqual(fetch_backup.stored_file, sf_backup)
        self.assertEqual(fetch_backup.original_filename, "archived_file.zip")
        self.assertEqual(fetch_backup.content_type, "application/zip")
        self.assertGreater(fetch_backup.first_fetch, url_backup.creation_date)

        # 4. Invariant: URL fields are strictly unchanged
        url_upload.refresh_from_db()
        url_backup.refresh_from_db()
        self.assertIsNone(url_upload.last_attempt)
        self.assertIsNone(url_backup.last_attempt)
        self.assertEqual(url_upload.local_filename, "my_game.zip")
        self.assertEqual(url_backup.local_filename, "archived_file.zip")

    def test_deduplication_between_urls(self) -> None:
        same_content = b"Identical game binary across two sources"
        same_hash = sha256(same_content).hexdigest()

        path1 = self._write_file("uploads", "game_v1.zip", same_content)
        path2 = self._write_file("backups", "game_clone.zip", same_content)

        url1 = URL.objects.create(
            original_url="/f/uploads/game_v1.zip",
            local_filename="game_v1.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )
        url2 = URL.objects.create(
            original_url="https://example.com/game_clone.zip",
            local_filename="game_clone.zip",
            is_uploaded=False,
            creation_date=django_timezone.now(),
        )

        out = StringIO()
        call_command("backfill_stored_files", stdout=out)

        # Only one StoredFile created
        self.assertEqual(
            StoredFile.objects.filter(content_hash=same_hash).count(), 1
        )
        sf = StoredFile.objects.get(content_hash=same_hash)

        # Both URLs have a URLFetch referencing the same StoredFile
        f1 = URLFetch.objects.get(url=url1)
        f2 = URLFetch.objects.get(url=url2)
        self.assertEqual(f1.stored_file, sf)
        self.assertEqual(f2.stored_file, sf)

        # Both legacy physical files remain untouched on disk
        self.assertTrue(path1.exists())
        self.assertTrue(path2.exists())

        # Check summary output mentions reuse
        output = out.getvalue()
        self.assertIn("Stored files created:  1", output)
        self.assertIn("Stored files reused:   1", output)
        self.assertIn("URL fetches created:   2", output)

    def test_idempotency_rerun(self) -> None:
        content = b"Idempotent test content"
        self._write_file("uploads", "idem.zip", content)

        URL.objects.create(
            original_url="/f/uploads/idem.zip",
            local_filename="idem.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )

        call_command("backfill_stored_files")
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(URLFetch.objects.count(), 1)

        # Run a second time
        out2 = StringIO()
        call_command("backfill_stored_files", stdout=out2)

        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(URLFetch.objects.count(), 1)
        self.assertIn("Already backfilled:    1", out2.getvalue())
        self.assertIn("Stored files created:  0", out2.getvalue())
        self.assertIn("URL fetches created:   0", out2.getvalue())

    def test_missing_physical_file(self) -> None:
        URL.objects.create(
            original_url="https://example.com/nonexistent.zip",
            local_filename="does_not_exist.zip",
            is_uploaded=False,
            creation_date=django_timezone.now(),
        )

        out = StringIO()
        call_command("backfill_stored_files", stdout=out)

        self.assertEqual(StoredFile.objects.count(), 0)
        self.assertEqual(URLFetch.objects.count(), 0)
        self.assertIn("Missing files:         1", out.getvalue())

    def test_dry_run(self) -> None:
        content = b"Dry run content"
        self._write_file("uploads", "dry_run.zip", content)

        URL.objects.create(
            original_url="/f/uploads/dry_run.zip",
            local_filename="dry_run.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )

        out = StringIO()
        call_command("backfill_stored_files", dry_run=True, stdout=out)

        self.assertEqual(StoredFile.objects.count(), 0)
        self.assertEqual(URLFetch.objects.count(), 0)
        output = out.getvalue()
        self.assertIn("(DRY RUN)", output)
        self.assertIn("Stored files created:  1", output)
        self.assertIn("URL fetches created:   1", output)

    def test_filter_by_url_id(self) -> None:
        self._write_file("uploads", "u1.zip", b"content 1")
        self._write_file("uploads", "u2.zip", b"content 2")

        url1 = URL.objects.create(
            original_url="/f/uploads/u1.zip",
            local_filename="u1.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )
        URL.objects.create(
            original_url="/f/uploads/u2.zip",
            local_filename="u2.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )

        call_command("backfill_stored_files", url_id=url1.pk)
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(URLFetch.objects.count(), 1)
        self.assertEqual(URLFetch.objects.first().url, url1)

    def test_filter_by_limit(self) -> None:
        for i in range(5):
            self._write_file("uploads", f"file{i}.zip", f"c{i}".encode())
            URL.objects.create(
                original_url=f"/f/uploads/file{i}.zip",
                local_filename=f"file{i}.zip",
                is_uploaded=True,
                creation_date=django_timezone.now(),
            )

        call_command("backfill_stored_files", limit=2)
        self.assertEqual(StoredFile.objects.count(), 2)
        self.assertEqual(URLFetch.objects.count(), 2)

    def test_filter_by_unprocessed_only(self) -> None:
        self._write_file("uploads", "f1.zip", b"f1")
        self._write_file("uploads", "f2.zip", b"f2")

        u1 = URL.objects.create(
            original_url="/f/uploads/f1.zip",
            local_filename="f1.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )
        URL.objects.create(
            original_url="/f/uploads/f2.zip",
            local_filename="f2.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )

        # Backfill u1 first
        call_command("backfill_stored_files", url_id=u1.pk)
        self.assertEqual(URLFetch.objects.count(), 1)

        # Run with unprocessed_only
        out = StringIO()
        call_command(
            "backfill_stored_files", unprocessed_only=True, stdout=out
        )
        self.assertIn("URLs examined:         1", out.getvalue())
        self.assertEqual(URLFetch.objects.count(), 2)

    def test_filter_by_game_id(self) -> None:
        self._write_file("uploads", "game1.zip", b"game1")
        self._write_file("uploads", "game2.zip", b"game2")

        u1 = URL.objects.create(
            original_url="/f/uploads/game1.zip",
            local_filename="game1.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )
        u2 = URL.objects.create(
            original_url="/f/uploads/game2.zip",
            local_filename="game2.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )

        cat = GameURLCategory.objects.create(symbolic_id="download")
        g1 = Game.objects.create(
            title="Game 1", creation_time=django_timezone.now()
        )
        g2 = Game.objects.create(
            title="Game 2", creation_time=django_timezone.now()
        )
        GameURL.objects.create(game=g1, url=u1, category=cat)
        GameURL.objects.create(game=g2, url=u2, category=cat)

        call_command("backfill_stored_files", game_id=g1.pk)
        self.assertEqual(URLFetch.objects.count(), 1)
        self.assertEqual(URLFetch.objects.first().url, u1)
