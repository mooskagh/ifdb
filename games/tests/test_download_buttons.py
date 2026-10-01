import hashlib
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from django.core.files.storage import FileSystemStorage
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings

from games.game_details import (
    GameDetailsBuilder,
    format_compact_file_size,
)
from games.gameinfo import GameInfo, GameUrl
from games.models import (
    URL,
    Game,
    GameURLCategory,
    StoredFile,
    URLFetch,
)


class FormatCompactFileSizeTests(TestCase):
    def test_none_and_negative(self) -> None:
        self.assertIsNone(format_compact_file_size(None))
        self.assertIsNone(format_compact_file_size(-10))

    def test_bytes(self) -> None:
        self.assertEqual(format_compact_file_size(0), "0Б")
        self.assertEqual(format_compact_file_size(500), "500Б")
        self.assertEqual(format_compact_file_size(1023), "1023Б")

    def test_kilobytes(self) -> None:
        self.assertEqual(format_compact_file_size(1024), "1КБ")
        self.assertEqual(format_compact_file_size(1536), "1.5КБ")
        self.assertEqual(format_compact_file_size(512000), "500КБ")

    def test_megabytes(self) -> None:
        self.assertEqual(format_compact_file_size(1024 * 1024), "1МБ")
        # 23.4 MB
        size = int(23.4 * 1024 * 1024)
        self.assertEqual(format_compact_file_size(size), "23.4МБ")

    def test_gigabytes(self) -> None:
        self.assertEqual(format_compact_file_size(1024 * 1024 * 1024), "1ГБ")
        size = int(1.2 * 1024 * 1024 * 1024)
        self.assertEqual(format_compact_file_size(size), "1.2ГБ")


class DownloadButtonsTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.media_root = self.temp_dir.name
        self.files_fs = FileSystemStorage(
            location=self.media_root, base_url="/f/"
        )
        self.cat_direct = GameURLCategory.objects.create(
            title="Скачать (прямая ссылка)",
            symbolic_id="download_direct",
            allow_cloning=True,
        )
        self.cat_landing = GameURLCategory.objects.create(
            title="Скачать (файлообменник)",
            symbolic_id="download_landing",
            allow_cloning=False,
        )
        self.game = Game.objects.create(
            title="Test Game",
            state=Game.State.PUBLISHED,
            creation_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_single_unfetched_url(self) -> None:
        url = URL.objects.create(
            original_url="https://qsp.org/games/test.zip",
            creation_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        info = GameInfo(
            name="Test Game",
            urls=[GameUrl("download_direct", url.id, "Скачать", None)],
        )
        content = GameDetailsBuilder(info).GetContentDict()
        self.assertEqual(len(content.download_groups), 1)
        group = content.download_groups[0]
        self.assertFalse(group.has_dropdown)
        self.assertFalse(group.main_button.is_local)
        self.assertFalse(group.main_button.is_link_broken)
        self.assertEqual(
            group.main_button.url, "https://qsp.org/games/test.zip"
        )
        self.assertEqual(group.main_button.title, "Скачать")

    def test_broken_external_url(self) -> None:
        url = URL.objects.create(
            original_url="https://broken.com/game.zip",
            creation_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            failing_since=datetime(2025, 1, 2, tzinfo=timezone.utc),
            last_error="404 Not Found",
        )
        info = GameInfo(
            name="Test Game",
            urls=[GameUrl("download_direct", url.id, "Скачать", None)],
        )
        content = GameDetailsBuilder(info).GetContentDict()
        group = content.download_groups[0]
        self.assertTrue(group.main_button.is_link_broken)
        self.assertFalse(group.main_button.is_local)

    def test_url_with_successful_local_fetch(self) -> None:
        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"gamecontent").hexdigest(),
            storage_path="g/1/game.zip",
            file_size=24536678,  # ~23.4MB
        )
        url = URL.objects.create(
            original_url="https://qsp.org/games/test.zip",
            creation_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        URLFetch.objects.create(
            url=url,
            stored_file=stored,
            original_filename="game.zip",
            first_fetch=datetime(2025, 1, 2, tzinfo=timezone.utc),
            last_fetch=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        info = GameInfo(
            name="Test Game",
            urls=[GameUrl("download_direct", url.id, "Скачать", None)],
        )
        with override_settings(FILES_FS=self.files_fs):
            content = GameDetailsBuilder(info).GetContentDict()
            self.assertEqual(len(content.download_groups), 1)
            group = content.download_groups[0]
            # Has dropdown because local copy is main, external is dropdown
            self.assertTrue(group.has_dropdown)
            self.assertTrue(group.main_button.is_local)
            self.assertEqual(group.main_button.url, "/f/g/1/game.zip")
            self.assertEqual(group.main_button.title, "Скачать (23.4МБ)")
            self.assertEqual(group.main_button.filename, "game.zip")

            self.assertEqual(len(group.dropdown_items), 1)
            dropdown_item = group.dropdown_items[0]
            self.assertFalse(dropdown_item.is_local)
            self.assertEqual(
                dropdown_item.url, "https://qsp.org/games/test.zip"
            )
            self.assertEqual(dropdown_item.title, "Скачать с qsp.org")

    def test_grouped_by_content_hash(self) -> None:
        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"sharedbytes").hexdigest(),
            storage_path="g/1/shared.zip",
            file_size=1048576,  # 1MB
        )
        url1 = URL.objects.create(
            original_url="https://mirror1.com/game.zip",
            creation_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        URLFetch.objects.create(
            url=url1,
            stored_file=stored,
            original_filename="shared.zip",
            first_fetch=datetime(2025, 1, 2, tzinfo=timezone.utc),
            last_fetch=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        url2 = URL.objects.create(
            original_url="https://mirror2.org/download.zip",
            creation_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        URLFetch.objects.create(
            url=url2,
            stored_file=stored,
            original_filename="shared.zip",
            first_fetch=datetime(2025, 1, 2, tzinfo=timezone.utc),
            last_fetch=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )

        info = GameInfo(
            name="Test Game",
            urls=[
                GameUrl("download_direct", url1.id, "Основная ссылка", None),
                GameUrl("download_direct", url2.id, "Зеркало", None),
            ],
        )
        with override_settings(FILES_FS=self.files_fs):
            content = GameDetailsBuilder(info).GetContentDict()
            # Must be grouped into a single group!
            self.assertEqual(len(content.download_groups), 1)
            group = content.download_groups[0]
            self.assertTrue(group.has_dropdown)
            self.assertEqual(group.main_button.title, "Основная ссылка (1МБ)")
            self.assertEqual(group.main_button.url, "/f/g/1/shared.zip")

            self.assertEqual(len(group.dropdown_items), 2)
            self.assertEqual(
                group.dropdown_items[0].url, "https://mirror1.com/game.zip"
            )
            self.assertEqual(group.dropdown_items[0].title, "Основная ссылка")
            self.assertEqual(
                group.dropdown_items[1].url, "https://mirror2.org/download.zip"
            )
            self.assertEqual(group.dropdown_items[1].title, "Зеркало")

    def test_older_versions_under_url(self) -> None:
        stored_old1 = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"v1").hexdigest(),
            storage_path="g/1/v1.zip",
            file_size=10485760,  # 10MB
        )
        stored_old2 = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"v2").hexdigest(),
            storage_path="g/1/v2.zip",
            file_size=15728640,  # 15MB
        )
        stored_latest = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"v3").hexdigest(),
            storage_path="g/1/v3.zip",
            file_size=20971520,  # 20MB
        )

        url = URL.objects.create(
            original_url="https://author.org/game.zip",
            creation_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )
        # Older fetch 1
        URLFetch.objects.create(
            url=url,
            stored_file=stored_old1,
            original_filename="game_v1.zip",
            first_fetch=datetime(2023, 5, 10, tzinfo=timezone.utc),
            last_fetch=datetime(2023, 8, 1, tzinfo=timezone.utc),
        )
        # Older fetch 2
        URLFetch.objects.create(
            url=url,
            stored_file=stored_old2,
            original_filename="game_v2.zip",
            first_fetch=datetime(2024, 1, 15, tzinfo=timezone.utc),
            last_fetch=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        # Latest fetch
        URLFetch.objects.create(
            url=url,
            stored_file=stored_latest,
            original_filename="game_v3.zip",
            first_fetch=datetime(2025, 1, 1, tzinfo=timezone.utc),
            last_fetch=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )

        info = GameInfo(
            name="Test Game",
            urls=[GameUrl("download_direct", url.id, "Скачать", None)],
        )
        with override_settings(FILES_FS=self.files_fs):
            content = GameDetailsBuilder(info).GetContentDict()
            group = content.download_groups[0]
            self.assertTrue(group.has_dropdown)
            self.assertEqual(group.main_button.title, "Скачать (20МБ)")
            self.assertEqual(group.main_button.url, "/f/g/1/v3.zip")

            self.assertEqual(len(group.dropdown_items), 1)
            item = group.dropdown_items[0]
            self.assertEqual(item.title, "Скачать с author.org")
            self.assertEqual(len(item.older_versions), 2)

            # Check ordering: newest first (v2 then v1)
            v2 = item.older_versions[0]
            self.assertEqual(v2.date_str, "2024-01-15")
            self.assertEqual(v2.size_str, "15МБ")
            self.assertEqual(v2.label, "Версия 2024-01-15 (15МБ)")
            self.assertEqual(v2.download_url, "/f/g/1/v2.zip")

            v1 = item.older_versions[1]
            self.assertEqual(v1.date_str, "2023-05-10")
            self.assertEqual(v1.size_str, "10МБ")
            self.assertEqual(v1.label, "Версия 2023-05-10 (10МБ)")
            self.assertEqual(v1.download_url, "/f/g/1/v1.zip")

    def test_template_rendering(self) -> None:
        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"templatebytes").hexdigest(),
            storage_path="g/1/game.zip",
            file_size=1048576,
        )
        url = URL.objects.create(
            original_url="https://site.org/game.zip",
            creation_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        URLFetch.objects.create(
            url=url,
            stored_file=stored,
            original_filename="game.zip",
            first_fetch=datetime(2025, 1, 2, tzinfo=timezone.utc),
            last_fetch=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        info = GameInfo(
            name="Test Game",
            urls=[GameUrl("download_direct", url.id, "Скачать", None)],
        )
        with override_settings(FILES_FS=self.files_fs):
            from django.contrib.auth.models import AnonymousUser

            rf = RequestFactory()
            request = rf.get("/game/1")
            request.user = AnonymousUser()
            builder = GameDetailsBuilder(info)
            game_page = builder.GetGameDict(self.game, request)

            rendered = render_to_string(
                "games/game_title_card.html",
                {
                    "download_groups": game_page.download_groups,
                    "game": self.game,
                },
                request=request,
            )

            # Check split button is rendered
            self.assertIn("button-split", rendered)
            self.assertIn("button-split-main", rendered)
            self.assertIn("button-split-arrow", rendered)
            self.assertIn("&#9660;", rendered)
            self.assertIn("Скачать (1МБ)", rendered)
            self.assertIn("/f/g/1/game.zip", rendered)
            # Check local download icon on main button
            self.assertIn("#download", rendered)
            # Check external download icon in dropdown
            self.assertIn("#download-external", rendered)
            self.assertIn("Скачать с site.org", rendered)
            self.assertIn("https://site.org/game.zip", rendered)
