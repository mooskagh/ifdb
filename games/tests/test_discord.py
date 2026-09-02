import json
from io import StringIO
from typing import Any
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils.timezone import now

from games.gameinfo import GameInfo, GameUrl, Person
from games.importer.discord import PostNewGameToDiscord
from games.models import Game


class DiscordRenderingTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    @override_settings(DISCORD_WEBHOOK="https://discord.example/hook")
    @patch("games.importer.discord.requests.post")
    @patch("games.importer.discord.GameInfo.from_game")
    def test_discord_uses_content_info_and_persisted_identity(
        self, from_game: MagicMock, post: MagicMock
    ) -> None:
        game = Game.objects.create(
            title="Persisted title",
            description="Persisted description",
            creation_time=now(),
        )
        from_game.return_value = GameInfo(
            name="Canonical title",
            description="Canonical description",
            personalities={"author": [Person(None, "Canonical author")]},
            urls=[
                GameUrl(
                    "poster",
                    None,
                    "Canonical poster",
                    "https://cdn.example/poster.png",
                )
            ],
        )

        PostNewGameToDiscord(game.id)

        from_game.assert_called_once_with(game)
        post.assert_called_once()
        payload: dict[str, Any] = json.loads(post.call_args.kwargs["data"])
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "Canonical title")
        self.assertEqual(embed["description"], "Canonical description")
        self.assertEqual(embed["url"], f"https://db.crem.xyz/game/{game.id}/")
        self.assertEqual(embed["footer"]["text"], "Автор: Canonical author")
        self.assertEqual(
            embed["image"]["url"], "https://cdn.example/poster.png"
        )

    @override_settings(DISCORD_WEBHOOK="https://discord.example/hook")
    @patch("games.importer.discord.requests.post")
    @patch("games.importer.discord.GameInfo.from_game")
    def test_discord_handles_absent_description(
        self, from_game: MagicMock, post: MagicMock
    ) -> None:
        game = Game.objects.create(
            title="Persisted title", creation_time=now()
        )
        from_game.return_value = GameInfo(name="Canonical title")

        PostNewGameToDiscord(game.id)

        payload: dict[str, Any] = json.loads(post.call_args.kwargs["data"])
        self.assertEqual(payload["embeds"][0]["description"], "")
