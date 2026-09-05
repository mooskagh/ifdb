import json

from django.test import Client, TestCase
from django.urls import reverse

from api.models import APIToken
from core.models import User
from games.models import Game


class APITokenAuthTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.user = User.objects.create_user(
            username="apitestuser",
            email="api@example.com",
            password="secretpassword",
        )
        self.token = APIToken.objects.create(
            user=self.user,
            name="Test Token",
            permissions=["*"],
        )

    def test_missing_auth_header_returns_401(self) -> None:
        response = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": "---\n- name: Game\n---\nDesc"
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "Unauthorized")

    def test_invalid_token_returns_401(self) -> None:
        response = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": "---\n- name: Game\n---\nDesc"
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer invalid_token_123",
        )
        self.assertEqual(response.status_code, 401)

    def test_inactive_token_returns_401(self) -> None:
        self.token.is_active = False
        self.token.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": "---\n- name: Game\n---\nDesc"
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token.key}",
        )
        self.assertEqual(response.status_code, 401)

    def test_token_header_format_works(self) -> None:
        response = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": "---\n- name: Game\n---\nDesc"
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )
        self.assertEqual(response.status_code, 201)

    def test_token_updates_last_used_at(self) -> None:
        self.assertIsNone(self.token.last_used_at)
        self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": "---\n- name: Game\n---\nDesc"
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token.key}",
        )
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_missing_permission_scope_returns_403(self) -> None:
        scoped_token = APIToken.objects.create(
            user=self.user,
            name="Read Only Token",
            permissions=["games:read"],
        )
        response = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": "---\n- name: Game\n---\nDesc"
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {scoped_token.key}",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Forbidden")

    def test_matching_permission_scope_succeeds(self) -> None:
        scoped_token = APIToken.objects.create(
            user=self.user,
            name="Write Token",
            permissions=["games:write"],
        )
        response = self.client.post(
            reverse("api_game_create"),
            data=json.dumps({
                "canonical_text": "---\n- name: Scoped Game\n---\nDesc"
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {scoped_token.key}",
        )
        self.assertEqual(response.status_code, 201)
        game = Game.objects.get(id=response.json()["id"])
        self.assertEqual(game.added_by, self.user)
