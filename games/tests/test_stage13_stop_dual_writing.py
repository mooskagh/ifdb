import hashlib
import io
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils.timezone import now

from contest.models import Competition, CompetitionURL, CompetitionURLCategory
from core.models import User
from games.fetcher import FetchOutcome, fetch_url
from games.game_details import GameDetailsBuilder
from games.gameinfo import GameInfo, GameUrl
from games.models import (
    URL,
    Game,
    GameURL,
    GameURLCategory,
    Personality,
    PersonalityUrl,
    PersonalityURLCategory,
    StoredFile,
    URLFetch,
)
from games.search import SB_AuxFlags


class MockResponse:
    def __init__(
        self,
        content: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ):
        self._content = content
        self._pos = 0
        self.metadata = {
            "filename": filename,
            "content-type": content_type,
        }

    def read(self, size: int = -1) -> bytes:
        if self._pos >= len(self._content):
            return b""
        if size < 0:
            chunk = self._content[self._pos :]
            self._pos = len(self._content)
            return chunk
        chunk = self._content[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        pass


class Stage13StopDualWritingTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.media_root = self.temp_dir.name
        self.files_fs = FileSystemStorage(
            location=self.media_root, base_url="/f/"
        )

        self.game = Game.objects.create(
            title="Stage 13 Test Game",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        self.cat_download = GameURLCategory.objects.create(
            title="Direct Download",
            symbolic_id="download_direct",
            allow_cloning=True,
        )
        self.cat_poster = GameURLCategory.objects.create(
            title="Poster",
            symbolic_id="poster",
            allow_cloning=True,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fetch_success_does_not_write_legacy_fields_on_url(self) -> None:
        url = URL.objects.create(
            original_url="https://example.com/quest.zip",
            creation_date=now(),
            ok_to_clone=True,
        )
        GameURL.objects.create(
            game=self.game,
            url=url,
            category=self.cat_download,
        )

        content = b"stage-13-quest-content"
        resp = MockResponse(
            content, filename="quest.zip", content_type="application/zip"
        )

        with (
            override_settings(FILES_FS=self.files_fs),
            patch("games.fetcher.FetchUrlToFileLike", return_value=resp),
        ):
            res = fetch_url(url)

        self.assertEqual(res.outcome, FetchOutcome.CREATED)

        url.refresh_from_db()
        # Legacy fields MUST NOT be populated
        self.assertIsNone(url.local_url)
        self.assertIsNone(url.file_size)
        self.assertIsNone(url.original_filename)
        self.assertIsNone(url.content_type)
        self.assertFalse(url.is_broken)

        # Health fields MUST be updated
        self.assertIsNotNone(url.last_attempt)
        self.assertIsNone(url.failing_since)
        self.assertIsNone(url.last_error)

        # Accessors MUST return values from StoredFile and URLFetch
        self.assertEqual(url.get_local_url(), f"/f/g/{self.game.id}/quest.zip")
        self.assertEqual(url.get_file_size(), len(content))
        self.assertEqual(url.get_original_filename(), "quest.zip")
        self.assertEqual(url.get_content_type(), "application/zip")
        self.assertFalse(url.is_link_broken())

    def test_fetch_failure_does_not_set_is_broken_but_sets_health(
        self,
    ) -> None:
        url = URL.objects.create(
            original_url="https://example.com/failing.zip",
            creation_date=now(),
            ok_to_clone=True,
        )
        GameURL.objects.create(
            game=self.game,
            url=url,
            category=self.cat_download,
        )

        with (
            override_settings(FILES_FS=self.files_fs),
            patch(
                "games.fetcher.FetchUrlToFileLike",
                side_effect=RuntimeError("HTTP 500 Internal Server Error"),
            ),
        ):
            res = fetch_url(url)

        self.assertEqual(res.outcome, FetchOutcome.FAILED)

        url.refresh_from_db()
        # Legacy field MUST NOT be updated to True
        self.assertFalse(url.is_broken)
        # Health state MUST be set
        self.assertIsNotNone(url.last_attempt)
        self.assertIsNotNone(url.failing_since)
        self.assertEqual(url.last_error, "HTTP 500 Internal Server Error")
        # is_link_broken returns True
        self.assertTrue(url.is_link_broken())

    def test_never_attempted_url_is_not_broken(self) -> None:
        # A URL marked is_broken=True historically, but never attempted under
        # the new system
        url = URL.objects.create(
            original_url="https://example.com/unattempted.zip",
            creation_date=now(),
            last_attempt=None,
            is_broken=True,
        )
        # Broken means actively tried and failed; unattempted is NOT broken
        self.assertFalse(url.is_link_broken())

    def test_recovered_url_clears_health_without_clearing_legacy_is_broken(
        self,
    ) -> None:
        # Legacy URL with is_broken=True
        url = URL.objects.create(
            original_url="https://example.com/recover.zip",
            creation_date=now(),
            ok_to_clone=True,
            is_broken=True,
            failing_since=now(),
            last_error="Old error",
        )
        GameURL.objects.create(
            game=self.game,
            url=url,
            category=self.cat_download,
        )

        content = b"recovered-bytes"
        resp = MockResponse(
            content, filename="recover.zip", content_type="application/zip"
        )

        with (
            override_settings(FILES_FS=self.files_fs),
            patch("games.fetcher.FetchUrlToFileLike", return_value=resp),
        ):
            res = fetch_url(url)

        self.assertEqual(res.outcome, FetchOutcome.CREATED)
        url.refresh_from_db()
        # Legacy is_broken was NOT written (still True in DB)
        self.assertTrue(url.is_broken)
        # But health state cleared
        self.assertIsNone(url.failing_since)
        self.assertIsNone(url.last_error)
        # And application reads report NOT broken
        self.assertFalse(url.is_link_broken())

    def test_cleanup_bad_fetches_does_not_write_legacy_fields(self) -> None:
        url = URL.objects.create(
            original_url="https://instead-games.ru/bad.html",
            creation_date=now(),
            ok_to_clone=True,
        )
        GameURL.objects.create(
            game=self.game,
            url=url,
            category=self.cat_download,
        )
        body = b"File not found: /path/to/game"
        sf = StoredFile.objects.create(
            content_hash=hashlib.sha256(body).hexdigest(),
            storage_path=f"g/{self.game.id}/bad.html",
            file_size=len(body),
            created_at=now(),
        )
        self.files_fs.save(f"g/{self.game.id}/bad.html", io.BytesIO(body))
        URLFetch.objects.create(
            url=url,
            stored_file=sf,
            content_type="text/plain",
            first_fetch=now(),
            last_fetch=now(),
        )

        with override_settings(FILES_FS=self.files_fs):
            call_command("cleanup_bad_fetches", delete=True)

        url.refresh_from_db()
        # Legacy fields are None / untouched
        self.assertIsNone(url.local_url)
        self.assertIsNone(url.file_size)
        self.assertFalse(url.is_broken)
        # Health state reflects failure
        self.assertIsNotNone(url.failing_since)
        self.assertIn("File not found", url.last_error or "")
        self.assertTrue(url.is_link_broken())

    def test_search_query_6_uses_failing_since_and_last_error_only(
        self,
    ) -> None:
        # Game with failing URL (failing_since set)
        game_failing = Game.objects.create(
            title="Failing Game",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        url_failing = URL.objects.create(
            original_url="https://example.com/fail.zip",
            creation_date=now(),
            failing_since=now(),
            last_error="404",
        )
        GameURL.objects.create(
            game=game_failing, url=url_failing, category=self.cat_download
        )

        # Game with never-attempted URL that has is_broken=True
        game_unattempted = Game.objects.create(
            title="Unattempted Legacy Broken Game",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        url_unattempted = URL.objects.create(
            original_url="https://example.com/legacy_broken.zip",
            creation_date=now(),
            last_attempt=None,
            is_broken=True,
        )
        GameURL.objects.create(
            game=game_unattempted,
            url=url_unattempted,
            category=self.cat_download,
        )

        # Game with healthy URL
        game_healthy = Game.objects.create(
            title="Healthy Game",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        url_healthy = URL.objects.create(
            original_url="https://example.com/healthy.zip",
            creation_date=now(),
            last_attempt=now(),
        )
        GameURL.objects.create(
            game=game_healthy, url=url_healthy, category=self.cat_download
        )

        matched_ids = list(
            Game.objects.filter(SB_AuxFlags.QUERIES[6]).values_list(
                "id", flat=True
            )
        )

        self.assertIn(game_failing.id, matched_ids)
        self.assertNotIn(game_unattempted.id, matched_ids)
        self.assertNotIn(game_healthy.id, matched_ids)

    def test_curation_game_url_list_state_filters(self) -> None:
        user = User.objects.create_superuser(
            username="curator_test",
            email="curator@example.com",
            password="pass",
        )
        client = Client()
        client.force_login(user)

        # Failing URL
        url_failed = URL.objects.create(
            original_url="https://example.com/curation_fail.zip",
            creation_date=now(),
            ok_to_clone=True,
            failing_since=now(),
            last_error="Error 500",
        )
        GameURL.objects.create(
            game=self.game, url=url_failed, category=self.cat_download
        )

        # Healthy URL
        url_ok = URL.objects.create(
            original_url="https://example.com/curation_ok.zip",
            creation_date=now(),
            ok_to_clone=True,
            last_attempt=now(),
        )
        GameURL.objects.create(
            game=self.game, url=url_ok, category=self.cat_download
        )

        # Never-attempted URL with legacy is_broken=True
        url_unattempted = URL.objects.create(
            original_url="https://example.com/curation_unattempted.zip",
            creation_date=now(),
            ok_to_clone=True,
            last_attempt=None,
            is_broken=True,
        )
        GameURL.objects.create(
            game=self.game, url=url_unattempted, category=self.cat_download
        )

        resp_failed = client.get("/curation/files/?state=failed")
        self.assertEqual(resp_failed.status_code, 200)
        failed_urls = list(resp_failed.context["urls"])
        self.assertIn(url_failed, failed_urls)
        self.assertNotIn(url_ok, failed_urls)
        self.assertNotIn(url_unattempted, failed_urls)

        resp_ok = client.get("/curation/files/?state=ok")
        self.assertEqual(resp_ok.status_code, 200)
        ok_urls = list(resp_ok.context["urls"])
        self.assertIn(url_ok, ok_urls)
        self.assertNotIn(url_failed, ok_urls)

    def test_curation_file_detail_does_not_render_broken_property(
        self,
    ) -> None:
        user = User.objects.create_superuser(
            username="curator_detail_test",
            email="curator_detail@example.com",
            password="pass",
        )
        client = Client()
        client.force_login(user)

        url = URL.objects.create(
            original_url="https://example.com/detail.zip",
            creation_date=now(),
            failing_since=now(),
            last_error="404 Not Found",
            is_broken=True,
        )
        GameURL.objects.create(
            game=self.game, url=url, category=self.cat_download
        )

        resp = client.get(f"/curation/files/{url.pk}/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        # Under "Свойства", "битая ссылка" must NOT appear
        self.assertNotIn("битая ссылка", content)
        # Dedicated error display should still appear
        self.assertIn("404 Not Found", content)

    def test_personality_url_and_competition_url_is_broken(self) -> None:
        url_failing = URL.objects.create(
            original_url="https://example.com/pers.zip",
            creation_date=now(),
            failing_since=now(),
            last_error="Connection refused",
        )
        url_healthy = URL.objects.create(
            original_url="https://example.com/pers_ok.zip",
            creation_date=now(),
            last_attempt=now(),
        )

        pers = Personality.objects.create(name="Author Person")
        pcat = PersonalityURLCategory.objects.create(title="Homepage")
        purl_failing = PersonalityUrl.objects.create(
            personality=pers, url=url_failing, category=pcat
        )
        purl_healthy = PersonalityUrl.objects.create(
            personality=pers, url=url_healthy, category=pcat
        )

        self.assertTrue(purl_failing.is_broken)
        self.assertTrue(purl_failing.is_link_broken())
        self.assertFalse(purl_healthy.is_broken)
        self.assertFalse(purl_healthy.is_link_broken())

        comp = Competition.objects.create(
            title="Comp 2026",
            slug="comp-2026",
            end_date=now().date(),
            published=True,
        )
        ccat = CompetitionURLCategory.objects.create(title="Downloads")
        curl_failing = CompetitionURL.objects.create(
            competition=comp, url=url_failing, category=ccat
        )
        curl_healthy = CompetitionURL.objects.create(
            competition=comp, url=url_healthy, category=ccat
        )

        self.assertTrue(curl_failing.is_broken)
        self.assertTrue(curl_failing.is_link_broken())
        self.assertFalse(curl_healthy.is_broken)
        self.assertFalse(curl_healthy.is_link_broken())

    def test_game_details_builder_with_no_legacy_fields(self) -> None:
        url = URL.objects.create(
            original_url="https://example.com/play.zip",
            creation_date=now(),
            last_attempt=now(),
            # Legacy fields all None
            local_url=None,
            local_filename=None,
            file_size=None,
            original_filename=None,
            content_type=None,
            is_broken=False,
        )
        sf = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"game-data").hexdigest(),
            storage_path=f"g/{self.game.id}/play.zip",
            file_size=9,
            created_at=now(),
        )
        URLFetch.objects.create(
            url=url,
            stored_file=sf,
            original_filename="play.zip",
            first_fetch=now(),
            last_fetch=now(),
        )
        GameURL.objects.create(
            game=self.game,
            url=url,
            category=self.cat_download,
            description="Play File",
        )

        builder = GameDetailsBuilder(
            GameInfo(
                name=self.game.title,
                urls=[
                    GameUrl(
                        category="download_direct",
                        url_id=url.id,
                        description="Play File",
                        url="https://example.com/play.zip",
                    )
                ],
            )
        )
        urls = builder.GetUrls()
        self.assertEqual(len(urls), 1)
        item = urls[0]
        self.assertEqual(item.local_url, f"/f/g/{self.game.id}/play.zip")
        self.assertEqual(item.GetLocalUrl(), f"/f/g/{self.game.id}/play.zip")
        self.assertFalse(item.is_broken)
        self.assertTrue(item.has_local_copy)
        self.assertTrue(item.HasLocalCopy())

    def test_rollback_via_feature_flag_returns_is_broken(self) -> None:
        url = URL.objects.create(
            original_url="https://example.com/rollback.zip",
            creation_date=now(),
            failing_since=now(),
            last_error="Error",
            is_broken=False,
        )
        with override_settings(USE_STORED_FILE_READS=False):
            self.assertFalse(url.is_link_broken())
