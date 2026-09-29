import hashlib
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.utils import timezone as django_timezone

from curation.views import _build_playable_files
from games.models import (
    URL,
    Game,
    GameURL,
    GameURLCategory,
    StoredFile,
    URLFetch,
)
from play.blueprint import (
    BlueprintInfo,
    BlueprintSpec,
    Compatibility,
    GenerateResult,
    GenerateSpec,
)
from play.models import Playable
from play.tasks import generate_playable


class DummyBlueprint:
    def get_spec(self) -> BlueprintSpec:
        return BlueprintSpec(
            name="Dummy",
            versions=["1.0.0"],
        )

    def accepts(
        self, filename: Path, **kwargs: object
    ) -> Compatibility | bool:
        return filename.name.endswith(".zip")

    def generate(self, spec: GenerateSpec) -> GenerateResult | None:
        spec.destination.mkdir(parents=True, exist_ok=True)
        return GenerateResult(player_name="DummyPlayer")


class FileAccessHelpersTests(TestCase):
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

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_stored_file_helpers(self) -> None:
        file_path = Path(self.media_root) / "g" / "1" / "game.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"game-content")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"game-content").hexdigest(),
            storage_path="g/1/game.zip",
            file_size=len(b"game-content"),
        )

        with override_settings(FILES_FS=self.files_fs):
            self.assertEqual(stored.public_url, "/f/g/1/game.zip")
            self.assertEqual(stored.path, file_path)
            self.assertTrue(stored.exists())
            with stored.open("rb") as f:
                self.assertEqual(f.read(), b"game-content")

    def test_url_with_stored_file_helpers(self) -> None:
        file_path = Path(self.media_root) / "g" / "42" / "test.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"content-42")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"content-42").hexdigest(),
            storage_path="g/42/test.zip",
            file_size=len(b"content-42"),
        )
        url = URL.objects.create(
            original_url="https://example.com/test.zip",
            creation_date=django_timezone.now(),
        )

        t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)
        URLFetch.objects.create(
            url=url,
            stored_file=stored,
            first_fetch=t1,
            last_fetch=t2,
        )

        with override_settings(FILES_FS=self.files_fs):
            # Latest fetch
            latest_fetch = url.get_latest_fetch()
            self.assertIsNotNone(latest_fetch)
            self.assertEqual(latest_fetch.stored_file, stored)
            self.assertEqual(url.latest_fetch, latest_fetch)

            # Stored file
            self.assertEqual(url.get_stored_file(), stored)
            self.assertEqual(url.stored_file, stored)

            # Public and local URL
            self.assertEqual(url.get_local_url(), "/f/g/42/test.zip")
            self.assertEqual(url.GetLocalUrl(), "/f/g/42/test.zip")

            # Stored copy check
            self.assertTrue(url.has_stored_copy(check_disk=False))
            self.assertTrue(url.has_stored_copy(check_disk=True))
            self.assertTrue(url.HasLocalCopy())

            # Path check
            self.assertEqual(
                url.get_local_file_path(must_exist=False), file_path
            )
            self.assertEqual(
                url.get_local_file_path(must_exist=True), file_path
            )

            # Open local file
            with url.open_local_file("rb") as f:
                self.assertEqual(f.read(), b"content-42")

    def test_url_with_stored_file_missing_on_disk(self) -> None:
        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"missing").hexdigest(),
            storage_path="g/99/missing.zip",
            file_size=123,
        )
        url = URL.objects.create(
            original_url="https://example.com/missing.zip",
            creation_date=django_timezone.now(),
        )
        URLFetch.objects.create(url=url, stored_file=stored)

        with override_settings(FILES_FS=self.files_fs):
            self.assertTrue(url.has_stored_copy(check_disk=False))
            self.assertFalse(url.has_stored_copy(check_disk=True))
            self.assertIsNotNone(url.get_local_file_path(must_exist=False))
            self.assertIsNone(url.get_local_file_path(must_exist=True))

    def test_url_fallback_to_legacy_fields(self) -> None:
        uploads_dir = Path(self.media_root) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        file_path = uploads_dir / "legacy_game.zip"
        file_path.write_bytes(b"legacy-content")

        url = URL.objects.create(
            original_url="https://example.com/legacy.zip",
            local_filename="legacy_game.zip",
            local_url="/f/uploads/legacy_game.zip",
            is_uploaded=True,
            creation_date=django_timezone.now(),
        )

        with override_settings(
            FILES_FS=self.files_fs,
            UPLOADS_FS=self.uploads_fs,
            BACKUPS_FS=self.backups_fs,
        ):
            # No fetch or stored file
            self.assertIsNone(url.get_latest_fetch())
            self.assertIsNone(url.get_stored_file())

            # Local URL falls back
            self.assertEqual(url.get_local_url(), "/f/uploads/legacy_game.zip")
            self.assertEqual(url.GetLocalUrl(), "/f/uploads/legacy_game.zip")

            # Stored copy check
            self.assertTrue(url.has_stored_copy(check_disk=False))
            self.assertTrue(url.has_stored_copy(check_disk=True))

            # Path check
            self.assertEqual(
                url.get_local_file_path(must_exist=False), file_path
            )
            self.assertEqual(
                url.get_local_file_path(must_exist=True), file_path
            )

            # Open local file
            with url.open_local_file("rb") as f:
                self.assertEqual(f.read(), b"legacy-content")

    def test_url_without_any_stored_file(self) -> None:
        url = URL.objects.create(
            original_url="https://example.com/external.zip",
            creation_date=django_timezone.now(),
        )

        with override_settings(
            FILES_FS=self.files_fs,
            UPLOADS_FS=self.uploads_fs,
            BACKUPS_FS=self.backups_fs,
        ):
            self.assertFalse(url.has_stored_copy(check_disk=False))
            self.assertFalse(url.has_stored_copy(check_disk=True))
            self.assertIsNone(url.get_local_file_path(must_exist=False))
            self.assertIsNone(url.get_local_file_path(must_exist=True))
            with self.assertRaises(FileNotFoundError):
                url.open_local_file("rb")

    def test_game_url_delegates(self) -> None:
        file_path = Path(self.media_root) / "g" / "10" / "game.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"game-data")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"game-data").hexdigest(),
            storage_path="g/10/game.zip",
            file_size=len(b"game-data"),
        )
        url = URL.objects.create(
            original_url="https://example.com/game.zip",
            creation_date=django_timezone.now(),
        )
        URLFetch.objects.create(url=url, stored_file=stored)

        game = Game.objects.create(
            title="Delegates Test Game",
            state=Game.State.PUBLISHED,
            creation_time=django_timezone.now(),
        )
        category = GameURLCategory.objects.create(
            title="Direct Download",
            symbolic_id="download_direct",
            allow_cloning=True,
        )
        game_url = GameURL.objects.create(
            game=game,
            url=url,
            category=category,
        )

        with override_settings(FILES_FS=self.files_fs):
            self.assertEqual(game_url.get_stored_file(), stored)
            self.assertEqual(game_url.get_local_url(), "/f/g/10/game.zip")
            self.assertTrue(game_url.has_stored_copy(check_disk=True))
            self.assertEqual(
                game_url.get_local_file_path(must_exist=True), file_path
            )
            with game_url.open_local_file("rb") as f:
                self.assertEqual(f.read(), b"game-data")


class MigratedReadersIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.media_root = self.temp_dir.name
        self.files_fs = FileSystemStorage(
            location=self.media_root, base_url="/f/"
        )

        self.game = Game.objects.create(
            title="Integration Test Game",
            state=Game.State.PUBLISHED,
            creation_time=django_timezone.now(),
        )
        self.category = GameURLCategory.objects.create(
            title="Direct Download",
            symbolic_id="download_direct",
            allow_cloning=True,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_generate_playable_with_stored_file(self) -> None:
        file_path = Path(self.media_root) / "g" / "1" / "adventure.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"PK\x03\x04mockzip")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"PK\x03\x04mockzip").hexdigest(),
            storage_path="g/1/adventure.zip",
            file_size=len(b"PK\x03\x04mockzip"),
        )
        url = URL.objects.create(
            original_url="https://example.com/adventure.zip",
            creation_date=django_timezone.now(),
        )
        URLFetch.objects.create(url=url, stored_file=stored)

        game_url = GameURL.objects.create(
            game=self.game,
            url=url,
            category=self.category,
        )

        playable = Playable.objects.create(
            game=self.game,
            game_url=game_url,
            template="dummy",
            template_version="1.0.0",
            config={},
        )

        dummy_bp = DummyBlueprint()
        playables_dir = Path(self.temp_dir.name) / "playables"

        with override_settings(
            FILES_FS=self.files_fs,
            PLAYABLE_DIR=str(playables_dir),
        ):
            with (
                patch(
                    "play.tasks.discover_blueprints",
                    return_value=[BlueprintInfo("dummy", dummy_bp)],
                ),
                patch("play.tasks.ensure_group_readable"),
            ):
                generate_playable(playable.pk)

        playable.refresh_from_db()
        self.assertEqual(playable.state, Playable.State.READY)
        self.assertTrue((playables_dir / str(playable.pk)).exists())

    def test_curation_get_playable_files_with_stored_file(self) -> None:
        file_path = Path(self.media_root) / "g" / "2" / "game.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"content")

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(b"content").hexdigest(),
            storage_path="g/2/game.zip",
            file_size=len(b"content"),
        )
        url = URL.objects.create(
            original_url="https://example.com/game.zip",
            creation_date=django_timezone.now(),
        )
        URLFetch.objects.create(url=url, stored_file=stored)

        GameURL.objects.create(
            game=self.game,
            url=url,
            category=self.category,
        )

        with override_settings(FILES_FS=self.files_fs):
            dummy_bp = DummyBlueprint()
            with patch(
                "curation.views.discover_blueprints",
                return_value=[BlueprintInfo("dummy", dummy_bp)],
            ):
                files = _build_playable_files(
                    self.game.pk, should_check_compatibility=True
                )

        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].has_local_copy)
        self.assertFalse(files[0].file_missing)
        self.assertTrue(files[0].compatibility)
