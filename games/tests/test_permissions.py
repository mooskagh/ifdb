from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.utils import timezone

from core.models import User
from games.models import Game, Personality
from games.permissions import (
    can_add_game,
    can_comment_game,
    can_delete_author,
    can_delete_game,
    can_edit_author,
    can_edit_game,
    can_view_author,
    can_view_game,
    can_vote_game,
)


class GamePermissionsTest(TestCase):
    def setUp(self) -> None:
        self.anon = AnonymousUser()
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="secretpassword",
        )
        self.staff = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="secretpassword",
            is_staff=True,
        )
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secretpassword",
        )
        self.published_game = Game.objects.create(
            title="Published Game",
            state=Game.State.PUBLISHED,
            creation_time=timezone.now(),
        )
        self.draft_game = Game.objects.create(
            title="Draft Game",
            state=Game.State.DRAFT,
            creation_time=timezone.now(),
        )
        self.author = Personality.objects.create(
            name="Test Author",
        )

    def test_can_view_game(self) -> None:
        self.assertTrue(can_view_game(self.anon, self.published_game))
        self.assertTrue(can_view_game(self.user, self.published_game))
        self.assertTrue(can_view_game(self.admin, self.published_game))

        self.assertFalse(can_view_game(self.anon, self.draft_game))
        self.assertFalse(can_view_game(self.user, self.draft_game))
        self.assertTrue(can_view_game(self.admin, self.draft_game))

    def test_can_edit_game(self) -> None:
        self.assertFalse(can_edit_game(self.anon, self.published_game))
        self.assertFalse(can_edit_game(self.user, self.published_game))
        self.assertTrue(can_edit_game(self.staff, self.published_game))
        self.assertTrue(can_edit_game(self.admin, self.published_game))

    def test_can_delete_game(self) -> None:
        self.assertFalse(can_delete_game(self.anon, self.published_game))
        self.assertFalse(can_delete_game(self.user, self.published_game))
        self.assertFalse(can_delete_game(self.staff, self.published_game))
        self.assertTrue(can_delete_game(self.admin, self.published_game))

    def test_author_permissions(self) -> None:
        self.assertTrue(can_view_author(self.anon, self.author))
        self.assertTrue(can_view_author(self.user, self.author))

        self.assertFalse(can_edit_author(self.anon, self.author))
        self.assertFalse(can_edit_author(self.user, self.author))
        self.assertTrue(can_edit_author(self.staff, self.author))
        self.assertTrue(can_edit_author(self.admin, self.author))

        self.assertFalse(can_delete_author(self.anon, self.author))
        self.assertFalse(can_delete_author(self.user, self.author))
        self.assertFalse(can_delete_author(self.staff, self.author))
        self.assertTrue(can_delete_author(self.admin, self.author))

    def test_can_comment_and_vote_and_add(self) -> None:
        self.assertFalse(can_comment_game(self.anon, self.published_game))
        self.assertTrue(can_comment_game(self.user, self.published_game))

        self.assertFalse(can_vote_game(self.anon, self.published_game))
        self.assertTrue(can_vote_game(self.user, self.published_game))

        self.assertFalse(can_add_game(self.anon))
        self.assertTrue(can_add_game(self.user))

        inactive_user = User.objects.create_user(
            username="inactive",
            email="inactive@example.com",
            password="secretpassword",
            is_active=False,
        )
        self.assertFalse(can_comment_game(inactive_user, self.published_game))
        self.assertFalse(can_vote_game(inactive_user, self.published_game))
        self.assertFalse(can_add_game(inactive_user))
