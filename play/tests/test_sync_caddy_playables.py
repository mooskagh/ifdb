from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils.timezone import now

from games.models import Game
from play.caddy import caddy_route_payload
from play.models import Playable


@override_settings(
    CADDY_ADMIN_URL="http://localhost:2019", CADDY_SERVER_NAME="srv0"
)
class TestSyncCaddyPlayables(TestCase):
    def setUp(self) -> None:
        game = Game.objects.create(title="2048", creation_time=now())
        self.playable = Playable.objects.create(
            game=game,
            template="static_files",
            template_version="1",
            slug="2048",
            state=Playable.State.READY,
        )
        Playable.objects.create(
            game=game,
            template="static_files",
            template_version="1",
            slug="pending-game",
        )
        self.routes_url = (
            "http://localhost:2019/config/apps/http/servers/srv0/routes/"
        )

    @patch("play.management.commands.sync_caddy_playables.requests.patch")
    @patch("play.management.commands.sync_caddy_playables.requests.get")
    def test_removes_stale_and_duplicate_routes(
        self, mock_get: MagicMock, mock_patch: MagicMock
    ) -> None:
        before = {"@id": "main_site", "handle": [{"handler": "reverse_proxy"}]}
        after = {
            "handle": [{"handler": "static_response", "status_code": 404}]
        }
        current = caddy_route_payload(self.playable)
        stale = {
            **current,
            "@id": "playable_999999",
            "handle": [{"handler": "file_server", "root": "/missing"}],
        }
        old_slug = {**current, "match": [{"host": ["old.play.crem.xyz"]}]}
        mock_get.return_value.headers = {"Etag": '"routes hash"'}
        mock_get.return_value.json.return_value = [
            before,
            stale,
            old_slug,
            after,
            current,
            current,
        ]

        call_command("sync_caddy_playables", stdout=StringIO())

        mock_patch.assert_called_once_with(
            self.routes_url,
            json=[before, current, after],
            headers={"If-Match": '"routes hash"'},
            timeout=5,
        )

    @patch("play.management.commands.sync_caddy_playables.requests.patch")
    @patch("play.management.commands.sync_caddy_playables.requests.get")
    def test_already_synced_routes_are_not_changed(
        self, mock_get: MagicMock, mock_patch: MagicMock
    ) -> None:
        mock_get.return_value.headers = {"Etag": '"routes hash"'}
        mock_get.return_value.json.return_value = [
            caddy_route_payload(self.playable)
        ]

        call_command("sync_caddy_playables", stdout=StringIO())

        mock_patch.assert_not_called()
