from copy import deepcopy
from io import StringIO
from typing import Any
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.db import connection
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.timezone import now

from games.game_details import GameDetailsBuilder, GameMedia, GamePerson
from games.gameinfo import Attribution, GameInfo, GameUrl, Person, Tag, parse
from games.models import (
    URL,
    Game,
    GameAuthor,
    GameDescriptionAttribution,
    GameTag,
    GameURL,
    Personality,
    PersonalityAlias,
)
from ifdb.permissioner import Permissioner


class GameDetailsContentTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def _request(self) -> Any:
        request = RequestFactory().get("/game/draft/")
        request.user = AnonymousUser()
        setattr(request, "perm", Permissioner(request))
        return request

    def _counts(self) -> dict[str, int]:
        models = (
            Game,
            GameAuthor,
            GameDescriptionAttribution,
            GameTag,
            GameURL,
            Personality,
            PersonalityAlias,
            URL,
        )
        return {model.__name__: model.objects.count() for model in models}

    def test_parsed_idless_content_renders_without_persistence(self) -> None:
        canonical = """---
- name: "Draft game"
- release_date: "2024-01-02"
- personalities:
  - author:
    - "Draft author"
  - artist:
    - "Draft participant"
- tags:
  - ["tag", "Draft tag"]
- urls:
  - ["game_page", "Draft page", "https://draft.example/game"]
  - ["poster", "Draft poster", "https://draft.example/poster.png"]
- attributions:
  - "draft.example"
---
A **markdown** description.
"""
        before_rows = self._counts()
        info = parse(canonical)
        after_parse_rows = self._counts()
        original = deepcopy(info)

        with CaptureQueriesContext(connection) as queries:
            content = GameDetailsBuilder(info).GetContentDict()
            html = render_to_string(
                "games/game.html", vars(content), request=self._request()
            )

        self.assertEqual(before_rows, after_parse_rows)
        self.assertEqual(info, original)
        self.assertEqual(self._counts(), before_rows)
        self.assertFalse(
            any(
                query["sql"]
                .lstrip()
                .upper()
                .startswith(("INSERT", "UPDATE", "DELETE"))
                for query in queries.captured_queries
            )
        )
        self.assertEqual(content.title, "Draft game")
        self.assertEqual(content.description, info.description)
        self.assertIn("<strong>markdown</strong>", content.markdown)
        self.assertEqual(
            content.authors,
            [GamePerson("Draft author", None)],
        )
        self.assertEqual(
            content.participants[0].items,
            [GamePerson("Draft participant", None)],
        )
        self.assertEqual(content.metadata.tags[0].name, "draft tag")
        self.assertIsNone(content.metadata.tags[0].search_query)
        self.assertEqual(
            content.links[0].items[0].remote_url,
            "https://draft.example/game",
        )
        self.assertEqual(
            content.media,
            [
                GameMedia(
                    "img",
                    "Draft poster",
                    img="https://draft.example/poster.png",
                )
            ],
        )
        self.assertEqual(content.description_attributions, ["draft.example"])
        self.assertIn("Draft game", html)
        self.assertIn("Draft author", html)
        self.assertIn("Draft participant", html)
        self.assertIn("draft tag", html)
        self.assertIn("<strong>markdown</strong>", html)
        self.assertNotIn('class="author-link"', html)
        self.assertNotIn("game--voting-panel", html)
        self.assertNotIn("Комментарии", html)
        self.assertNotIn("Добавлено", html)

    def test_persisted_ids_enrich_without_replacing_canonical_values(
        self,
    ) -> None:
        personality = Personality.objects.create(name="Linked personality")
        alias = PersonalityAlias.objects.create(
            name="Linked alias", personality=personality
        )
        fantasy = GameTag.objects.get(symbolic_id="g_fantasy")
        page = URL.objects.create(
            original_url="https://stored.example/page",
            is_broken=True,
            creation_date=now(),
        )
        poster = URL.objects.create(
            original_url="https://stored.example/poster.png",
            local_url="/media/poster.png",
            creation_date=now(),
        )
        attr = GameDescriptionAttribution.objects.create(name="stored.example")
        info = GameInfo(
            name="Canonical title",
            description="Canonical description",
            personalities={
                "author": [Person(alias.id, "")],
                "artist": [Person(None, "Draft artist")],
            },
            tags=[
                Tag("genre", fantasy.symbolic_id, fantasy.id, None),
                Tag("tag", None, None, "Draft tag"),
            ],
            urls=[
                GameUrl(
                    "game_page",
                    page.id,
                    "Canonical page",
                    "https://canonical.example/page",
                ),
                GameUrl(
                    "poster",
                    poster.id,
                    "Canonical poster",
                    "https://canonical.example/poster.png",
                ),
            ],
            attributions=[
                Attribution(attr.id, ""),
                Attribution(None, "draft.example"),
            ],
        )
        original = deepcopy(info)

        content = GameDetailsBuilder(info).GetContentDict()

        self.assertEqual(
            content.authors,
            [GamePerson("Linked alias", personality.id)],
        )
        self.assertEqual(
            content.participants[0].items,
            [GamePerson("Draft artist", None)],
        )
        genre = content.metadata.genres[0]
        self.assertEqual(genre.name, fantasy.name)
        self.assertIsNotNone(genre.search_query)
        self.assertEqual(content.metadata.tags[0].name, "Draft tag")
        self.assertIsNone(content.metadata.tags[0].search_query)
        page_link = content.links[0].items[0]
        self.assertEqual(page_link.description, "Canonical page")
        self.assertEqual(
            page_link.remote_url, "https://canonical.example/page"
        )
        self.assertTrue(page_link.is_broken)
        self.assertEqual(
            content.media[0],
            GameMedia("img", "Canonical poster", img="/media/poster.png"),
        )
        self.assertEqual(
            content.description_attributions,
            ["draft.example", "stored.example"],
        )
        self.assertEqual(info, original)

    @mock.patch("games.views.GameInfo.from_game")
    def test_public_page_uses_gameinfo_for_content(
        self, from_game: Any
    ) -> None:
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Persisted title",
            description="Persisted body",
            creation_time=now(),
        )
        from_game.return_value = GameInfo(
            name="Canonical title", description="Canonical body"
        )

        response = self.client.get(reverse("show_game", args=[game.id]))

        self.assertEqual(response.status_code, 200)
        from_game.assert_called_once_with(game)
        self.assertContains(response, "Canonical title")
        self.assertContains(response, "Canonical body")
        self.assertNotContains(response, "Persisted title")
        self.assertEqual(response.context["game"].id, game.id)
        self.assertTrue(response.context["added_date"])
