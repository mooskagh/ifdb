import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from celery.exceptions import Retry
from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.utils.timezone import now

from games.fetcher import FetchOutcome
from games.models import (
    URL,
    Game,
    GameURL,
    GameURLCategory,
    StoredFile,
    URLFetch,
)
from games.tasks import clone_file, come_up_with_filename


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


class CloneFileTaskTestCase(TestCase):
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

        self.category, _ = GameURLCategory.objects.get_or_create(
            symbolic_id="download",
            defaults={"title": "Download", "allow_cloning": True},
        )

    def tearDown(self) -> None:
        self.settings_override.disable()
        self.temp_dir.cleanup()
        super().tearDown()

    def create_game(self, game_id: int, title: str = "Test Game") -> Game:
        return Game.objects.create(
            id=game_id, title=title, creation_time=now()
        )

    def create_url(
        self,
        original_url: str = "https://example.com/downloads/adventure.zip",
        is_uploaded: bool = False,
        ok_to_clone: bool = True,
        game: Game | None = None,
    ) -> URL:
        url = URL.objects.create(
            original_url=original_url,
            is_uploaded=is_uploaded,
            ok_to_clone=ok_to_clone,
            creation_date=now(),
        )
        if game is not None:
            GameURL.objects.create(game=game, url=url, category=self.category)
        return url

    def test_clone_file_success_with_game(self) -> None:
        game = self.create_game(501)
        url = self.create_url("https://example.com/games/quest.zip", game=game)
        content = b"quest-v1-bytes"
        resp = MockResponse(
            content, filename="quest.zip", content_type="application/zip"
        )

        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            res = clone_file(url.pk)

        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.outcome, FetchOutcome.CREATED)
        self.assertIsNotNone(res.stored_file)
        self.assertIsNotNone(res.url_fetch)

        stored = res.stored_file
        assert stored is not None
        self.assertEqual(stored.storage_path, "g/501/quest.zip")
        self.assertTrue(stored.exists())

        url.refresh_from_db()
        self.assertEqual(url.local_url, "/f/g/501/quest.zip")
        self.assertEqual(url.file_size, len(content))
        self.assertEqual(url.original_filename, "quest.zip")
        self.assertEqual(url.content_type, "application/zip")
        self.assertFalse(url.is_broken)
        self.assertIsNone(url.failing_since)
        self.assertIsNone(url.last_error)
        self.assertIsNotNone(url.last_attempt)

    def test_clone_file_success_without_game(self) -> None:
        url = self.create_url("https://example.com/files/tool.zip", game=None)
        content = b"tool-bytes"
        resp = MockResponse(content, filename="tool.zip")

        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            res = clone_file(url.pk)

        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.outcome, FetchOutcome.CREATED)
        assert res.stored_file is not None
        self.assertEqual(res.stored_file.storage_path, "backups/tool.zip")

    def test_clone_file_deduplication(self) -> None:
        game1 = self.create_game(502)
        game2 = self.create_game(503)
        url1 = self.create_url("https://site1.org/game.zip", game=game1)
        url2 = self.create_url("https://site2.org/game.zip", game=game2)

        content = b"shared-content-xyz"
        resp1 = MockResponse(content, filename="game.zip")
        resp2 = MockResponse(content, filename="game.zip")

        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp1):
            res1 = clone_file(url1.pk)
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp2):
            res2 = clone_file(url2.pk)

        self.assertIsNotNone(res1)
        self.assertIsNotNone(res2)
        assert res1 is not None and res2 is not None
        self.assertEqual(res1.outcome, FetchOutcome.CREATED)
        self.assertEqual(res2.outcome, FetchOutcome.REUSED)
        self.assertEqual(res1.stored_file, res2.stored_file)
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(URLFetch.objects.count(), 2)

    def test_clone_file_refetch_unchanged(self) -> None:
        game = self.create_game(504)
        url = self.create_url("https://example.com/same.zip", game=game)
        content = b"unchanged-content"

        resp1 = MockResponse(content, filename="same.zip")
        resp2 = MockResponse(content, filename="same.zip")

        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp1):
            res1 = clone_file(url.pk)
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp2):
            res2 = clone_file(url.pk)

        self.assertIsNotNone(res1)
        self.assertIsNotNone(res2)
        assert res1 is not None and res2 is not None
        self.assertEqual(res1.outcome, FetchOutcome.CREATED)
        self.assertEqual(res2.outcome, FetchOutcome.UNCHANGED)
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(URLFetch.objects.count(), 1)

    def test_clone_file_skips_uploaded_url(self) -> None:
        url = self.create_url(
            "https://db.crem.xyz/f/uploads/myupload.zip",
            is_uploaded=True,
            ok_to_clone=False,
        )
        with patch("games.fetcher.FetchUrlToFileLike") as mock_fetch:
            res = clone_file(url.pk)

        mock_fetch.assert_not_called()
        self.assertIsNone(res)
        url.refresh_from_db()
        self.assertIsNone(url.last_attempt)

    def test_clone_file_nonexistent_url(self) -> None:
        res = clone_file(999999)
        self.assertIsNone(res)

    def test_clone_file_celery_apply(self) -> None:
        game = self.create_game(505)
        url = self.create_url("https://example.com/eager.zip", game=game)
        content = b"eager-content"
        resp = MockResponse(content, filename="eager.zip")

        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            async_res = clone_file.apply(args=[url.pk])

        self.assertTrue(async_res.successful())
        fetch_res = async_res.result
        self.assertEqual(fetch_res.outcome, FetchOutcome.CREATED)
        self.assertTrue(url.has_stored_copy())

    def test_clone_file_failure_triggers_retry_when_retries_remain(
        self,
    ) -> None:
        game = self.create_game(506)
        url = self.create_url("https://example.com/fail.zip", game=game)

        clone_file.push_request(retries=0)
        try:
            with (
                patch.object(
                    clone_file, "retry", side_effect=Retry("Retrying task")
                ) as mock_retry,
                patch(
                    "games.fetcher.FetchUrlToFileLike",
                    side_effect=RuntimeError("503 Service Unavailable"),
                ),
                self.assertRaises(Retry),
            ):
                clone_file(url.pk)

            mock_retry.assert_called_once()
            url.refresh_from_db()
            self.assertTrue(url.is_broken)
            self.assertIsNotNone(url.failing_since)
            self.assertIn("503 Service Unavailable", url.last_error or "")
        finally:
            clone_file.pop_request()

    def test_clone_file_failure_raises_when_retries_exhausted(self) -> None:
        game = self.create_game(507)
        url = self.create_url("https://example.com/exhaust.zip", game=game)

        clone_file.push_request(retries=3)
        try:
            with (
                patch.object(clone_file, "retry") as mock_retry,
                patch(
                    "games.fetcher.FetchUrlToFileLike",
                    side_effect=RuntimeError("404 Not Found"),
                ),
                self.assertRaises(RuntimeError) as ctx,
            ):
                clone_file(url.pk)

            self.assertIn("404 Not Found", str(ctx.exception))
            mock_retry.assert_not_called()

            url.refresh_from_db()
            self.assertTrue(url.is_broken)
            self.assertIsNotNone(url.failing_since)
            self.assertIn("404 Not Found", url.last_error or "")
        finally:
            clone_file.pop_request()

    def test_come_up_with_filename_compatibility(self) -> None:
        self.assertEqual(
            come_up_with_filename({"filename": "release.zip"}), "release.zip"
        )
        self.assertEqual(
            come_up_with_filename({
                "filename": None,
                "url": "https://example.com/game.tar.gz",
            }),
            "game.tar.gz",
        )
        self.assertEqual(come_up_with_filename({}), "unknown")
