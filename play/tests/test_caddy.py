from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils.timezone import now

from games.models import Game
from play.caddy import (
    caddy_route_id_for_playable,
    caddy_route_payload,
    configure_caddy_playable,
    delete_caddy_playable,
)
from play.models import Playable


class TestCaddyIntegration(TestCase):
    def setUp(self) -> None:
        self.game = Game.objects.create(
            title="Caddy Game", creation_time=now()
        )
        self.playable = Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="1.0",
            slug="cool-game",
        )

    def test_caddy_route_helpers(self) -> None:
        self.assertEqual(
            caddy_route_id_for_playable(self.playable.pk),
            f"playable_{self.playable.pk}",
        )
        payload = caddy_route_payload(self.playable)
        self.assertEqual(payload["@id"], f"playable_{self.playable.pk}")
        self.assertEqual(
            payload["match"],
            [{"host": [f"cool-game.{settings.PLAYABLE_BASE_DOMAIN}"]}],
        )
        self.assertEqual(payload["handle"][0]["handler"], "file_server")
        self.assertIn(str(self.playable.pk), payload["handle"][0]["root"])

    @override_settings(CADDY_ADMIN_URL="http://localhost:2019")
    @patch("requests.post")
    @patch("requests.get")
    def test_configure_caddy_creates_new_route(
        self, mock_get: MagicMock, mock_post: MagicMock
    ) -> None:
        mock_get_resp = MagicMock(status_code=404)
        mock_get.return_value = mock_get_resp

        mock_post_resp = MagicMock(status_code=200)
        mock_post.return_value = mock_post_resp

        result = configure_caddy_playable(self.playable)
        self.assertTrue(result)

        mock_get.assert_called_once_with(
            f"http://localhost:2019/id/playable_{self.playable.pk}",
            timeout=5,
        )
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(
            args[0],
            "http://localhost:2019/config/apps/http/servers/srv0/routes/",
        )
        self.assertEqual(kwargs["json"]["@id"], f"playable_{self.playable.pk}")

    @override_settings(CADDY_ADMIN_URL="http://localhost:2019")
    @patch("requests.put")
    @patch("requests.get")
    def test_configure_caddy_updates_existing_route(
        self, mock_get: MagicMock, mock_put: MagicMock
    ) -> None:
        mock_get_resp = MagicMock(status_code=200)
        mock_get.return_value = mock_get_resp

        mock_put_resp = MagicMock(status_code=200)
        mock_put.return_value = mock_put_resp

        result = configure_caddy_playable(self.playable)
        self.assertTrue(result)

        mock_put.assert_called_once_with(
            f"http://localhost:2019/id/playable_{self.playable.pk}",
            json=caddy_route_payload(self.playable),
            timeout=5,
        )

    @override_settings(CADDY_ADMIN_URL=None)
    def test_configure_caddy_skipped_when_no_url(self) -> None:
        result = configure_caddy_playable(self.playable)
        self.assertFalse(result)

    @override_settings(CADDY_ADMIN_URL="http://localhost:2019")
    @patch("requests.delete")
    def test_delete_caddy_playable(self, mock_delete: MagicMock) -> None:
        mock_delete_resp = MagicMock(status_code=200)
        mock_delete.return_value = mock_delete_resp

        result = delete_caddy_playable(self.playable.pk)
        self.assertTrue(result)
        mock_delete.assert_called_once_with(
            f"http://localhost:2019/id/playable_{self.playable.pk}",
            timeout=5,
        )

    @override_settings(CADDY_ADMIN_URL=None)
    def test_delete_caddy_skipped_when_no_url(self) -> None:
        result = delete_caddy_playable(self.playable.pk)
        self.assertFalse(result)
