from datetime import datetime, timezone

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone as django_timezone

from games.models import URL, StoredFile, URLFetch


class StoredFileModelTests(TestCase):
    def test_create_and_public_url(self) -> None:
        file = StoredFile.objects.create(
            content_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            storage_path="g/123/game.zip",
            file_size=1024,
        )
        self.assertEqual(str(file), "g/123/game.zip")
        self.assertEqual(file.public_url, "/f/g/123/game.zip")
        self.assertIsNotNone(file.created_at)

    def test_content_hash_must_be_unique(self) -> None:
        hash_val = "1" * 64
        StoredFile.objects.create(
            content_hash=hash_val,
            storage_path="uploads/first.zip",
            file_size=100,
        )
        with self.assertRaises(IntegrityError):
            StoredFile.objects.create(
                content_hash=hash_val,
                storage_path="uploads/second.zip",
                file_size=100,
            )

    def test_storage_path_must_be_unique(self) -> None:
        StoredFile.objects.create(
            content_hash="2" * 64,
            storage_path="uploads/same_path.zip",
            file_size=100,
        )
        with self.assertRaises(IntegrityError):
            StoredFile.objects.create(
                content_hash="3" * 64,
                storage_path="uploads/same_path.zip",
                file_size=100,
            )


class URLFetchModelTests(TestCase):
    def setUp(self) -> None:
        self.url = URL.objects.create(
            original_url="https://example.com/game.zip",
            creation_date=django_timezone.now(),
        )
        self.file_a = StoredFile.objects.create(
            content_hash="a" * 64,
            storage_path="backups/file_a.zip",
            file_size=500,
        )
        self.file_b = StoredFile.objects.create(
            content_hash="b" * 64,
            storage_path="backups/file_b.zip",
            file_size=600,
        )

    def test_fetch_creation_and_relations(self) -> None:
        t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

        fetch = URLFetch.objects.create(
            url=self.url,
            stored_file=self.file_a,
            original_filename="game.zip",
            content_type="application/zip",
            first_fetch=t1,
            last_fetch=t2,
        )
        self.assertEqual(fetch.url, self.url)
        self.assertEqual(fetch.stored_file, self.file_a)
        self.assertIn("file_a.zip", str(fetch))
        self.assertEqual(list(self.url.fetches.all()), [fetch])
        self.assertEqual(list(self.file_a.fetches.all()), [fetch])

    def test_url_fetch_not_unique_for_same_url_and_file(self) -> None:
        # History: fetch 1 -> file A, fetch 2 -> file B, fetch 3 -> file A
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        t3 = datetime(2026, 1, 3, tzinfo=timezone.utc)

        fetch1 = URLFetch.objects.create(
            url=self.url,
            stored_file=self.file_a,
            first_fetch=t1,
            last_fetch=t1,
        )
        fetch2 = URLFetch.objects.create(
            url=self.url,
            stored_file=self.file_b,
            first_fetch=t2,
            last_fetch=t2,
        )
        fetch3 = URLFetch.objects.create(
            url=self.url,
            stored_file=self.file_a,
            first_fetch=t3,
            last_fetch=t3,
        )

        self.assertEqual(self.url.fetches.count(), 3)
        self.assertEqual(
            list(self.url.fetches.order_by("first_fetch")),
            [fetch1, fetch2, fetch3],
        )

    def test_stored_file_deletion_is_protected(self) -> None:
        URLFetch.objects.create(
            url=self.url,
            stored_file=self.file_a,
        )
        with self.assertRaises(ProtectedError):
            self.file_a.delete()

    def test_url_deletion_cascades_fetches(self) -> None:
        URLFetch.objects.create(
            url=self.url,
            stored_file=self.file_a,
        )
        self.assertEqual(URLFetch.objects.count(), 1)
        self.url.delete()
        self.assertEqual(URLFetch.objects.count(), 0)
        # StoredFile remains untouched
        self.assertTrue(StoredFile.objects.filter(pk=self.file_a.pk).exists())

    def test_bad_fetch_flag_and_successful_fetch(self) -> None:
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)

        fetch_good = URLFetch.objects.create(
            url=self.url,
            stored_file=self.file_a,
            first_fetch=t1,
            last_fetch=t1,
        )
        self.assertFalse(fetch_good.bad_fetch)
        self.assertNotIn("[BAD]", str(fetch_good))

        fetch_bad = URLFetch.objects.create(
            url=self.url,
            stored_file=self.file_b,
            first_fetch=t2,
            last_fetch=t2,
            bad_fetch=True,
        )
        self.assertTrue(fetch_bad.bad_fetch)
        self.assertIn("[BAD]", str(fetch_bad))

        # Unfiltered latest fetch returns the true latest (even if bad)
        self.assertEqual(self.url.get_latest_fetch(), fetch_bad)
        self.assertEqual(
            self.url.get_latest_fetch(successful_only=False), fetch_bad
        )
        self.assertEqual(self.url.latest_fetch, fetch_bad)

        # Successful-only fetch returns fetch_good
        self.assertEqual(
            self.url.get_latest_fetch(successful_only=True), fetch_good
        )
        self.assertEqual(self.url.get_latest_successful_fetch(), fetch_good)

        # Prefetched cache behavior
        url_with_prefetch = (
            URL.objects
            .filter(pk=self.url.pk)
            .prefetch_related("fetches__stored_file")
            .first()
        )
        assert url_with_prefetch is not None
        self.assertEqual(url_with_prefetch.get_latest_fetch(), fetch_bad)
        self.assertEqual(
            url_with_prefetch.get_latest_fetch(successful_only=True),
            fetch_good,
        )
        self.assertEqual(
            url_with_prefetch.get_latest_successful_fetch(), fetch_good
        )


class URLHealthFieldsTests(TestCase):
    def test_health_fields_default_to_none(self) -> None:
        url = URL.objects.create(
            original_url="https://example.com/test.zip",
            creation_date=django_timezone.now(),
        )
        self.assertIsNone(url.last_attempt)
        self.assertIsNone(url.failing_since)
        self.assertIsNone(url.last_error)

    def test_update_health_fields(self) -> None:
        attempt_time = django_timezone.now()
        failing_time = django_timezone.now()
        error_msg = "HTTP 404: Not Found"

        url = URL.objects.create(
            original_url="https://example.com/test.zip",
            creation_date=django_timezone.now(),
            last_attempt=attempt_time,
            failing_since=failing_time,
            last_error=error_msg,
        )
        url.refresh_from_db()
        self.assertEqual(url.last_attempt, attempt_time)
        self.assertEqual(url.failing_since, failing_time)
        self.assertEqual(url.last_error, error_msg)


class StorageAdminTests(TestCase):
    def test_admin_pages_load(self) -> None:
        from django.urls import reverse

        from core.models import User

        admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )
        self.client.force_login(admin_user)

        file = StoredFile.objects.create(
            content_hash="c" * 64,
            storage_path="backups/file_c.zip",
            file_size=1234,
        )
        url = URL.objects.create(
            original_url="https://example.com/test_admin.zip",
            creation_date=django_timezone.now(),
        )
        URLFetch.objects.create(
            url=url,
            stored_file=file,
        )

        resp = self.client.get(reverse("admin:games_storedfile_changelist"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(reverse("admin:games_urlfetch_changelist"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(reverse("admin:games_url_changelist"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(
            reverse("admin:games_url_change", args=[url.pk])
        )
        self.assertEqual(resp.status_code, 200)
