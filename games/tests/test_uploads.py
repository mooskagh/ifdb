import io
import tempfile
from hashlib import sha256
from pathlib import Path

from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils.timezone import now

from curation.manual import store_manual_add
from games.fetcher import get_eligible_urls
from games.gameinfo import GameInfo, GameUrl
from games.models import (
    URL,
    Game,
    GameURL,
    GameURLCategory,
    StoredFile,
    URLFetch,
)
from games.uploads import (
    finalize_provisional_uploads,
    handle_existing_game_upload,
    is_provisional_upload,
)


class UploadMigrationTestCase(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_root = Path(self.temp_dir.name)
        self.files_fs = FileSystemStorage(
            location=str(self.media_root), base_url="/f/"
        )
        self.backups_fs = FileSystemStorage(
            location=str(self.media_root / "backups"), base_url="/f/backups/"
        )
        self.uploads_fs = FileSystemStorage(
            location=str(self.media_root / "uploads"), base_url="/f/uploads/"
        )

        self.settings_override = override_settings(
            MEDIA_ROOT=str(self.media_root),
            FILES_FS=self.files_fs,
            BACKUPS_FS=self.backups_fs,
            UPLOADS_FS=self.uploads_fs,
        )
        self.settings_override.enable()

        self.cat_download, _ = GameURLCategory.objects.get_or_create(
            symbolic_id="download_direct",
            defaults={"title": "Download Direct", "allow_cloning": True},
        )

    def tearDown(self) -> None:
        self.settings_override.disable()
        self.temp_dir.cleanup()
        super().tearDown()

    def test_existing_game_unique_upload(self) -> None:
        game = Game.objects.create(
            id=123, title="Game 123", creation_time=now()
        )
        content = b"game binary content v1"
        uploaded = SimpleUploadedFile(
            "adventure.zip", content, content_type="application/zip"
        )

        url, stored_file, fetch = handle_existing_game_upload(
            game=game,
            uploaded_file=uploaded,
            build_absolute_uri=lambda path: f"http://testserver{path}",
        )

        self.assertEqual(stored_file.storage_path, "g/123/adventure.zip")
        self.assertEqual(stored_file.content_hash, sha256(content).hexdigest())
        self.assertEqual(stored_file.file_size, len(content))
        self.assertTrue(stored_file.exists())
        self.assertEqual(stored_file.open("rb").read(), content)

        self.assertTrue(url.is_uploaded)
        self.assertEqual(url.get_local_url(), "/f/g/123/adventure.zip")
        self.assertEqual(
            url.original_url, "http://testserver/f/g/123/adventure.zip"
        )
        self.assertEqual(url.get_original_filename(), "adventure.zip")
        self.assertEqual(url.get_stored_file(), stored_file)

        self.assertEqual(fetch.stored_file, stored_file)
        self.assertEqual(fetch.url, url)

    def test_existing_game_duplicate_upload_reuses_stored_file(self) -> None:
        game1 = Game.objects.create(
            id=101, title="Game 101", creation_time=now()
        )
        game2 = Game.objects.create(
            id=102, title="Game 102", creation_time=now()
        )

        shared_bytes = b"identical bytes for both games"
        file1 = SimpleUploadedFile(
            "first.zip", shared_bytes, content_type="application/zip"
        )
        file2 = SimpleUploadedFile(
            "second.zip", shared_bytes, content_type="application/zip"
        )

        url1, stored1, fetch1 = handle_existing_game_upload(
            game=game1,
            uploaded_file=file1,
            build_absolute_uri=lambda p: f"http://testserver{p}",
        )
        url2, stored2, fetch2 = handle_existing_game_upload(
            game=game2,
            uploaded_file=file2,
            build_absolute_uri=lambda p: f"http://testserver{p}",
        )

        self.assertEqual(stored1.id, stored2.id)
        self.assertEqual(stored2.storage_path, "g/101/first.zip")
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertFalse((self.media_root / "g/102").exists())
        self.assertEqual(url2.get_local_url(), "/f/g/101/first.zip")
        self.assertEqual(
            url2.original_url, "http://testserver/f/g/101/first.zip"
        )

    def test_collision_handling_in_game_upload(self) -> None:
        game = Game.objects.create(
            id=200, title="Game 200", creation_time=now()
        )
        bytes_a = b"content version A"
        bytes_b = b"content version B"

        file_a = SimpleUploadedFile(
            "game.zip", bytes_a, content_type="application/zip"
        )
        file_b = SimpleUploadedFile(
            "game.zip", bytes_b, content_type="application/zip"
        )

        url_a, stored_a, _ = handle_existing_game_upload(
            game=game,
            uploaded_file=file_a,
            build_absolute_uri=lambda p: f"http://testserver{p}",
        )
        url_b, stored_b, _ = handle_existing_game_upload(
            game=game,
            uploaded_file=file_b,
            build_absolute_uri=lambda p: f"http://testserver{p}",
        )

        self.assertEqual(stored_a.storage_path, "g/200/game.zip")
        self.assertTrue(stored_b.storage_path.startswith("g/200/game-"))
        self.assertTrue(stored_b.storage_path.endswith(".zip"))
        self.assertNotEqual(stored_a.id, stored_b.id)
        self.assertEqual(stored_a.open("rb").read(), bytes_a)
        self.assertEqual(stored_b.open("rb").read(), bytes_b)

    def test_new_game_provisional_upload_promoted(self) -> None:
        # Step 1: Editor uploads provisional file to UPLOADS_FS
        content = b"provisional new game data"
        filename = self.uploads_fs.save("story.zip", io.BytesIO(content))
        prov_full_url = f"http://testserver/f/uploads/{filename}"

        prov_url = URL.objects.create(
            original_url=prov_full_url,
            is_uploaded=True,
            creation_date=now(),
        )

        # Step 2: User submits new game via GameInfo
        info = GameInfo(
            name="Brand New Quest",
            urls=[
                GameUrl(
                    category="download_direct",
                    url_id=None,
                    description="Download",
                    url=prov_full_url,
                )
            ],
        )

        game, canonical = info.save(None)

        final_expected_path = f"g/{game.id}/story.zip"
        final_expected_url = f"http://testserver/f/g/{game.id}/story.zip"

        stored = StoredFile.objects.filter(
            storage_path=final_expected_path
        ).first()
        self.assertIsNotNone(stored)
        self.assertEqual(stored.file_size, len(content))
        self.assertEqual(stored.open("rb").read(), content)

        self.assertIn(final_expected_url, canonical)
        self.assertNotIn("/f/uploads/", canonical)

        gu = GameURL.objects.get(game=game)
        self.assertEqual(gu.url.original_url, final_expected_url)
        self.assertEqual(gu.url.get_stored_file(), stored)
        self.assertTrue(gu.url.fetches.filter(stored_file=stored).exists())

        # Provisional URL record deleted
        self.assertFalse(URL.objects.filter(id=prov_url.id).exists())

    def test_existing_published_legacy_upload_not_promoted(self) -> None:
        # Setup legacy file in UPLOADS_FS
        legacy_content = b"legacy game uploaded years ago"
        legacy_rel = self.uploads_fs.save(
            "legacy.zip", io.BytesIO(legacy_content)
        )
        legacy_full_url = f"http://testserver/f/uploads/{legacy_rel}"

        legacy_hash = sha256(legacy_content).hexdigest()
        legacy_stored = StoredFile.objects.create(
            storage_path=f"uploads/{legacy_rel}",
            content_hash=legacy_hash,
            file_size=len(legacy_content),
            created_at=now(),
        )

        legacy_url = URL.objects.create(
            original_url=legacy_full_url,
            is_uploaded=True,
            creation_date=now(),
        )
        URLFetch.objects.create(url=legacy_url, stored_file=legacy_stored)

        game1 = Game.objects.create(
            id=50, title="Old Game", creation_time=now()
        )
        GameURL.objects.create(
            game=game1, url=legacy_url, category=self.cat_download
        )

        # Check is_provisional_upload detects it as NOT provisional
        is_prov, _ = is_provisional_upload(legacy_full_url)
        self.assertFalse(is_prov)

        # Now create Game 2 referencing the legacy URL
        info2 = GameInfo(
            name="New Compilation Game",
            urls=[
                GameUrl(
                    category="download_direct",
                    url_id=None,
                    description="Old file",
                    url=legacy_full_url,
                )
            ],
        )

        game2, canonical2 = info2.save(None)

        # It must NOT be promoted or moved to g/game2.id/...
        self.assertFalse((self.media_root / f"g/{game2.id}").exists())
        self.assertTrue(self.uploads_fs.exists(legacy_rel))
        self.assertEqual(legacy_stored.storage_path, f"uploads/{legacy_rel}")

        gu2 = GameURL.objects.get(game=game2)
        self.assertEqual(gu2.url, legacy_url)
        self.assertEqual(gu2.url.original_url, legacy_full_url)

    def test_uploaded_urls_excluded_from_refetch(self) -> None:
        game = Game.objects.create(
            id=300, title="Game 300", creation_time=now()
        )
        uploaded = SimpleUploadedFile(
            "archive.zip", b"content", content_type="application/zip"
        )
        url, _, _ = handle_existing_game_upload(
            game=game,
            uploaded_file=uploaded,
            build_absolute_uri=lambda p: f"http://testserver{p}",
        )
        GameURL.objects.create(game=game, url=url, category=self.cat_download)

        self.assertTrue(url.is_uploaded)
        eligible_ids = [u.id for u in get_eligible_urls()]
        self.assertNotIn(url.id, eligible_ids)

    def test_failed_save_leaves_provisional_upload(self) -> None:
        content = b"staging bytes that should survive rollback"
        filename = self.uploads_fs.save("temp_story.zip", io.BytesIO(content))
        prov_full_url = f"http://testserver/f/uploads/{filename}"

        prov_url = URL.objects.create(
            original_url=prov_full_url,
            is_uploaded=True,
            creation_date=now(),
        )

        info = GameInfo(
            name="Failing Game",
            urls=[
                GameUrl(
                    category="download_direct",
                    url_id=None,
                    description="Temp",
                    url=prov_full_url,
                )
            ],
        )

        class IntentionalError(Exception):
            pass

        with self.assertRaises(IntentionalError):
            with transaction.atomic():
                game = Game.objects.create(
                    title="Temp Game", creation_time=now()
                )
                finalize_provisional_uploads(game, info)
                raise IntentionalError("simulate failure")

        # Staging file and URL record should still exist
        self.assertTrue(self.uploads_fs.exists(filename))
        self.assertTrue(URL.objects.filter(id=prov_url.id).exists())

    def test_store_manual_add_and_edit_finalize_provisional_uploads(
        self,
    ) -> None:
        content = b"manual add content"
        filename = self.uploads_fs.save("editor.zip", io.BytesIO(content))
        prov_url = f"http://testserver/f/uploads/{filename}"

        URL.objects.create(
            original_url=prov_url,
            is_uploaded=True,
            creation_date=now(),
        )

        data = {
            "title": "Manual Game",
            "links": [["download_direct", "Manual link", prov_url]],
        }

        rev = store_manual_add(data, None, apply=True)
        game = rev.game

        self.assertNotIn("/f/uploads/", rev.canonical_text)
        self.assertIn(f"/f/g/{game.id}/editor.zip", rev.canonical_text)
