import time

import jwt
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from jwt import PyJWKSet

from api.models import APIToken
from core.models import User


class SSOTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.user = User.objects.create_user(
            username="ssouser",
            email="sso@example.com",
            password="testpassword",
        )
        self.token = APIToken.objects.create(
            user=self.user,
            name="SSO Test Token",
            permissions=["*"],
        )

    def test_ticket_unauthenticated_returns_401(self) -> None:
        response = self.client.get(
            reverse("api_sso_ticket"), {"client_id": "foo"}
        )
        self.assertEqual(response.status_code, 401)

    def test_ticket_missing_client_id_returns_400(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(reverse("api_sso_ticket"))
        self.assertEqual(response.status_code, 400)

    def test_ticket_and_jwks_verification(self) -> None:
        self.client.force_login(self.user)
        now_before = int(time.time())

        ticket_resp = self.client.get(
            reverse("api_sso_ticket"), {"client_id": "foo"}
        )
        self.assertEqual(ticket_resp.status_code, 200)
        ticket = ticket_resp.json()["ticket"]

        jwks_resp = self.client.get(reverse("api_sso_jwks"))
        self.assertEqual(jwks_resp.status_code, 200)
        jwks = PyJWKSet.from_dict(jwks_resp.json())

        header = jwt.get_unverified_header(ticket)
        self.assertEqual(header["alg"], "EdDSA")
        key = next(k for k in jwks.keys if k.key_id == header["kid"])

        claims = jwt.decode(
            ticket,
            key.key,
            algorithms=["EdDSA"],
            audience="foo",
            issuer="https://db.crem.xyz",
        )
        self.assertEqual(claims["iss"], "https://db.crem.xyz")
        self.assertEqual(claims["sub"], str(self.user.id))
        self.assertEqual(claims["aud"], "foo")
        self.assertGreaterEqual(claims["iat"], now_before - 1)
        self.assertEqual(claims["exp"], claims["iat"] + 60)

    def test_ticket_via_bearer_token(self) -> None:
        response = self.client.get(
            reverse("api_sso_ticket"),
            {"client_id": "foo"},
            HTTP_AUTHORIZATION=f"Bearer {self.token.key}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("ticket", response.json())

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_ticket_cors_allowed_origin_unauthenticated(self) -> None:
        response = self.client.get(
            reverse("api_sso_ticket"),
            {"client_id": "danetka"},
            HTTP_ORIGIN="https://danetka.play.crem.xyz",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://danetka.play.crem.xyz",
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Credentials"),
            "true",
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Methods"),
            "GET",
        )

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_ticket_cors_allowed_origin_authenticated(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("api_sso_ticket"),
            {"client_id": "danetka"},
            HTTP_ORIGIN="https://danetka.play.crem.xyz",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://danetka.play.crem.xyz",
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Credentials"),
            "true",
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Methods"),
            "GET",
        )

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_ticket_cors_disallowed_origin(self) -> None:
        response = self.client.get(
            reverse("api_sso_ticket"),
            {"client_id": "danetka"},
            HTTP_ORIGIN="https://evil.com",
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_ticket_cors_no_origin(self) -> None:
        response = self.client.get(
            reverse("api_sso_ticket"),
            {"client_id": "danetka"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_jwks_does_not_set_cors(self) -> None:
        response = self.client.get(
            reverse("api_sso_jwks"),
            HTTP_ORIGIN="https://danetka.play.crem.xyz",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
