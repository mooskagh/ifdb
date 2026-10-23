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
        self.assertIsNotNone(payload)
        assert payload is not None
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
    @patch("requests.patch")
    @patch("requests.get")
    def test_configure_caddy_updates_existing_route(
        self, mock_get: MagicMock, mock_patch: MagicMock
    ) -> None:
        mock_get_resp = MagicMock(status_code=200)
        mock_get.return_value = mock_get_resp

        mock_patch_resp = MagicMock(status_code=200)
        mock_patch.return_value = mock_patch_resp

        result = configure_caddy_playable(self.playable)
        self.assertTrue(result)

        mock_patch.assert_called_once_with(
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

    def test_external_caddy_routes(self) -> None:
        p_proxy = Playable.objects.create(
            game=self.game,
            template="external",
            template_version="1.0",
            slug="ext-proxy",
            config={"upstream": "127.0.0.1:9000"},
        )
        proxy_payload = caddy_route_payload(p_proxy)
        self.assertIsNotNone(proxy_payload)
        assert proxy_payload is not None
        self.assertEqual(
            proxy_payload["handle"][0]["handler"], "reverse_proxy"
        )
        self.assertEqual(
            proxy_payload["handle"][0]["upstreams"],
            [{"dial": "127.0.0.1:9000"}],
        )

        p_redir = Playable.objects.create(
            game=self.game,
            template="external",
            template_version="1.0",
            slug="ext-redir",
            config={"redirect": "https://external.org/game"},
        )
        redir_payload = caddy_route_payload(p_redir)
        self.assertIsNotNone(redir_payload)
        assert redir_payload is not None
        self.assertEqual(
            redir_payload["handle"][0]["handler"], "static_response"
        )
        self.assertEqual(
            redir_payload["handle"][0]["headers"]["Location"],
            ["https://external.org/game"],
        )

        p_noop = Playable.objects.create(
            game=self.game,
            template="external",
            template_version="1.0",
            slug="ext-noop",
            config={},
        )
        self.assertIsNone(caddy_route_payload(p_noop))

    @override_settings(CADDY_ADMIN_URL="http://localhost:2019")
    @patch("play.caddy.delete_caddy_playable")
    def test_configure_caddy_external_noop_cleans_route_and_returns_true(
        self, mock_delete: MagicMock
    ) -> None:
        mock_delete.return_value = True
        p_noop = Playable.objects.create(
            game=self.game,
            template="external",
            template_version="1.0",
            slug="ext-noop",
            config={},
        )
        result = configure_caddy_playable(p_noop)
        self.assertTrue(result)
        mock_delete.assert_called_once_with(p_noop.pk)
