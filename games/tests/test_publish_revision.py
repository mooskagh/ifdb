from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils.timezone import now

from core.models import User
from curation.merge import merge_game_into_history
from curation.models import GameCuration
from games.gameinfo import Attribution, GameInfo, GameUrl, Person, Tag
from games.models import (
    Game,
    GameRevision,
)
from moder.actions.games_action import GameCloneAction


class PublishRevisionTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="tester", email="tester@example.com", password="pw"
        )
        self.staff_user = User.objects.create_user(
            username="gardener",
            email="gardener@example.com",
            password="pw",
            is_staff=True,
            is_superuser=True,
        )

    def test_publish_revision_syncs_draft_game_fields_and_projections(
        self,
    ) -> None:
        game = Game.objects.create(
            title="Old Draft Title",
            state=Game.State.DRAFT,
            creation_time=now(),
        )
        info = GameInfo(
            name="Published Game Title",
            date="2023-05-12",
            description="Detailed game description body.",
            personalities={"author": [Person(None, "Author Name")]},
            tags=[Tag("genre", "g_fantasy", None, None)],
            urls=[
                GameUrl(
                    "download_direct",
                    None,
                    "Game download file",
                    "https://example.com/game.zip",
                )
            ],
            attributions=[Attribution(None, "Source Catalog")],
        )
        rev = GameRevision(
            game=game,
            created_at=now(),
            origin=GameRevision.Origin.MANUAL_EDIT,
            canonical_text=info.to_canonical(),
        )

        game.publish_revision(rev, actor=self.user)

        game.refresh_from_db()
        rev.refresh_from_db()

        self.assertEqual(game.state, Game.State.PUBLISHED)
        self.assertEqual(game.published_revision, rev)
        self.assertEqual(game.title, "Published Game Title")
        self.assertEqual(game.description, "Detailed game description body.")
        self.assertEqual(game.release_date, date(2023, 5, 12))

        self.assertEqual(rev.status, GameRevision.Status.ACCEPTED)
        self.assertEqual(rev.published_by, self.user)
        self.assertIsNotNone(rev.published_at)

        # Projections in sync
        self.assertTrue(game.tags.filter(symbolic_id="g_fantasy").exists())
        self.assertTrue(
            game.gameauthor_set.filter(author__name="Author Name").exists()
        )
        self.assertTrue(
            game.gameurl_set.filter(
                url__original_url="https://example.com/game.zip"
            ).exists()
        )
        self.assertTrue(
            game.description_attributions.filter(
                name="Source Catalog"
            ).exists()
        )

        # show_game renders cleanly
        response = self.client.get(reverse("show_game", args=[game.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Published Game Title")
        self.assertContains(response, "Detailed game description body.")

    def test_publish_revision_updates_existing_game(self) -> None:
        game = Game.objects.create(
            title="Initial Title",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        first_rev = GameRevision(
            game=game,
            created_at=now(),
            origin=GameRevision.Origin.MANUAL_EDIT,
            canonical_text=GameInfo(name="Initial Title").to_canonical(),
        )
        game.publish_revision(first_rev, actor=self.user)

        # Publish a second revision
        second_rev = GameRevision(
            game=game,
            created_at=now(),
            origin=GameRevision.Origin.MANUAL_EDIT,
            canonical_text=GameInfo(
                name="Updated Title", description="New body"
            ).to_canonical(),
        )
        game.publish_revision(second_rev, actor=self.user)

        game.refresh_from_db()
        second_rev.refresh_from_db()

        self.assertEqual(game.published_revision, second_rev)
        self.assertEqual(game.title, "Updated Title")
        self.assertEqual(game.description, "New body")
        self.assertEqual(
            second_rev.previous_canonical_text, first_rev.canonical_text
        )

    def test_game_clone_action_publishes_revision(self) -> None:
        game = Game.objects.create(
            title="Original Game",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        rev = GameRevision(
            game=game,
            created_at=now(),
            origin=GameRevision.Origin.MANUAL_EDIT,
            canonical_text=GameInfo(
                name="Original Game", description="Original Desc"
            ).to_canonical(),
        )
        game.publish_revision(rev, actor=self.user)

        factory = RequestFactory()
        request = factory.post(f"/moder/game/{game.id}/clone/")
        request.user = self.staff_user

        action = GameCloneAction(request, game)
        action.DoAction("Клонировать", {}, execute=True)

        cloned = Game.objects.exclude(id=game.id).latest("id")
        self.assertEqual(cloned.state, Game.State.PUBLISHED)
        self.assertIsNotNone(cloned.published_revision)
        assert cloned.published_revision is not None
        self.assertEqual(
            cloned.published_revision.origin, GameRevision.Origin.CLONE
        )
        self.assertEqual(cloned.title, "Original Game")

        # Visiting show_game on the cloned game succeeds with HTTP 200
        response = self.client.get(reverse("show_game", args=[cloned.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Original Game")
        self.assertContains(response, "Original Desc")

    def test_merge_game_into_history_publishes_merged_revision(self) -> None:
        target_game = Game.objects.create(
            title="Target Game",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        target_rev = GameRevision(
            game=target_game,
            created_at=now(),
            origin=GameRevision.Origin.MANUAL_EDIT,
            canonical_text=GameInfo(
                name="Target Game", description="Target description."
            ).to_canonical(),
        )
        target_game.publish_revision(target_rev, actor=self.user)
        target_history = GameCuration.objects.create(game=target_game)

        source_game = Game.objects.create(
            title="Source Game",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        source_rev = GameRevision(
            game=source_game,
            created_at=now(),
            origin=GameRevision.Origin.MANUAL_EDIT,
            canonical_text=GameInfo(
                name="Source Game", description="Source description."
            ).to_canonical(),
        )
        source_game.publish_revision(source_rev, actor=self.user)

        merge_game_into_history(
            target_history=target_history,
            source_game=source_game,
            actor=self.user,
            remap_contests=False,
        )

        target_game.refresh_from_db()
        self.assertNotEqual(target_game.published_revision, target_rev)
        assert target_game.published_revision is not None
        self.assertEqual(
            target_game.published_revision.origin, GameRevision.Origin.MERGE
        )
        self.assertIn(
            "Target description.",
            target_game.published_revision.canonical_text,
        )
        self.assertIn(
            "Source description.",
            target_game.published_revision.canonical_text,
        )

        response = self.client.get(reverse("show_game", args=[target_game.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Target description.")
        self.assertContains(response, "Source description.")
