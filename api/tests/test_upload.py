from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from api.models import APIToken
from core.models import User
from games.models import URL, Game, GameRevision, GameURL


class APIUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def setUp(self) -> None:
        self.client = Client()
        self.user = User.objects.create_user(
            username="uploader",
            email="uploader@example.com",
            password="secretpassword",
        )
        self.token = APIToken.objects.create(
            user=self.user,
            name="Upload Token",
            permissions=["*"],
        )
        self.headers = {"Authorization": f"Bearer {self.token.key}"}

    def test_standalone_file_upload(self) -> None:
        file = SimpleUploadedFile(
            "game_archive.zip",
            b"PK\x03\x04filecontent",
            content_type="application/zip",
        )
        response = self.client.post(
            reverse("api_file_upload"),
            data={"file": file},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("url_id", data)
        self.assertIn("url", data)
        self.assertEqual(data["filename"], "game_archive.zip")
        self.assertEqual(data["canonical_snippet"][0], "download_direct")
        self.assertEqual(data["canonical_snippet"][2], data["url_id"])

        url_obj = URL.objects.get(pk=data["url_id"])
        self.assertTrue(url_obj.is_uploaded)
        self.assertEqual(url_obj.creator, self.user)
        self.assertEqual(url_obj.original_filename, "game_archive.zip")

    def test_game_connected_file_upload(self) -> None:
        game = Game.objects.create(
            title="Upload Target Game",
            state=Game.State.DRAFT,
            added_by=self.user,
            creation_time=timezone.now(),
        )
        file = SimpleUploadedFile(
            "release.tar.gz",
            b"content123",
            content_type="application/gzip",
        )
        response = self.client.post(
            reverse("api_game_file_upload", kwargs={"game_id": game.id}),
            data={
                "file": file,
                "description": "Version 1.0",
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["game_id"], game.id)
        self.assertEqual(data["filename"], "release.tar.gz")
        self.assertEqual(data["description"], "Version 1.0")
        self.assertIn("urls:", data["canonical_text"])

        url_obj = URL.objects.get(pk=data["url_id"])
        self.assertTrue(url_obj.local_filename.startswith(f"games/{game.id}/"))

        game_url = GameURL.objects.get(game=game, url=url_obj)
        self.assertEqual(game_url.category.symbolic_id, "download_direct")
        self.assertEqual(game_url.description, "Version 1.0")

        latest_rev = (
            GameRevision.objects.filter(game=game).order_by("-id").first()
        )
        self.assertIsNotNone(latest_rev)
        self.assertEqual(latest_rev.origin, GameRevision.Origin.API)
        self.assertEqual(latest_rev.created_by, self.user)

    def test_upload_missing_file_returns_400(self) -> None:
        response = self.client.post(
            reverse("api_file_upload"),
            data={},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_invalid_game_id_returns_404(self) -> None:
        file = SimpleUploadedFile("test.txt", b"abc")
        response = self.client.post(
            reverse("api_game_file_upload", kwargs={"game_id": 999999}),
            data={"file": file},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 404)
