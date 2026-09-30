import io
import tempfile
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils.timezone import now

from games.fetcher import (
    FetchOutcome,
    determine_storage_path,
    fetch_url,
    sanitize_filename,
)
from games.models import (
    URL,
    Game,
    GameURL,
    GameURLCategory,
    StoredFile,
    URLFetch,
)


class MockResponse:
    def __init__(
        self,
        data: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ):
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


class BaseFetcherTestCase(TestCase):
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
        game: Game | None = None,
    ) -> URL:
        url = URL.objects.create(
            original_url=original_url,
            is_uploaded=is_uploaded,
            creation_date=now(),
        )
        if game is not None:
            GameURL.objects.create(game=game, url=url, category=self.category)
        return url


class TestFetchUrlHistory(BaseFetcherTestCase):
    def test_instead_error_body_is_a_failed_fetch_for_any_file_category(
        self,
    ) -> None:
        game = self.create_game(197)
        url = self.create_url(
            "https://instead-games.ru/downloader.php?id=42", game=game
        )
        poster = GameURLCategory.objects.create(
            title="Poster", allow_cloning=True
        )
        GameURL.objects.filter(url=url).update(category=poster)

        good = fetch_url(
            url,
            downloader=lambda _url, *, timeout: MockResponse(b"image bytes"),
        )
        result = fetch_url(
            url,
            downloader=lambda _url, *, timeout: MockResponse(
                b"File not found: poster.jpg", content_type="text/html"
            ),
        )

        self.assertEqual(result.outcome, FetchOutcome.FAILED)
        self.assertIn("File not found", result.error or "")
        self.assertEqual(URLFetch.objects.count(), 1)
        self.assertEqual(StoredFile.objects.count(), 1)
        url.refresh_from_db()
        self.assertTrue(url.is_link_broken())
        self.assertEqual(url.get_stored_file(), good.stored_file)

    def test_questbook_error_card_is_a_failed_fetch(self) -> None:
        game = self.create_game(196)
        url = self.create_url(
            "https://quest-book.ru/online/other/download/9/txt/", game=game
        )
        page = (
            '<!DOCTYPE html><meta charset="windows-1251">'
            + "<nav>КвестБук</nav>" * 100
            + (
                '<div class="card-header"><h4 class="mt-0">'
                "Общая ошибка</h4></div>"
                '<div class="card-body"><div class="text-center">'
                "Ошибка запроса</div></div>"
            )
        ).encode("cp1251")

        result = fetch_url(
            url,
            downloader=lambda _url, *, timeout: MockResponse(
                page, content_type="text/html"
            ),
        )

        self.assertEqual(result.outcome, FetchOutcome.FAILED)
        self.assertIn("Request error", result.error or "")
        self.assertFalse(URLFetch.objects.exists())
        self.assertFalse(StoredFile.objects.exists())
        url.refresh_from_db()
        self.assertTrue(url.is_link_broken())

    def test_error_words_inside_valid_content_are_not_rejected(self) -> None:
        game = self.create_game(195)
        instead = self.create_url(
            "https://instead-games.ru/download/game.html", game=game
        )
        questbook = self.create_url(
            "https://quest-book.ru/online/game", game=game
        )
        other = self.create_url("https://example.com/game.txt", game=game)
        bodies = (
            (instead, b"<html>File not found: a character's line</html>"),
            (
                questbook,
                "<html><p>Общая ошибка: Ошибка запроса</p></html>".encode(),
            ),
            (other, b"File not found: a line of dialogue"),
        )
        for url, body in bodies:
            with self.subTest(url=url.original_url):
                result = fetch_url(
                    url,
                    downloader=lambda _url, *, timeout: MockResponse(
                        body, content_type="text/html"
                    ),
                )
                self.assertEqual(result.outcome, FetchOutcome.CREATED)

    def test_long_encoded_public_url_is_saved(self) -> None:
        game = self.create_game(198)
        url = self.create_url(game=game)
        filename = "игра" * 14 + ".jpg"

        result = fetch_url(
            url,
            downloader=lambda _url, *, timeout: MockResponse(
                b"image", filename=filename
            ),
        )

        self.assertEqual(result.outcome, FetchOutcome.CREATED)
        assert result.stored_file is not None
        url.refresh_from_db()
        self.assertIsNone(url.local_url)
        self.assertGreater(len(url.get_local_url() or ""), 255)
        self.assertEqual(url.get_local_url(), result.stored_file.public_url)

    def test_overlapping_fetch_cannot_move_timestamps_backwards(self) -> None:
        game = self.create_game(199)
        url = self.create_url(game=game)
        earlier = now()
        later = earlier + timedelta(minutes=1)

        def download(_original_url: str, *, timeout: int) -> MockResponse:
            inner_url = URL.objects.get(pk=url.pk)
            inner = fetch_url(
                inner_url,
                downloader=lambda _url, *, timeout: MockResponse(b"content"),
            )
            self.assertEqual(inner.outcome, FetchOutcome.CREATED)
            return MockResponse(b"content")

        with patch("games.fetcher.now", side_effect=[earlier, later]):
            outer = fetch_url(url, downloader=download)

        self.assertEqual(outer.outcome, FetchOutcome.UNCHANGED)
        url.refresh_from_db()
        fetch = URLFetch.objects.get(url=url)
        self.assertEqual(url.last_attempt, later)
        self.assertEqual(fetch.first_fetch, later)
        self.assertEqual(fetch.last_fetch, later)

    def test_first_fetch_creates_stored_file_and_url_fetch(self) -> None:
        game = self.create_game(101)
        url = self.create_url("https://example.com/games/quest.zip", game=game)

        content = b"quest-content-v1"
        resp = MockResponse(
            content, filename="quest.zip", content_type="application/zip"
        )

        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            res = fetch_url(url)

        self.assertEqual(res.outcome, FetchOutcome.CREATED)
        self.assertIsNotNone(res.stored_file)
        self.assertIsNotNone(res.url_fetch)

        stored = res.stored_file
        assert stored is not None
        self.assertEqual(stored.content_hash, sha256(content).hexdigest())
        self.assertEqual(stored.storage_path, "g/101/quest.zip")
        self.assertEqual(stored.file_size, len(content))
        self.assertTrue(stored.exists())

        url.refresh_from_db()
        self.assertIsNone(url.local_url)
        self.assertIsNone(url.file_size)
        self.assertIsNone(url.original_filename)
        self.assertIsNone(url.content_type)
        self.assertFalse(url.is_broken)
        self.assertEqual(url.get_local_url(), "/f/g/101/quest.zip")
        self.assertEqual(url.get_file_size(), len(content))
        self.assertEqual(url.get_original_filename(), "quest.zip")
        self.assertEqual(url.get_content_type(), "application/zip")
        self.assertFalse(url.is_link_broken())
        self.assertIsNone(url.failing_since)
        self.assertIsNone(url.last_error)
        self.assertIsNotNone(url.last_attempt)

    def test_refetch_identical_bytes_updates_last_fetch_only(self) -> None:
        game = self.create_game(102)
        url = self.create_url("https://example.com/games/quest.zip", game=game)
        content = b"identical-bytes"

        resp1 = MockResponse(
            content, filename="quest.zip", content_type="application/zip"
        )
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp1):
            res1 = fetch_url(url)

        self.assertEqual(res1.outcome, FetchOutcome.CREATED)
        fetch1 = res1.url_fetch
        assert fetch1 is not None

        # Re-fetch identical content
        resp2 = MockResponse(
            content, filename="quest.zip", content_type="application/zip"
        )
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp2):
            res2 = fetch_url(url)

        self.assertEqual(res2.outcome, FetchOutcome.UNCHANGED)
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(URLFetch.objects.count(), 1)

        fetch1.refresh_from_db()
        assert res1.stored_file is not None
        self.assertEqual(fetch1.stored_file_id, res1.stored_file.id)
        self.assertGreaterEqual(fetch1.last_fetch, fetch1.first_fetch)

    def test_changed_bytes_creates_second_url_fetch(self) -> None:
        game = self.create_game(103)
        url = self.create_url("https://example.com/games/quest.zip", game=game)

        resp1 = MockResponse(
            b"bytes-A", filename="quest.zip", content_type="application/zip"
        )
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp1):
            fetch_url(url)

        resp2 = MockResponse(
            b"bytes-B", filename="quest.zip", content_type="application/zip"
        )
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp2):
            res2 = fetch_url(url)

        self.assertEqual(res2.outcome, FetchOutcome.CREATED)
        self.assertEqual(StoredFile.objects.count(), 2)
        self.assertEqual(URLFetch.objects.count(), 2)

        url.refresh_from_db()
        current_stored = url.get_stored_file()
        assert current_stored is not None
        assert res2.stored_file is not None
        self.assertEqual(current_stored.id, res2.stored_file.id)

    def test_fetch_history_a_b_a_sequence(self) -> None:
        game = self.create_game(104)
        url = self.create_url("https://example.com/games/quest.zip", game=game)

        # 1. Fetch A
        resp_a1 = MockResponse(b"bytes-A", filename="quest.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp_a1):
            res_a1 = fetch_url(url)

        # 2. Fetch B
        resp_b = MockResponse(b"bytes-B", filename="quest.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp_b):
            res_b = fetch_url(url)

        # 3. Fetch A again
        resp_a2 = MockResponse(b"bytes-A", filename="quest.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp_a2):
            res_a2 = fetch_url(url)

        self.assertEqual(res_a2.outcome, FetchOutcome.REUSED)
        # Exactly 2 StoredFiles: A and B
        self.assertEqual(StoredFile.objects.count(), 2)
        # Exactly 3 URLFetches
        self.assertEqual(URLFetch.objects.count(), 3)

        fetches = list(url.fetches.order_by("id"))
        self.assertEqual(fetches[0].stored_file, res_a1.stored_file)
        self.assertEqual(fetches[1].stored_file, res_b.stored_file)
        self.assertEqual(fetches[2].stored_file, res_a1.stored_file)

    def test_fetch_failure_records_error_and_preserves_history(self) -> None:
        game = self.create_game(105)
        url = self.create_url("https://example.com/games/quest.zip", game=game)

        # Initial successful fetch
        resp = MockResponse(b"initial-success", filename="quest.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            fetch_url(url)

        initial_stored = url.get_stored_file()
        self.assertIsNotNone(initial_stored)

        # Subsequent fetch fails
        with patch(
            "games.fetcher.FetchUrlToFileLike",
            side_effect=RuntimeError("HTTP 404 Not Found"),
        ):
            res_fail = fetch_url(url)

        self.assertEqual(res_fail.outcome, FetchOutcome.FAILED)
        self.assertIn("HTTP 404 Not Found", res_fail.error or "")

        url.refresh_from_db()
        self.assertTrue(url.is_link_broken())
        self.assertIsNotNone(url.failing_since)
        self.assertIn("HTTP 404 Not Found", url.last_error or "")
        self.assertEqual(URLFetch.objects.count(), 1)

        # Stored file and reader access remain intact!
        self.assertEqual(url.get_stored_file(), initial_stored)
        self.assertTrue(url.has_stored_copy())
        self.assertEqual(url.open_local_file().read(), b"initial-success")

        # Second consecutive failure keeps original failing_since
        orig_failing_since = url.failing_since
        with patch(
            "games.fetcher.FetchUrlToFileLike",
            side_effect=RuntimeError("HTTP 500 Server Error"),
        ):
            fetch_url(url)

        url.refresh_from_db()
        self.assertEqual(url.failing_since, orig_failing_since)
        self.assertIn("HTTP 500", url.last_error or "")

    def test_failure_followed_by_success_clears_health_state(self) -> None:
        game = self.create_game(106)
        url = self.create_url("https://example.com/games/quest.zip", game=game)

        # Fail first
        with patch(
            "games.fetcher.FetchUrlToFileLike",
            side_effect=RuntimeError("Network down"),
        ):
            fetch_url(url)

        url.refresh_from_db()
        self.assertTrue(url.is_link_broken())
        self.assertIsNotNone(url.failing_since)

        # Recover
        resp = MockResponse(b"recovered-bytes", filename="quest.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            res = fetch_url(url)

        self.assertEqual(res.outcome, FetchOutcome.CREATED)
        url.refresh_from_db()
        self.assertFalse(url.is_link_broken())
        self.assertIsNone(url.failing_since)
        self.assertIsNone(url.last_error)


class TestDeduplication(BaseFetcherTestCase):
    def test_two_urls_with_same_bytes_share_stored_file(self) -> None:
        game1 = self.create_game(201)
        game2 = self.create_game(202)

        url1 = self.create_url("https://site1.org/mirror/game.zip", game=game1)
        url2 = self.create_url("https://site2.org/mirror/game.zip", game=game2)

        content = b"shared-game-bytes-12345"

        resp1 = MockResponse(content, filename="game.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp1):
            res1 = fetch_url(url1)

        resp2 = MockResponse(content, filename="game.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp2):
            res2 = fetch_url(url2)

        self.assertEqual(res1.outcome, FetchOutcome.CREATED)
        self.assertEqual(res2.outcome, FetchOutcome.REUSED)
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(res1.stored_file, res2.stored_file)

        # Physical file is under game 201's namespace
        assert res1.stored_file is not None
        self.assertEqual(res1.stored_file.storage_path, "g/201/game.zip")
        # url2 points to that same physical file
        url2.refresh_from_db()
        self.assertIsNone(url2.local_url)
        self.assertEqual(url2.get_local_url(), "/f/g/201/game.zip")

    def test_uploaded_file_and_remote_url_share_stored_file(self) -> None:
        content = b"upload-and-remote-identical"
        digest = sha256(content).hexdigest()

        # Simulate existing backfilled upload in StoredFile
        upload_path = self.media_root / "uploads" / "myupload.zip"
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(content)

        stored = StoredFile.objects.create(
            content_hash=digest,
            storage_path="uploads/myupload.zip",
            file_size=len(content),
            created_at=now(),
        )

        game = self.create_game(203)
        remote_url = self.create_url("https://example.com/file.zip", game=game)

        resp = MockResponse(content, filename="file.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            res = fetch_url(remote_url)

        self.assertEqual(res.outcome, FetchOutcome.REUSED)
        self.assertEqual(res.stored_file, stored)
        self.assertEqual(StoredFile.objects.count(), 1)
        # No file created in g/203/
        self.assertFalse((self.media_root / "g" / "203").exists())


class TestStoragePathsAndCollisions(BaseFetcherTestCase):
    def test_game_scoped_storage_path(self) -> None:
        game = self.create_game(301)
        url = self.create_url(
            "https://example.com/downloads/adventure.zip", game=game
        )

        resp = MockResponse(b"adv-bytes", filename="adventure.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            res = fetch_url(url)

        assert res.stored_file is not None
        self.assertEqual(res.stored_file.storage_path, "g/301/adventure.zip")

    def test_multiple_games_use_lowest_game_id(self) -> None:
        game_high = self.create_game(350)
        game_low = self.create_game(310)

        url = self.create_url("https://example.com/multi.zip", game=game_high)
        GameURL.objects.create(game=game_low, url=url, category=self.category)

        resp = MockResponse(b"multi-game-bytes", filename="multi.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            res = fetch_url(url)

        assert res.stored_file is not None
        self.assertEqual(res.stored_file.storage_path, "g/310/multi.zip")

    def test_no_game_skips_fetch(self) -> None:
        url = self.create_url("https://example.com/alone.zip", game=None)

        resp = MockResponse(b"alone-bytes", filename="alone.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            res = fetch_url(url)

        self.assertEqual(res.outcome, FetchOutcome.SKIPPED)
        self.assertIsNone(res.stored_file)
        self.assertEqual(res.error, "URL is not referenced by any game")

    def test_determine_storage_path_without_game_uses_backups(self) -> None:
        path = determine_storage_path(
            candidate_filename="alone.zip", content_hash="hash123"
        )
        self.assertEqual(path, "backups/alone.zip")

    def test_collision_with_different_bytes_uses_short_hash(self) -> None:
        game = self.create_game(302)
        url1 = self.create_url("https://example.com/v1/release.zip", game=game)
        url2 = self.create_url("https://example.com/v2/release.zip", game=game)

        resp1 = MockResponse(b"release-v1", filename="release.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp1):
            res1 = fetch_url(url1)

        content2 = b"release-v2-different"
        digest2 = sha256(content2).hexdigest()
        resp2 = MockResponse(content2, filename="release.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp2):
            res2 = fetch_url(url2)

        assert res1.stored_file is not None
        assert res2.stored_file is not None

        self.assertEqual(res1.stored_file.storage_path, "g/302/release.zip")
        expected_collision = f"g/302/release-{digest2[:8]}.zip"
        self.assertEqual(res2.stored_file.storage_path, expected_collision)

        # Both physical files exist intact on disk
        self.assertTrue(
            (self.media_root / "g" / "302" / "release.zip").exists()
        )
        self.assertTrue(
            (
                self.media_root / "g" / "302" / f"release-{digest2[:8]}.zip"
            ).exists()
        )

    def test_same_filename_in_different_games_do_not_collide(self) -> None:
        game1 = self.create_game(303)
        game2 = self.create_game(304)

        url1 = self.create_url("https://game1.com/game.zip", game=game1)
        url2 = self.create_url("https://game2.com/game.zip", game=game2)

        resp1 = MockResponse(b"bytes-game-1", filename="game.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp1):
            res1 = fetch_url(url1)

        resp2 = MockResponse(b"bytes-game-2", filename="game.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp2):
            res2 = fetch_url(url2)

        assert res1.stored_file is not None
        assert res2.stored_file is not None
        self.assertEqual(res1.stored_file.storage_path, "g/303/game.zip")
        self.assertEqual(res2.stored_file.storage_path, "g/304/game.zip")

    def test_filename_sanitization(self) -> None:
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(
            sanitize_filename("my cool game.zip"), "my_cool_game.zip"
        )
        self.assertEqual(
            sanitize_filename("", content_type="application/zip"),
            "download.zip",
        )
        self.assertEqual(
            sanitize_filename(None, content_type="image/png"), "download.png"
        )
        self.assertEqual(sanitize_filename("игра (тест).z5"), "игра_тест.z5")


class TestFetchUrlsCommand(BaseFetcherTestCase):
    def test_fetch_urls_by_id(self) -> None:
        game = self.create_game(401)
        url = self.create_url("https://example.com/cmd.zip", game=game)

        resp = MockResponse(b"cmd-content", filename="cmd.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            call_command("fetch_urls", url_id=url.id, verbosity=1)

        url.refresh_from_db()
        self.assertIsNone(url.local_url)
        self.assertEqual(url.get_local_url(), "/f/g/401/cmd.zip")
        self.assertFalse(url.is_link_broken())

    def test_fetch_urls_by_game(self) -> None:
        game1 = self.create_game(402)
        game2 = self.create_game(403)

        url1 = self.create_url("https://example.com/g1.zip", game=game1)
        url2 = self.create_url("https://example.com/g2.zip", game=game2)

        resp = MockResponse(b"g1-content", filename="g1.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            call_command("fetch_urls", game_id=game1.id, verbosity=1)

        url1.refresh_from_db()
        url2.refresh_from_db()
        self.assertIsNotNone(url1.last_attempt)
        self.assertIsNone(url2.last_attempt)

    def test_fetch_urls_queue_ordering(self) -> None:
        game = self.create_game(404)
        t0 = now()

        # Never-attempted: older vs newer creation
        u_never_old = URL.objects.create(
            original_url="https://example.com/never_old.zip",
            is_uploaded=False,
            creation_date=t0 - timedelta(days=5),
        )
        u_never_new = URL.objects.create(
            original_url="https://example.com/never_new.zip",
            is_uploaded=False,
            creation_date=t0 - timedelta(days=1),
        )

        # Attempted: attempted longer ago vs recently
        u_att_old = URL.objects.create(
            original_url="https://example.com/att_old.zip",
            is_uploaded=False,
            creation_date=t0 - timedelta(days=10),
            last_attempt=t0 - timedelta(days=7),
        )
        u_att_recent = URL.objects.create(
            original_url="https://example.com/att_recent.zip",
            is_uploaded=False,
            creation_date=t0 - timedelta(days=10),
            last_attempt=t0 - timedelta(days=1),
        )

        for u in (u_never_old, u_never_new, u_att_old, u_att_recent):
            GameURL.objects.create(game=game, url=u, category=self.category)

        fetched_order: list[int] = []

        def mock_downloader(orig_url: str, **kwargs: Any) -> MockResponse:
            url_obj = URL.objects.get(original_url=orig_url)
            fetched_order.append(url_obj.id)
            return MockResponse(
                f"data-{url_obj.id}".encode(), filename="file.zip"
            )

        with patch(
            "games.fetcher.FetchUrlToFileLike", side_effect=mock_downloader
        ):
            call_command("fetch_urls", game_id=game.id, verbosity=0)

        # Expected order:
        # 1. Never attempted: newest creation first (u_never_new, then
        #    u_never_old)
        # 2. Attempted: oldest attempt first (u_att_old, then u_att_recent)
        expected_order = [
            u_never_new.id,
            u_never_old.id,
            u_att_old.id,
            u_att_recent.id,
        ]
        self.assertEqual(fetched_order, expected_order)

    def test_fetch_urls_skips_uploaded_urls(self) -> None:
        game = self.create_game(405)
        url_upload = self.create_url(
            "https://example.com/uploaded.zip",
            is_uploaded=True,
            game=game,
        )

        with patch("games.fetcher.FetchUrlToFileLike") as mock_fetch:
            call_command("fetch_urls", url_id=url_upload.id, force=True)

        mock_fetch.assert_not_called()
        url_upload.refresh_from_db()
        self.assertIsNone(url_upload.last_attempt)


class TestCleanupBadFetchesCommand(BaseFetcherTestCase):
    def test_cleanup_bad_fetches_dry_run_and_delete(self) -> None:
        game = self.create_game(406)
        url = self.create_url(
            "https://instead-games.ru/downloader.php?id=42", game=game
        )
        body = b"File not found: test.zip\r\n"
        sf = StoredFile.objects.create(
            content_hash="a" * 64,
            storage_path="g/406/test.zip",
            file_size=len(body),
            created_at=now(),
        )
        self.files_fs.save("g/406/test.zip", io.BytesIO(body))
        fetch = URLFetch.objects.create(
            url=url,
            stored_file=sf,
            content_type="text/plain",
            first_fetch=now(),
            last_fetch=now(),
        )

        with override_settings(FILES_FS=self.files_fs):
            out_dry = io.StringIO()
            call_command("cleanup_bad_fetches", stdout=out_dry)
            self.assertIn("Found 1 bad fetch(es)", out_dry.getvalue())
            self.assertIn("Dry run only", out_dry.getvalue())
            self.assertEqual(URLFetch.objects.filter(pk=fetch.pk).count(), 1)

            out_del = io.StringIO()
            call_command("cleanup_bad_fetches", delete=True, stdout=out_del)
            self.assertIn(
                "Successfully deleted 1 fetch(es)", out_del.getvalue()
            )
            self.assertFalse(URLFetch.objects.filter(pk=fetch.pk).exists())
            self.assertTrue(StoredFile.objects.filter(pk=sf.pk).exists())

            url.refresh_from_db()
            self.assertIsNone(url.local_url)
            self.assertIsNone(url.file_size)
            self.assertIsNone(url.get_local_url())
            self.assertIsNone(url.get_file_size())
            self.assertTrue(url.is_link_broken())
            self.assertIn("File not found", url.last_error or "")
