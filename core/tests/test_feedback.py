import json

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import User


@override_settings(
    PLAYABLE_BASE_DOMAIN="play.crem.xyz",
    CURATION_NOTIFICATION_EMAIL="curation@example.com",
    DEFAULT_FROM_EMAIL="noreply@crem.xyz",
)
class FeedbackViewTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="secretpassword",
        )
        self.feedback_url = reverse("feedback")

    def test_options_cors_preflight(self) -> None:
        res = self.client.options(
            self.feedback_url,
            HTTP_ORIGIN="https://mygame.play.crem.xyz",
        )
        self.assertEqual(res.status_code, 204)
        self.assertEqual(
            res.headers.get("Access-Control-Allow-Origin"),
            "https://mygame.play.crem.xyz",
        )
        self.assertEqual(
            res.headers.get("Access-Control-Allow-Credentials"), "true"
        )

    def test_get_unauthenticated(self) -> None:
        res = self.client.get(
            self.feedback_url,
            HTTP_ORIGIN="https://mygame.play.crem.xyz",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["authenticated"])
        self.assertIn("accounts/login/", data["login_url"])

    def test_get_authenticated(self) -> None:
        self.client.force_login(self.user)
        res = self.client.get(self.feedback_url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["username"], "testuser")
        self.assertEqual(data["user"]["email"], "testuser@example.com")

    def test_forbidden_origin(self) -> None:
        res = self.client.get(
            self.feedback_url,
            HTTP_ORIGIN="https://malicious-site.com",
        )
        self.assertEqual(res.status_code, 403)

    def test_post_unauthenticated(self) -> None:
        res = self.client.post(
            self.feedback_url,
            json.dumps({"text": "Something is broken"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(len(mail.outbox), 0)

    def test_post_empty_text(self) -> None:
        self.client.force_login(self.user)
        res = self.client.post(
            self.feedback_url,
            json.dumps({"text": "   "}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_post_success(self) -> None:
        self.client.force_login(self.user)
        payload = {
            "text": "The parser hangs on command 'look'.",
            "url": "https://cool-game.play.crem.xyz/",
            "player_name": "INSTEAD",
            "player_url": "https://instead3.hugeping.ru/",
            "game_name": "Cool Game",
            "game_url": "https://db.crem.xyz/game/42/",
        }
        res = self.client.post(
            self.feedback_url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_ORIGIN="https://cool-game.play.crem.xyz",
            HTTP_USER_AGENT="Mozilla/5.0 TestBrowser",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok"})
        self.assertEqual(
            res.headers.get("Access-Control-Allow-Origin"),
            "https://cool-game.play.crem.xyz",
        )

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.from_email, "noreply@crem.xyz")
        self.assertEqual(sent.to, ["testuser@example.com"])
        self.assertEqual(sent.bcc, ["curation@example.com"])
        self.assertEqual(sent.reply_to, ["testuser@example.com"])
        self.assertEqual(
            sent.subject,
            "Сообщение об ошибке на сайте https://cool-game.play.crem.xyz/",
        )
        self.assertIn("The parser hangs on command 'look'.", sent.body)
        self.assertIn(
            "Пользователь: testuser (testuser@example.com)", sent.body
        )
        self.assertIn("Плеер: https://instead3.hugeping.ru/", sent.body)
        self.assertNotIn("INSTEAD", sent.body)
        self.assertIn(
            "Игра: Cool Game (https://db.crem.xyz/game/42/)", sent.body
        )
        player_idx = sent.body.find("Плеер:")
        game_idx = sent.body.find("Игра:")
        self.assertTrue(0 <= player_idx < game_idx)
        self.assertIn("Mozilla/5.0 TestBrowser", sent.body)

    def test_post_prevents_crlf_injection_in_subject(self) -> None:
        self.client.force_login(self.user)
        payload = {
            "text": "Some bug report",
            "url": "https://example.com/\r\nBcc: evil@example.com",
        }
        res = self.client.post(
            self.feedback_url,
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertNotIn("\r", sent.subject)
        self.assertNotIn("\n", sent.subject)

    @override_settings(
        CURATION_NOTIFICATION_EMAIL=None,
        ADMINS=[("Admin", "admin@example.com")],
    )
    def test_post_bcc_fallback_to_admins(self) -> None:
        self.client.force_login(self.user)
        payload = {"text": "Bug report fallback"}
        res = self.client.post(
            self.feedback_url,
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.bcc, ["admin@example.com"])
