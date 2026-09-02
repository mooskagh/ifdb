import json
from urllib.parse import urljoin

import requests
from django.conf import settings

from games.game_details import GameDetailsBuilder
from games.gameinfo import GameInfo
from games.models import Game

LENGTH = 400
HARD_LENGTH = 1500


def PostNewGameToDiscord(game_id):
    if not settings.DISCORD_WEBHOOK:
        return

    game = Game.objects.get(id=game_id)
    content = GameDetailsBuilder(GameInfo.from_game(game)).GetContentDict()

    authors = None
    if content.authors:
        authors = ",  ".join(x.name for x in content.authors)
        if len(content.authors) == 1:
            authors = "Автор: " + authors
        else:
            authors = "Авторы: " + authors

    description = content.description or ""
    if len(description) > LENGTH:
        newline = description.find("\n", LENGTH)
        description = description[: newline if newline != -1 else LENGTH]
    if len(description) > HARD_LENGTH:
        description = description[:HARD_LENGTH] + "…"

    hook = {
        "username": "Бот игровых новинок",
        "content": "Новая игра!",
        "avatar_url": "https://db.crem.xyz/static/duck_full.png",
        "embeds": [
            {
                "title": content.title,
                "url": "https://db.crem.xyz/game/%d/" % game.id,
                "description": description,
            }
        ],
    }
    if authors:
        hook["embeds"][0]["footer"] = {
            "text": authors,
            "icon_url": "https://db.crem.xyz/static/default_author.jpg",
        }
    if content.media:
        for entry in content.media:
            if entry.img:
                hook["embeds"][0]["image"] = {
                    "url": urljoin("https://db.crem.xyz/", entry.img)
                }

    requests.post(
        settings.DISCORD_WEBHOOK,
        data=json.dumps(hook),
        headers={"Content-type": "application/json"},
    )
