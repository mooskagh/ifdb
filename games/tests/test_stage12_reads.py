import hashlib
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone as django_timezone

from contest.models import Competition, CompetitionURL, CompetitionURLCategory
from games.duplicates import get_duplicate_url_groups
from games.game_details import GameDetailsBuilder
from games.gameinfo import GameInfo, GameUrl
from games.models import (
    URL,
    Game,
    GameURL,
    GameURLCategory,
    StoredFile,
    URLFetch,
)


class Stage12ReadsTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.media_root = self.temp_dir.name
        self.files_fs = FileSystemStorage(
            location=self.media_root, base_url="/f/"
        )
        self.uploads_fs = FileSystemStorage(
            location=Path(self.media_root) / "uploads",
            base_url="/f/uploads/",
        )
        self.backups_fs = FileSystemStorage(
            location=Path(self.media_root) / "backups",
            base_url="/f/backups/",
        )

        self.game = Game.objects.create(
            title="Stage 12 Test Game",
            state=Game.State.PUBLISHED,
            creation_time=django_timezone.now(),
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

    def test_metadata_helpers_prefer_new_model(self) -> None:
        file_path = Path(self.media_root) / "g" / "1" / "archive.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"archive-content")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"archive-content").hexdigest(),
            storage_path="g/1/archive.zip",
            file_size=len(b"archive-content"),
        )
        url = URL.objects.create(
            original_url="https://example.com/archive.zip",
            creation_date=django_timezone.now(),
            original_filename="old_archive.zip",
            content_type="application/octet-stream",
            file_size=9999,
        )
        URLFetch.objects.create(
            url=url,
            stored_file=stored,
            original_filename="new_archive.zip",
            content_type="application/zip",
        )

        with override_settings(
            FILES_FS=self.files_fs,
            USE_STORED_FILE_READS=True,
        ):
            self.assertEqual(url.get_original_filename(), "new_archive.zip")
            self.assertEqual(url.get_content_type(), "application/zip")
            self.assertEqual(url.get_file_size(), len(b"archive-content"))

            # GameURL delegates
            game_url = GameURL.objects.create(
                game=self.game,
                url=url,
                category=self.cat_download,
            )
            self.assertEqual(
                game_url.get_original_filename(), "new_archive.zip"
            )
            self.assertEqual(game_url.get_content_type(), "application/zip")
            self.assertEqual(game_url.get_file_size(), len(b"archive-content"))

    def test_metadata_helpers_fallback_to_legacy(self) -> None:
        url = URL.objects.create(
            original_url="https://example.com/legacy.zip",
            creation_date=django_timezone.now(),
            original_filename="legacy.zip",
            content_type="application/zip",
            file_size=1234,
            local_filename="legacy.zip",
            local_url="/f/uploads/legacy.zip",
        )

        with override_settings(
            FILES_FS=self.files_fs,
            USE_STORED_FILE_READS=True,
        ):
            self.assertEqual(url.get_original_filename(), "legacy.zip")
            self.assertEqual(url.get_content_type(), "application/zip")
            self.assertEqual(url.get_file_size(), 1234)
            self.assertEqual(url.get_local_url(), "/f/uploads/legacy.zip")

    def test_feature_flag_rollback_uses_legacy_fields(self) -> None:
        file_path = Path(self.media_root) / "g" / "1" / "game.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"new-data")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"new-data").hexdigest(),
            storage_path="g/1/game.zip",
            file_size=len(b"new-data"),
        )
        url = URL.objects.create(
            original_url="https://example.com/game.zip",
            creation_date=django_timezone.now(),
            local_url="/f/uploads/old.zip",
            local_filename="old.zip",
            original_filename="old.zip",
            content_type="application/old",
            file_size=10,
        )
        URLFetch.objects.create(
            url=url,
            stored_file=stored,
            original_filename="new.zip",
            content_type="application/new",
        )

        # When feature flag is False, reads roll back to legacy fields
        with override_settings(
            FILES_FS=self.files_fs,
            USE_STORED_FILE_READS=False,
        ):
            self.assertIsNone(url.get_stored_file())
            self.assertEqual(url.get_local_url(), "/f/uploads/old.zip")
            self.assertEqual(url.get_original_filename(), "old.zip")
            self.assertEqual(url.get_content_type(), "application/old")
            self.assertEqual(url.get_file_size(), 10)

    def test_broken_link_derived_from_health_fields(self) -> None:
        # Failing URL with new health fields
        failing_url = URL.objects.create(
            original_url="https://example.com/fail.zip",
            creation_date=django_timezone.now(),
            failing_since=django_timezone.now(),
            last_error="Connection refused",
            is_broken=False,
        )
        self.assertTrue(failing_url.is_link_broken())
        self.assertTrue(failing_url.is_broken_link)

        # Healthy URL
        healthy_url = URL.objects.create(
            original_url="https://example.com/ok.zip",
            creation_date=django_timezone.now(),
            failing_since=None,
            last_error=None,
            is_broken=False,
        )
        self.assertFalse(healthy_url.is_link_broken())
        self.assertFalse(healthy_url.is_broken_link)

        # Legacy URL with is_broken=True and empty failing_since
        legacy_broken = URL.objects.create(
            original_url="https://example.com/legacy_broken.zip",
            creation_date=django_timezone.now(),
            is_broken=True,
        )
        # Broken requires actively trying and failing
        self.assertFalse(legacy_broken.is_link_broken())
        self.assertFalse(legacy_broken.is_broken_link)
        with override_settings(USE_STORED_FILE_READS=False):
            self.assertTrue(legacy_broken.is_link_broken())

        # GameURL delegates
        gu_failing = GameURL.objects.create(
            game=self.game,
            url=failing_url,
            category=self.cat_download,
        )
        self.assertTrue(gu_failing.is_link_broken())
        self.assertTrue(gu_failing.is_broken)

        gu_healthy = GameURL.objects.create(
            game=self.game,
            url=healthy_url,
            category=self.cat_download,
        )
        self.assertFalse(gu_healthy.is_link_broken())
        self.assertFalse(gu_healthy.is_broken)

    def test_competition_url_delegates(self) -> None:
        comp = Competition.objects.create(
            title="Delegates Competition",
            slug="delegates-comp",
            end_date=django_timezone.now().date(),
            published=True,
        )
        comp_cat = CompetitionURLCategory.objects.create(
            title="Logo",
            symbolic_id="logo",
            allow_cloning=True,
        )
        file_path = Path(self.media_root) / "backups" / "logo.png"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"logo-bytes")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"logo-bytes").hexdigest(),
            storage_path="backups/logo.png",
            file_size=len(b"logo-bytes"),
        )
        url = URL.objects.create(
            original_url="https://example.com/logo.png",
            creation_date=django_timezone.now(),
        )
        URLFetch.objects.create(url=url, stored_file=stored)

        comp_url = CompetitionURL.objects.create(
            competition=comp,
            url=url,
            category=comp_cat,
        )

        with override_settings(FILES_FS=self.files_fs):
            self.assertEqual(comp_url.get_stored_file(), stored)
            self.assertEqual(comp_url.get_local_url(), "/f/backups/logo.png")
            self.assertEqual(comp_url.GetLocalUrl(), "/f/backups/logo.png")
            self.assertTrue(comp_url.has_stored_copy(check_disk=True))
            self.assertFalse(comp_url.is_link_broken())
            self.assertFalse(comp_url.is_broken)

    def test_game_details_builder_with_stored_file(self) -> None:
        file_path = Path(self.media_root) / "g" / "1" / "game.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"game-binary")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"game-binary").hexdigest(),
            storage_path="g/1/game.zip",
            file_size=len(b"game-binary"),
        )
        url = URL.objects.create(
            original_url="https://example.com/game.zip",
            creation_date=django_timezone.now(),
        )
        URLFetch.objects.create(url=url, stored_file=stored)

        info = GameInfo(
            name="Details Test",
            urls=[
                GameUrl(
                    "download_direct",
                    url.id,
                    "Download File",
                    "https://example.com/game.zip",
                ),
            ],
        )

        with override_settings(FILES_FS=self.files_fs):
            content = GameDetailsBuilder(info).GetContentDict()
            self.assertEqual(len(content.download), 1)
            item = content.download[0]
            self.assertEqual(item.local_url, "/f/g/1/game.zip")
            self.assertEqual(item.GetLocalUrl(), "/f/g/1/game.zip")
            self.assertEqual(
                item.GetRemoteUrl(), "https://example.com/game.zip"
            )
            self.assertFalse(item.is_broken)
            self.assertTrue(item.has_local_copy)
            self.assertTrue(item.HasLocalCopy())
            self.assertEqual(item.url, url)

    def test_duplicate_url_grouping(self) -> None:
        file_path = Path(self.media_root) / "g" / "1" / "shared.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"shared-bytes")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"shared-bytes").hexdigest(),
            storage_path="g/1/shared.zip",
            file_size=len(b"shared-bytes"),
        )

        u1 = URL.objects.create(
            original_url="https://mirror1.com/game.zip",
            creation_date=django_timezone.now(),
        )
        u2 = URL.objects.create(
            original_url="https://mirror2.com/game.zip",
            creation_date=django_timezone.now(),
        )
        u3 = URL.objects.create(
            original_url="https://unique.com/unique.zip",
            creation_date=django_timezone.now(),
        )

        URLFetch.objects.create(url=u1, stored_file=stored)
        URLFetch.objects.create(url=u2, stored_file=stored)

        # u1 and u2 duplicate each other
        self.assertEqual(list(u1.get_duplicate_urls()), [u2])
        self.assertEqual(list(u2.get_duplicate_urls()), [u1])
        self.assertEqual(list(u3.get_duplicate_urls()), [])

        # Include self
        self.assertEqual(
            set(u1.get_duplicate_urls(include_self=True)), {u1, u2}
        )

        # GameURL duplicates
        gu1 = GameURL.objects.create(
            game=self.game,
            url=u1,
            category=self.cat_download,
        )
        gu2 = GameURL.objects.create(
            game=self.game,
            url=u2,
            category=self.cat_download,
        )
        self.assertEqual(list(gu1.get_duplicate_game_urls()), [gu2])

        # Global duplicate groups
        groups = get_duplicate_url_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].stored_file, stored)
        self.assertEqual(set(groups[0].urls), {u1, u2})
        self.assertEqual(groups[0].duplicate_count, 2)
        self.assertEqual(groups[0].potential_savings, len(b"shared-bytes"))

    def test_duplicate_report_command(self) -> None:
        file_path = Path(self.media_root) / "g" / "1" / "dup.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"duplicate-content")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"duplicate-content").hexdigest(),
            storage_path="g/1/dup.zip",
            file_size=len(b"duplicate-content"),
        )
        u1 = URL.objects.create(
            original_url="https://site-a.com/dup.zip",
            creation_date=django_timezone.now(),
        )
        u2 = URL.objects.create(
            original_url="https://site-b.com/dup.zip",
            creation_date=django_timezone.now(),
        )
        URLFetch.objects.create(url=u1, stored_file=stored)
        URLFetch.objects.create(url=u2, stored_file=stored)
        GameURL.objects.create(
            game=self.game,
            url=u1,
            category=self.cat_download,
        )

        out = StringIO()
        call_command("duplicate_report", stdout=out)
        output = out.getvalue()
        self.assertIn("Total duplicate groups: 1", output)
        self.assertIn("Total URLs involved:    2", output)
        self.assertIn(stored.storage_path, output)

    def test_legacy_fallback_report_command(self) -> None:
        # URL 1: migrated to StoredFile (no fallback required)
        file_path = Path(self.media_root) / "g" / "1" / "migrated.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"migrated")
        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"migrated").hexdigest(),
            storage_path="g/1/migrated.zip",
            file_size=len(b"migrated"),
        )
        u_migrated = URL.objects.create(
            original_url="https://example.com/migrated.zip",
            local_filename="migrated.zip",
            local_url="/f/uploads/migrated.zip",
            creation_date=django_timezone.now(),
        )
        URLFetch.objects.create(url=u_migrated, stored_file=stored)

        # URL 2: has legacy fields, but NO URLFetch (requires fallback)
        URL.objects.create(
            original_url="https://example.com/unmigrated.zip",
            local_filename="unmigrated.zip",
            local_url="/f/uploads/unmigrated.zip",
            creation_date=django_timezone.now(),
        )

        with override_settings(FILES_FS=self.files_fs):
            out = StringIO()
            call_command("legacy_fallback_report", "--details", stdout=out)
            output = out.getvalue()
            self.assertIn("Total URLs with legacy local fields: 2", output)
            self.assertIn("Fully migrated URLs (using StoredFile): 1", output)
            self.assertIn("URLs requiring legacy fallback:      1", output)
            self.assertIn("no_url_fetch", output)
            self.assertIn("unmigrated.zip", output)
