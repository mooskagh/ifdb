import json
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore

from games.game_details import GameDetailsBuilder
from ifdb.permissioner import Permissioner

LENGTH = 400
HARD_LENGTH = 1500

USER = "бездушный робот"


class FakeRequest:
    def __init__(self, username):
        self.user = get_user_model().objects.get(username=username)
        self.session = SessionStore()
        self.is_fake = True
        self.META = {}
        self.perm = Permissioner(self)


def PostNewGameToDiscord(game_id):
    if not settings.DISCORD_WEBHOOK:
        return

    request = FakeRequest(USER)
    gameinfo = GameDetailsBuilder(game_id, request).GetGameDict()

    authors = None
    if "authors" in gameinfo:
        authors = ",  ".join([x.name for x in gameinfo["authors"]])
        if len(gameinfo["authors"]) == 1:
            authors = "Автор: " + authors
        else:
            authors = "Авторы: " + authors

    description = gameinfo["game"].description
    if len(description) > LENGTH:
        description = description[: description.find("\n", LENGTH)]
    if len(description) > HARD_LENGTH:
        description = description[:HARD_LENGTH] + "…"

    url = settings.DISCORD_WEBHOOK
    hook = {}
    hook["username"] = "Бот игровых новинок"
    hook["content"] = "Новая игра!"
    hook["avatar_url"] = "https://db.crem.xyz/static/duck_full.png"
    hook["embeds"] = [
        {
            "title": gameinfo["game"].title,
            "url": "https://db.crem.xyz/game/%d/" % game_id,
            "description": description,
        }
    ]
    if authors:
        hook["embeds"][0]["footer"] = {
            "text": authors,
            "icon_url": "https://db.crem.xyz/static/default_author.jpg",
        }
    if "media" in gameinfo:
        for entry in gameinfo["media"]:
            if "img" in entry:
                hook["embeds"][0]["image"] = {
                    "url": urljoin("https://db.crem.xyz/", entry["img"])
                }

    requests.post(
        url,
        data=json.dumps(hook),
        headers={"Content-type": "application/json"},
    )
