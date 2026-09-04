from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils.timezone import now

from contest.models import Competition, GameList, GameListEntry
from contest.views import CompetitionGameFetcher
from contest.voting import RenderVotingImpl, RenderVotingImplV2
from core.models import User
from core.snippets import LastComments, LastUrlCat
from games.gameinfo import GameInfo
from games.models import (
    URL,
    Game,
    GameAuthor,
    GameAuthorRole,
    GameComment,
    GameURL,
    GameURLCategory,
    GameVote,
    Personality,
    PersonalityAlias,
)
from games.search import MakeSearch
from games.tools import ComputeHonors


class GameLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def _game(
        self,
        title: str,
        *,
        state: Game.State = Game.State.PUBLISHED,
        redirect_to: Game | None = None,
    ) -> Game:
        return Game.objects.create(
            title=title,
            creation_time=now(),
            state=state,
            redirect_to=redirect_to,
            view_perm="@all",
            vote_perm="@all",
            comment_perm="@all",
        )

    def test_published_queryset_keeps_only_public_rows(self) -> None:
        published = self._game("Published")
        draft = self._game("Draft", state=Game.State.DRAFT)
        redirect = self._game(
            "Redirect", state=Game.State.REDIRECT, redirect_to=published
        )

        self.assertEqual(
            set(Game.objects.published().values_list("id", flat=True)),
            {published.id},
        )
        self.assertEqual(Game.objects.count(), 3)
        self.assertNotIn(draft, Game.objects.published())
        self.assertNotIn(redirect, Game.objects.published())

    def test_gameinfo_creation_publishes_and_update_preserves_state(
        self,
    ) -> None:
        created, _ = GameInfo(name="Created").save()
        self.assertEqual(created.state, Game.State.PUBLISHED)

        draft = self._game("Draft", state=Game.State.DRAFT)
        GameInfo(name="Updated").save(draft)
        draft.refresh_from_db()

        self.assertEqual(draft.title, "Updated")
        self.assertEqual(draft.state, Game.State.DRAFT)

    def test_game_state_constraints_validate_local_invariants(self) -> None:
        target = self._game("Target")

        with self.assertRaises(ValidationError):
            Game(
                title="Missing target",
                creation_time=now(),
                state=Game.State.REDIRECT,
            ).full_clean()
        with self.assertRaises(ValidationError):
            Game(
                title="Unexpected target",
                creation_time=now(),
                state=Game.State.PUBLISHED,
                redirect_to=target,
            ).full_clean()
        with self.assertRaises(ValidationError):
            Game(
                pk=target.pk,
                title="Self target",
                creation_time=now(),
                state=Game.State.REDIRECT,
                redirect_to=target,
            ).full_clean()

    def test_published_detail_renders_normally(self) -> None:
        game = self._game("Published")

        response = self.client.get(reverse("show_game", args=[game.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Published")

    def test_draft_detail_is_not_public(self) -> None:
        game = self._game("Draft", state=Game.State.DRAFT)

        response = self.client.get(reverse("show_game", args=[game.id]))

        self.assertEqual(response.status_code, 404)

    def test_redirects_follow_multiple_hops_and_preserve_query_string(
        self,
    ) -> None:
        target = self._game("Target")
        middle = self._game(
            "Middle", state=Game.State.REDIRECT, redirect_to=target
        )
        source = self._game(
            "Source", state=Game.State.REDIRECT, redirect_to=middle
        )

        response = self.client.get(
            reverse("show_game", args=[source.id])
            + "?utm_source=test&value=a%2Bb"
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            reverse("show_game", args=[target.id])
            + "?utm_source=test&value=a%2Bb",
        )

    def test_invalid_redirect_chain_is_not_public(self) -> None:
        target = self._game("Target")
        left = self._game(
            "Left", state=Game.State.REDIRECT, redirect_to=target
        )
        right = self._game(
            "Right", state=Game.State.REDIRECT, redirect_to=target
        )
        Game.objects.filter(pk=left.pk).update(redirect_to=right)
        Game.objects.filter(pk=right.pk).update(redirect_to=left)

        response = self.client.get(reverse("show_game", args=[left.id]))
        missing = self.client.get(reverse("show_game", args=[999999]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(missing.status_code, 404)

    def test_redirect_to_hidden_terminal_is_not_public(self) -> None:
        draft = self._game("Draft", state=Game.State.DRAFT)
        source = self._game(
            "Source", state=Game.State.REDIRECT, redirect_to=draft
        )

        response = self.client.get(reverse("show_game", args=[source.id]))

        self.assertEqual(response.status_code, 404)

    def test_public_search_excludes_hidden_games(self) -> None:
        visible = self._game("Visible")
        self._game("Draft", state=Game.State.DRAFT)
        self._game("Redirect", state=Game.State.REDIRECT, redirect_to=visible)

        def allow(_: str) -> bool:
            return True

        games = MakeSearch(allow).Search(start=0, limit=10)

        self.assertEqual([game.id for game in games], [visible.id])

    def test_public_json_rejects_hidden_game(self) -> None:
        draft = self._game("Draft", state=Game.State.DRAFT)

        response = self.client.get(
            reverse("json_gameinfo"), {"game_id": draft.id}
        )

        self.assertEqual(response.status_code, 404)

    def test_vote_and_comment_redirect_ids_write_to_terminal(self) -> None:
        user = User.objects.create_user(username="voter", password="password")
        target = self._game("Target")
        source = self._game(
            "Source", state=Game.State.REDIRECT, redirect_to=target
        )
        self.client.force_login(user)

        vote_response = self.client.post(
            reverse("vote_game"), {"game_id": source.id, "score": 5}
        )
        comment_response = self.client.post(
            reverse("comment_game"),
            {"game_id": source.id, "text": "A comment"},
        )

        self.assertEqual(vote_response.status_code, 302)
        self.assertEqual(
            vote_response["Location"], reverse("show_game", args=[target.id])
        )
        self.assertEqual(comment_response.status_code, 302)
        self.assertEqual(
            comment_response["Location"],
            reverse("show_game", args=[target.id]),
        )
        self.assertTrue(GameVote.objects.filter(game=target).exists())
        self.assertEqual(
            GameComment.objects.get().game_id,
            target.id,
        )

    def test_public_snippets_exclude_hidden_games(self) -> None:
        visible = self._game("Visible")
        draft = self._game("Draft", state=Game.State.DRAFT)
        redirect = self._game(
            "Redirect", state=Game.State.REDIRECT, redirect_to=visible
        )
        for game in [visible, draft, redirect]:
            GameComment.objects.create(
                game=game,
                creation_time=now(),
                text=game.title,
            )

        category = GameURLCategory.objects.get(symbolic_id="game_page")
        for game in [visible, draft, redirect]:
            url = URL.objects.create(
                original_url=f"https://example.com/{game.id}",
                creation_date=now(),
            )
            GameURL.objects.create(game=game, category=category, url=url)

        comments = LastComments(limit=10)
        urls = LastUrlCat(
            None,
            "game_page",
            max_secs=10**9,
            min_count=0,
            max_count=10,
        )

        self.assertEqual(
            [comment.game_id for comment in comments], [visible.id]
        )
        self.assertEqual([url["id"] for url in urls], [visible.id])

    def test_public_contest_listing_and_voting_exclude_hidden_games(
        self,
    ) -> None:
        user = User.objects.create_user(username="voter", password="password")
        visible = self._game("Visible")
        draft = self._game("Draft", state=Game.State.DRAFT)
        redirect = self._game(
            "Redirect", state=Game.State.REDIRECT, redirect_to=visible
        )
        competition = Competition.objects.create(
            title="Competition",
            slug="competition",
            end_date=now().date(),
            options="{}",
            published=True,
        )
        gamelist = GameList.objects.create(
            competition=competition, title="Nomination"
        )
        GameListEntry.objects.create(gamelist=gamelist, game=visible, rank=1)
        GameListEntry.objects.create(gamelist=gamelist, game=draft, rank=2)
        GameListEntry.objects.create(gamelist=gamelist, game=redirect, rank=3)
        GameListEntry.objects.create(gamelist=gamelist, game=None, rank=4)

        raw = CompetitionGameFetcher(competition).GetCompetitionGamesRaw()
        entries = [entry for group in raw for entry in group["ranked"]]
        request = RequestFactory().get("/")
        request.user = user
        fields = [{"name": "score", "type": "IntegerField"}]
        voting = {
            "open": True,
            "sections": [
                {
                    "nomination": gamelist.id,
                    "fields": fields,
                }
            ],
        }
        old_result = RenderVotingImpl(
            request, competition, voting, None, preview=False
        )
        new_voting = {
            "open": True,
            "sections": {
                "main": {"nomination": gamelist.id, "fields": ["score"]}
            },
            "fields": fields,
        }
        new_result = RenderVotingImplV2(
            request, competition, new_voting, "main", preview=False
        )

        self.assertEqual(
            {entry.game_id for entry in entries if entry.game_id is not None},
            {visible.id},
        )
        self.assertTrue(any(entry.game_id is None for entry in entries))
        self.assertEqual(
            [
                form.gameentry.game_id
                for form in old_result["sections"][0].forms
            ],
            [visible.id],
        )
        self.assertEqual(
            [form.gameentry.game_id for form in new_result["formset"].forms],
            [visible.id],
        )

    def test_honors_ignore_non_public_games(self) -> None:
        personality = Personality.objects.create(name="Author")
        alias = PersonalityAlias.objects.create(
            name="Author", personality=personality
        )
        role = GameAuthorRole.objects.get(symbolic_id="author")
        user = User.objects.create_user(
            username="author-voter", password="password"
        )
        hidden = self._game("Hidden", state=Game.State.DRAFT)
        GameAuthor.objects.create(game=hidden, author=alias, role=role)
        GameVote.objects.create(
            game=hidden,
            user=user,
            creation_time=now(),
            star_rating=5,
        )

        self.assertEqual(ComputeHonors(personality.id), 0.0)

        visible = self._game("Visible")
        GameAuthor.objects.create(game=visible, author=alias, role=role)
        GameVote.objects.create(
            game=visible,
            user=user,
            creation_time=now(),
            star_rating=5,
        )

        self.assertGreater(ComputeHonors(personality.id), 0.0)

    def test_comment_vote_on_hidden_game_is_not_public(self) -> None:
        user = User.objects.create_user(username="voter", password="password")
        draft = self._game("Draft", state=Game.State.DRAFT)
        comment = GameComment.objects.create(
            game=draft,
            user=user,
            creation_time=now(),
            text="Hidden",
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("json_commentvote"), {"comment": comment.id}
        )

        self.assertEqual(response.status_code, 404)
