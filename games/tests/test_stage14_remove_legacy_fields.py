import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.utils.timezone import now

from contest.models import Competition, CompetitionURL, CompetitionURLCategory
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


class Stage14RemoveLegacyFieldsTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.media_root = self.temp_dir.name
        self.files_fs = FileSystemStorage(
            location=self.media_root, base_url="/f/"
        )

        self.game = Game.objects.create(
            title="Stage 14 Test Game",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        self.cat_download = GameURLCategory.objects.create(
            title="Direct Download",
            symbolic_id="download_direct",
            allow_cloning=True,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_legacy_fields_removed_from_url_model(self) -> None:
        removed_fields = [
            "local_url",
            "local_filename",
            "original_filename",
            "content_type",
            "file_size",
            "is_broken",
        ]
        url_field_names = {f.name for f in URL._meta.get_fields()}
        for field in removed_fields:
            self.assertNotIn(
                field,
                url_field_names,
                f"Field '{field}' should have been removed from URL model",
            )
            with self.assertRaises(TypeError):
                URL(**{field: "test"})

    def test_retained_fields_on_url_model(self) -> None:
        url_field_names = {f.name for f in URL._meta.get_fields()}
        self.assertIn("is_uploaded", url_field_names)
        self.assertIn("creation_date", url_field_names)
        self.assertIn("original_url", url_field_names)
        self.assertIn("failing_since", url_field_names)
        self.assertIn("last_error", url_field_names)
        self.assertIn("last_attempt", url_field_names)

    def test_legacy_methods_removed_from_url(self) -> None:
        self.assertFalse(hasattr(URL, "resolve_local_file"))
        self.assertFalse(hasattr(URL, "GetFs"))

    def test_is_broken_property_removed_from_all_url_models(self) -> None:
        url = URL.objects.create(
            original_url="https://example.com/test.zip",
            creation_date=now(),
        )
        gu = GameURL.objects.create(
            game=self.game,
            url=url,
            category=self.cat_download,
        )
        pers = Personality.objects.create(name="Author")
        pcat = PersonalityURLCategory.objects.create(title="Site")
        purl = PersonalityUrl.objects.create(
            personality=pers,
            url=url,
            category=pcat,
        )
        comp = Competition.objects.create(
            title="Comp",
            slug="comp",
            end_date=now().date(),
            published=True,
        )
        ccat = CompetitionURLCategory.objects.create(title="Link")
        curl = CompetitionURL.objects.create(
            competition=comp,
            url=url,
            category=ccat,
        )

        for obj in [url, gu, purl, curl]:
            self.assertFalse(
                hasattr(obj, "is_broken"),
                f"{type(obj).__name__} should not have 'is_broken' attribute",
            )
            self.assertTrue(
                hasattr(obj, "is_link_broken"),
                f"{type(obj).__name__} must have 'is_link_broken' method",
            )
            self.assertFalse(obj.is_link_broken())

    def test_is_link_broken_evaluates_correctly(self) -> None:
        url_failing = URL.objects.create(
            original_url="https://example.com/broken.zip",
            creation_date=now(),
            failing_since=now(),
            last_error="503 Service Unavailable",
        )
        gu_failing = GameURL.objects.create(
            game=self.game,
            url=url_failing,
            category=self.cat_download,
        )
        self.assertTrue(url_failing.is_link_broken())
        self.assertTrue(gu_failing.is_link_broken())

    def test_file_accessors_without_stored_file_return_none(self) -> None:
        url = URL.objects.create(
            original_url="https://example.com/plain.zip",
            creation_date=now(),
        )
        with override_settings(FILES_FS=self.files_fs):
            self.assertIsNone(url.get_stored_file())
            self.assertIsNone(url.get_local_url())
            self.assertIsNone(url.get_original_filename())
            self.assertIsNone(url.get_content_type())
            self.assertIsNone(url.get_file_size())
            self.assertFalse(url.has_stored_copy())
            self.assertIsNone(url.get_local_file_path())
            with self.assertRaises(FileNotFoundError):
                url.open_local_file()

    def test_file_accessors_with_stored_file(self) -> None:
        content = b"stage-14-content"
        file_path = Path(self.media_root) / "g" / "99" / "file.zip"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

        stored = StoredFile.objects.create(
            content_hash=hashlib.sha256(content).hexdigest(),
            storage_path="g/99/file.zip",
            file_size=len(content),
        )
        url = URL.objects.create(
            original_url="https://example.com/file.zip",
            creation_date=now(),
        )
        URLFetch.objects.create(
            url=url,
            stored_file=stored,
            original_filename="file.zip",
            content_type="application/zip",
        )

        with override_settings(FILES_FS=self.files_fs):
            self.assertEqual(url.get_stored_file(), stored)
            self.assertEqual(url.get_local_url(), "/f/g/99/file.zip")
            self.assertEqual(url.get_original_filename(), "file.zip")
            self.assertEqual(url.get_content_type(), "application/zip")
            self.assertEqual(url.get_file_size(), len(content))
            self.assertTrue(url.has_stored_copy(check_disk=True))
            self.assertEqual(
                url.get_local_file_path(must_exist=True), file_path
            )
            with url.open_local_file("rb") as f:
                self.assertEqual(f.read(), content)
