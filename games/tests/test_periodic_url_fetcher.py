import io
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.utils.timezone import now

from games.fetcher import (
    FetchOutcome,
    fetch_url,
    get_eligible_urls,
    run_fetch_urls,
)
from games.models import (
    URL,
    Game,
    GameURL,
    GameURLCategory,
    StoredFile,
    URLFetch,
)
from games.tasks import fetch_urls


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


class PeriodicUrlFetcherTestCase(TestCase):
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
        self.default_game = self.create_game(500, "Default Game")

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
        original_url: str,
        *,
        creation_date: datetime | None = None,
        last_attempt: datetime | None = None,
        is_uploaded: bool = False,
        allow_cloning: bool = True,
        game: Game | None = None,
        attach_game: bool = True,
    ) -> URL:
        created = creation_date or now()
        url = URL.objects.create(
            original_url=original_url,
            creation_date=created,
            last_attempt=last_attempt,
            is_uploaded=is_uploaded,
        )
        if attach_game:
            target_game = game or self.default_game
            category = self.category
            if not allow_cloning:
                category, _ = GameURLCategory.objects.get_or_create(
                    symbolic_id="no_clone",
                    defaults={"title": "No cloning", "allow_cloning": False},
                )
            GameURL.objects.create(
                game=target_game, url=url, category=category
            )
        return url

    def test_eligible_urls_ordering_never_attempted_then_attempted(
        self,
    ) -> None:
        base_time = now()
        # Older never-attempted URL
        u_never_old = self.create_url(
            "https://example.com/never-old.zip",
            creation_date=base_time - timedelta(days=5),
            last_attempt=None,
        )
        # Newer never-attempted URL
        u_never_new = self.create_url(
            "https://example.com/never-new.zip",
            creation_date=base_time - timedelta(days=1),
            last_attempt=None,
        )
        # Attempted long ago
        u_att_old = self.create_url(
            "https://example.com/att-old.zip",
            creation_date=base_time - timedelta(days=10),
            last_attempt=base_time - timedelta(days=3),
        )
        # Attempted recently
        u_att_recent = self.create_url(
            "https://example.com/att-recent.zip",
            creation_date=base_time - timedelta(days=10),
            last_attempt=base_time - timedelta(hours=1),
        )

        eligible = list(get_eligible_urls())
        self.assertEqual(
            eligible,
            [u_never_new, u_never_old, u_att_old, u_att_recent],
        )

    def test_eligible_urls_filters_uploaded_and_category(self) -> None:
        self.create_url(
            "https://example.com/uploaded.zip",
            is_uploaded=True,
        )
        self.create_url(
            "https://example.com/no-clone.zip",
            is_uploaded=False,
            allow_cloning=False,
        )
        valid = self.create_url(
            "https://example.com/valid.zip",
            is_uploaded=False,
        )

        eligible = list(get_eligible_urls())
        self.assertEqual(eligible, [valid])

        # If forced, non-cloneable URLs are included,
        # but uploaded URLs are still excluded.
        forced = list(get_eligible_urls(force=True))
        self.assertEqual(len(forced), 2)

    def test_eligible_urls_skips_urls_not_referenced_by_any_game(self) -> None:
        u_with_game = self.create_url(
            "https://example.com/with-game.zip",
            attach_game=True,
        )
        u_without_game = self.create_url(
            "https://example.com/without-game.zip",
            attach_game=False,
        )

        eligible = list(get_eligible_urls())
        self.assertIn(u_with_game, eligible)
        self.assertNotIn(u_without_game, eligible)

        # Even with force=True or explicit url_id, unreferenced URLs are out
        self.assertNotIn(u_without_game, list(get_eligible_urls(force=True)))
        self.assertEqual(list(get_eligible_urls(url_id=u_without_game.pk)), [])

        # Direct fetch_url skips it as well
        direct_res = fetch_url(u_without_game)
        self.assertEqual(direct_res.outcome, FetchOutcome.SKIPPED)
        self.assertEqual(direct_res.error, "URL is not referenced by any game")

    def test_eligible_urls_respects_limit(self) -> None:
        base_time = now()
        for i in range(5):
            self.create_url(
                f"https://example.com/file{i}.zip",
                creation_date=base_time - timedelta(minutes=i),
            )

        eligible = list(get_eligible_urls(limit=2))
        self.assertEqual(len(eligible), 2)

    def test_shared_url_uses_any_allowed_game_category(self) -> None:
        url = self.create_url(
            "https://example.com/shared.zip", allow_cloning=False
        )
        self.assertEqual(list(get_eligible_urls()), [])
        other_game = self.create_game(603)
        allowed = GameURL.objects.create(
            game=other_game, url=url, category=self.category
        )
        GameURL.objects.create(
            game=self.default_game, url=url, category=self.category
        )
        self.assertEqual(list(get_eligible_urls()), [url])
        self.assertEqual(list(get_eligible_urls(game_id=other_game.pk)), [url])

        allowed.delete()
        GameURL.objects.filter(url=url, category=self.category).delete()
        self.assertEqual(list(get_eligible_urls()), [])
        self.assertEqual(list(get_eligible_urls(force=True)), [url])

    def test_non_game_categories_do_not_make_url_eligible(self) -> None:
        from contest.models import (
            Competition,
            CompetitionURL,
            CompetitionURLCategory,
        )
        from games.models import (
            Personality,
            PersonalityUrl,
            PersonalityURLCategory,
        )

        url = self.create_url(
            "https://example.com/non-game.zip", attach_game=False
        )
        competition = Competition.objects.create(
            title="Competition",
            slug="competition",
            end_date=now().date(),
            published=True,
        )
        CompetitionURL.objects.create(
            competition=competition,
            url=url,
            category=CompetitionURLCategory.objects.create(
                title="Archive", allow_cloning=True
            ),
        )
        PersonalityUrl.objects.create(
            personality=Personality.objects.create(name="Author"),
            url=url,
            category=PersonalityURLCategory.objects.create(
                title="Avatar", allow_cloning=True
            ),
        )
        self.assertEqual(list(get_eligible_urls()), [])
        self.assertEqual(list(get_eligible_urls(force=True)), [])

    def test_eligible_urls_filters_by_url_id_and_game_id(self) -> None:
        game1 = self.create_game(601)
        game2 = self.create_game(602)
        u1 = self.create_url("https://example.com/g1.zip", game=game1)
        u2 = self.create_url("https://example.com/g2.zip", game=game2)

        self.assertEqual(list(get_eligible_urls(url_id=u1.pk)), [u1])
        self.assertEqual(list(get_eligible_urls(game_id=602)), [u2])

    def test_run_fetch_urls_never_attempted_then_rotates_to_back(self) -> None:
        base_time = now()
        u1 = self.create_url(
            "https://example.com/f1.zip",
            creation_date=base_time - timedelta(minutes=2),
        )
        u2 = self.create_url(
            "https://example.com/f2.zip",
            creation_date=base_time - timedelta(minutes=1),
        )

        resp = MockResponse(b"some-bytes", filename="file.zip")
        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            stats = run_fetch_urls(limit=1)

        self.assertEqual(stats.urls_examined, 1)
        self.assertEqual(stats.files_created, 1)

        # u2 was newer so it was fetched first. Now u2 has last_attempt set.
        u2.refresh_from_db()
        self.assertIsNotNone(u2.last_attempt)

        # Next run without limit: u1 (never attempted) should come first,
        # then u2 (attempted).
        remaining = list(get_eligible_urls())
        self.assertEqual(remaining, [u1, u2])

    def test_run_fetch_urls_unchanged_content_extends_last_fetch(self) -> None:
        url = self.create_url("https://example.com/unchanged.zip")

        with patch(
            "games.fetcher.FetchUrlToFileLike",
            side_effect=lambda *args, **kwargs: MockResponse(
                b"same-payload", filename="unchanged.zip"
            ),
        ):
            stats1 = run_fetch_urls()
            self.assertEqual(stats1.files_created, 1)

            first_fetch = URLFetch.objects.get(url=url)
            t1_first = first_fetch.first_fetch
            t1_last = first_fetch.last_fetch

            stats2 = run_fetch_urls()
            self.assertEqual(stats2.fetches_unchanged, 1)
            self.assertEqual(stats2.files_created, 0)

            first_fetch.refresh_from_db()
            self.assertEqual(first_fetch.first_fetch, t1_first)
            self.assertGreaterEqual(first_fetch.last_fetch, t1_last)
            self.assertEqual(URLFetch.objects.filter(url=url).count(), 1)
            self.assertEqual(StoredFile.objects.count(), 1)

    def test_run_fetch_urls_changed_content_creates_new_fetch_row(
        self,
    ) -> None:
        url = self.create_url("https://example.com/updating.zip")
        resp1 = MockResponse(b"version-1", filename="updating.zip")
        resp2 = MockResponse(b"version-2", filename="updating.zip")

        with patch(
            "games.fetcher.FetchUrlToFileLike", side_effect=[resp1, resp2]
        ):
            stats1 = run_fetch_urls()
            self.assertEqual(stats1.files_created, 1)

            stats2 = run_fetch_urls()
            self.assertEqual(stats2.files_created, 1)

        self.assertEqual(URLFetch.objects.filter(url=url).count(), 2)
        self.assertEqual(StoredFile.objects.count(), 2)

    def test_run_fetch_urls_duplicate_bytes_reuses_stored_file(self) -> None:
        u1 = self.create_url("https://example.com/source1.zip")
        u2 = self.create_url("https://example.com/source2.zip")
        content = b"shared-identical-content"

        resp1 = MockResponse(content, filename="source1.zip")
        resp2 = MockResponse(content, filename="source2.zip")

        with patch(
            "games.fetcher.FetchUrlToFileLike", side_effect=[resp1, resp2]
        ):
            stats = run_fetch_urls()

        self.assertEqual(stats.files_created, 1)
        self.assertEqual(stats.files_reused, 1)
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(URLFetch.objects.count(), 2)
        self.assertIsNotNone(u1.get_stored_file())
        self.assertEqual(u1.get_stored_file(), u2.get_stored_file())

    def test_run_fetch_urls_failure_preserves_last_successful_file(
        self,
    ) -> None:
        url = self.create_url("https://example.com/flake.zip")
        good_resp = MockResponse(b"initial-good-bytes", filename="flake.zip")

        with patch("games.fetcher.FetchUrlToFileLike", return_value=good_resp):
            stats1 = run_fetch_urls()
            self.assertEqual(stats1.files_created, 1)

        url.refresh_from_db()
        self.assertFalse(url.is_link_broken())
        stored_file_before = url.get_stored_file()
        self.assertIsNotNone(stored_file_before)

        # Now simulate network failure on refetch
        with patch(
            "games.fetcher.FetchUrlToFileLike",
            side_effect=RuntimeError("500 Internal Server Error"),
        ):
            stats2 = run_fetch_urls()
            self.assertEqual(stats2.fetches_failed, 1)

        url.refresh_from_db()
        self.assertTrue(url.is_link_broken())
        self.assertIsNotNone(url.failing_since)
        self.assertIn("500 Internal Server Error", url.last_error or "")
        # Stored file and URLFetch from previous fetch are preserved intact
        self.assertEqual(url.get_stored_file(), stored_file_before)
        self.assertEqual(URLFetch.objects.filter(url=url).count(), 1)

        # Recovery clears failure state
        recover_resp = MockResponse(b"recovered-bytes", filename="flake.zip")
        with patch(
            "games.fetcher.FetchUrlToFileLike", return_value=recover_resp
        ):
            stats3 = run_fetch_urls()
            self.assertIn(stats3.files_created, (0, 1))
            self.assertEqual(stats3.fetches_failed, 0)

        url.refresh_from_db()
        self.assertFalse(url.is_link_broken())
        self.assertIsNone(url.failing_since)
        self.assertIsNone(url.last_error)

    def test_celery_fetch_urls_task(self) -> None:
        url = self.create_url("https://example.com/task-test.zip")
        resp = MockResponse(b"celery-test-bytes", filename="task-test.zip")

        with patch("games.fetcher.FetchUrlToFileLike", return_value=resp):
            async_res = fetch_urls.apply(kwargs={"limit": 5})

        self.assertTrue(async_res.successful())
        result = async_res.result
        self.assertEqual(result["urls_examined"], 1)
        self.assertEqual(result["files_created"], 1)
        self.assertEqual(result["fetches_failed"], 0)
        self.assertTrue(url.has_stored_copy())
