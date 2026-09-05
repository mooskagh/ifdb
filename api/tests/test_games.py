import json
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from api.models import APIToken
from core.models import User
from games.models import Game, GameRevision


class APIGameTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def setUp(self) -> None:
        self.client = Client()
        self.user = User.objects.create_user(
            username="gamer",
            email="gamer@example.com",
            password="secretpassword",
        )
        self.token = APIToken.objects.create(
            user=self.user,
            name="Game Token",
            permissions=["*"],
        )
        self.headers = {"Authorization": f"Bearer {self.token.key}"}

    def test_create_game_defaults_to_draft(self) -> None:
        canonical_text = (
            "---\n- name: Adventure Quest\n---\nExciting quest game."
        )
        response = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({"canonical_text": canonical_text}),
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["title"], "Adventure Quest")
        self.assertEqual(data["state"], "draft")
        self.assertIn("Adventure Quest", data["canonical_text"])

        game = Game.objects.get(pk=data["id"])
        self.assertEqual(game.state, Game.State.DRAFT)
        self.assertEqual(game.added_by, self.user)

        revision = GameRevision.objects.get(pk=data["revision_id"])
        self.assertEqual(revision.origin, GameRevision.Origin.API)
        self.assertEqual(revision.created_by, self.user)
        self.assertEqual(revision.status, GameRevision.Status.PROPOSED)

    def test_create_game_with_raw_text_payload(self) -> None:
        canonical_text = (
            "---\n- name: Text Game\n---\nRaw markdown description."
        )
        response = self.client.post(
            reverse("api_game_create"),
            data=canonical_text,
            content_type="text/plain",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["title"], "Text Game")
        self.assertEqual(data["state"], "draft")

    def test_create_published_game_requires_publish_scope(self) -> None:
        write_only_token = APIToken.objects.create(
            user=self.user,
            name="Write Only",
            permissions=["games:write"],
        )
        canonical_text = "---\n- name: Published Attempt\n---\nDescription."
        response = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": canonical_text,
                "state": "published",
            }),
            content_type="application/json",
            headers={"Authorization": f"Bearer {write_only_token.key}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_create_published_game_succeeds(self) -> None:
        canonical_text = "---\n- name: Direct Published\n---\nDescription."
        response = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": canonical_text,
                "state": "published",
            }),
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["state"], "published")

        game = Game.objects.get(pk=data["id"])
        self.assertEqual(game.state, Game.State.PUBLISHED)
        self.assertIsNotNone(game.published_revision)
        self.assertEqual(
            game.published_revision.origin, GameRevision.Origin.API
        )
        self.assertEqual(game.published_revision.published_by, self.user)

    def test_get_game(self) -> None:
        canonical_text = "---\n- name: Inspect Game\n---\nBody text."
        create_res = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({"canonical_text": canonical_text}),
            content_type="application/json",
            headers=self.headers,
        )
        game_id = create_res.json()["id"]

        get_res = self.client.get(
            reverse("api_game_detail", kwargs={"game_id": game_id}),
            headers=self.headers,
        )
        self.assertEqual(get_res.status_code, 200)
        data = get_res.json()
        self.assertEqual(data["id"], game_id)
        self.assertEqual(data["title"], "Inspect Game")
        self.assertIn("Inspect Game", data["canonical_text"])

    def test_get_game_not_found(self) -> None:
        res = self.client.get(
            reverse("api_game_detail", kwargs={"game_id": 999999}),
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 404)

    def test_update_game_via_canonical_text(self) -> None:
        create_res = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": "---\n- name: Initial\n---\nDesc 1"
            }),
            content_type="application/json",
            headers=self.headers,
        )
        game_id = create_res.json()["id"]

        update_text = "---\n- name: Updated Title\n---\nDesc 2"
        update_res = self.client.put(
            reverse("api_game_detail", kwargs={"game_id": game_id}),
            data=json.dumps({"canonical_text": update_text}),
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(update_res.status_code, 200)
        data = update_res.json()
        self.assertEqual(data["title"], "Updated Title")
        self.assertIn("Updated Title", data["canonical_text"])

        game = Game.objects.get(pk=game_id)
        self.assertEqual(game.title, "Updated Title")
        self.assertEqual(game.gamerevision_set.count(), 2)
        latest_rev = game.gamerevision_set.order_by("-id").first()
        self.assertIsNotNone(latest_rev)
        self.assertEqual(latest_rev.origin, GameRevision.Origin.API)

    def test_publish_and_unpublish_game(self) -> None:
        create_res = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": "---\n- name: Toggle Game\n---\nDesc"
            }),
            content_type="application/json",
            headers=self.headers,
        )
        game_id = create_res.json()["id"]
        game = Game.objects.get(pk=game_id)
        self.assertEqual(game.state, Game.State.DRAFT)

        # Publish
        pub_res = self.client.post(
            reverse("api_game_publish", kwargs={"game_id": game_id}),
            headers=self.headers,
        )
        self.assertEqual(pub_res.status_code, 200)
        self.assertEqual(pub_res.json()["state"], "published")

        game.refresh_from_db()
        self.assertEqual(game.state, Game.State.PUBLISHED)
        self.assertIsNotNone(game.published_revision)

        # Publish again (idempotent)
        pub_res2 = self.client.post(
            reverse("api_game_publish", kwargs={"game_id": game_id}),
            headers=self.headers,
        )
        self.assertEqual(pub_res2.status_code, 200)
        self.assertEqual(pub_res2.json()["state"], "published")

        # Unpublish
        unpub_res = self.client.post(
            reverse("api_game_unpublish", kwargs={"game_id": game_id}),
            headers=self.headers,
        )
        self.assertEqual(unpub_res.status_code, 200)
        self.assertEqual(unpub_res.json()["state"], "draft")

        game.refresh_from_db()
        self.assertEqual(game.state, Game.State.DRAFT)

        # Unpublish again (idempotent)
        unpub_res2 = self.client.post(
            reverse("api_game_unpublish", kwargs={"game_id": game_id}),
            headers=self.headers,
        )
        self.assertEqual(unpub_res2.status_code, 200)
        self.assertEqual(unpub_res2.json()["state"], "draft")
