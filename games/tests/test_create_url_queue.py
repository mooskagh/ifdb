import io
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.utils.timezone import now

from games.fetcher import get_eligible_urls
from games.models import (
    URL,
    Game,
    GameURL,
    GameURLCategory,
    StoredFile,
    URLFetch,
)
from games.tasks import fetch_urls
from games.tools import CreateUrl


class MockResponse:
    def __init__(
        self,
        data: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> None:
        self.data = data
        self.metadata = {
            "filename": filename,
            "content-type": content_type,
        }
        self._stream = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        pass


class CreateUrlQueueTestCase(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_root = Path(self.temp_dir.name)
        self.files_fs = FileSystemStorage(
            location=str(self.media_root), base_url="/f/"
        )
        self.uploads_fs = FileSystemStorage(
            location=str(self.media_root / "uploads"), base_url="/f/uploads/"
        )
        self.backups_fs = FileSystemStorage(
            location=str(self.media_root / "backups"), base_url="/f/backups/"
        )
        self.settings_override = override_settings(
            MEDIA_ROOT=str(self.media_root),
            FILES_FS=self.files_fs,
            UPLOADS_FS=self.uploads_fs,
            BACKUPS_FS=self.backups_fs,
        )
        self.settings_override.enable()

        self.category, _ = GameURLCategory.objects.get_or_create(
            symbolic_id="download",
            defaults={"title": "Download", "allow_cloning": True},
        )
        self.game = Game.objects.create(
            id=701, title="Queue Test Game", creation_time=now()
        )

    def tearDown(self) -> None:
        self.settings_override.disable()
        self.temp_dir.cleanup()
        super().tearDown()

    def attach_game(self, url: URL) -> GameURL:
        return GameURL.objects.create(
            game=self.game, url=url, category=self.category
        )

    def test_create_url_queues_by_state(self) -> None:
        url = CreateUrl("https://example.com/game.zip")
        self.assertFalse(url.is_uploaded)
        self.assertIsNone(url.last_attempt)

        # An unreferenced URL is not eligible for automated fetching
        self.assertNotIn(url, list(get_eligible_urls()))

        # Once attached to a game, it appears at the head of the queue
        self.attach_game(url)
        eligible = list(get_eligible_urls())
        self.assertIn(url, eligible)
        self.assertEqual(eligible[0], url)

    def test_newer_created_urls_appear_first_in_queue(self) -> None:
        older = CreateUrl("https://example.com/older.zip")
        older.creation_date = now() - timedelta(hours=1)
        older.save(update_fields=["creation_date"])
        self.attach_game(older)

        newer = CreateUrl("https://example.com/newer.zip")
        self.attach_game(newer)

        attempted = URL.objects.create(
            original_url="https://example.com/attempted.zip",
            creation_date=now() - timedelta(days=1),
            last_attempt=now() - timedelta(days=1),
        )
        self.attach_game(attempted)

        eligible = list(get_eligible_urls())
        self.assertEqual(eligible[:3], [newer, older, attempted])

    def test_existing_url_becomes_eligible_when_cloning_enabled(self) -> None:
        self.category.allow_cloning = False
        self.category.save(update_fields=["allow_cloning"])
        url = CreateUrl("https://example.com/no-clone.zip")
        self.attach_game(url)
        self.assertNotIn(url, list(get_eligible_urls()))

        self.category.allow_cloning = True
        self.category.save(update_fields=["allow_cloning"])
        updated = CreateUrl("https://example.com/no-clone.zip")
        self.assertEqual(url.pk, updated.pk)
        self.assertIn(updated, list(get_eligible_urls()))

        self.category.allow_cloning = False
        self.category.save(update_fields=["allow_cloning"])
        self.assertNotIn(url, list(get_eligible_urls()))

    def test_create_url_for_upload_not_eligible(self) -> None:
        self.uploads_fs.save("uploaded.zip", ContentFile(b"ZIP DATA"))
        url = CreateUrl("https://zok.cx/f/uploads/uploaded.zip")
        self.attach_game(url)
        self.assertTrue(url.is_uploaded)
        self.assertNotIn(url, list(get_eligible_urls()))

    def test_created_url_processed_by_fetch_urls_task(self) -> None:
        url = CreateUrl("https://example.com/playable.zip")
        self.attach_game(url)
        resp = MockResponse(b"playable-bytes", filename="playable.zip")

        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            stats = fetch_urls(limit=10)

        self.assertEqual(stats["urls_examined"], 1)
        self.assertEqual(stats["files_created"], 1)

        url.refresh_from_db()
        self.assertIsNotNone(url.last_attempt)
        self.assertTrue(url.has_stored_copy())
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(URLFetch.objects.count(), 1)
