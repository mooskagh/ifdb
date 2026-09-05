from django.contrib.auth.models import AnonymousUser
from django.test import Client, TestCase
from django.utils import timezone

from contest.permissions import (
    can_admin_competition,
    can_view_competition,
    can_view_competition_document,
)
from core.models import User

from .models import Competition, CompetitionDocument


class ShowCompetitionViewTest(TestCase):
    """Test the show_competition view that uses markdown rendering."""

    def setUp(self):
        self.client = Client()

    def test_show_competition_with_markdown_rendering(self):
        """Test that show_competition view doesn't crash on markdown."""
        # Create a minimal competition and document
        competition = Competition.objects.create(
            title="Test Competition",
            slug="test-comp",
            end_date=timezone.now().date(),
            published=True,
        )

        document = CompetitionDocument.objects.create(
            title="Test Document",
            slug="test-doc",
            competition=competition,
            text="# Test Markdown\n\nSome test content with **bold** text.",
        )

        # This should trigger the markdown rendering error
        response = self.client.get(f"/jam/{competition.slug}/{document.slug}")

        # The view should not crash (status should be 200, not 500)
        self.assertEqual(response.status_code, 200)


class CompetitionPermissionsTest(TestCase):
    def setUp(self) -> None:
        self.anon = AnonymousUser()
        self.owner = User.objects.create_user(
            username="compowner",
            email="owner@example.com",
            password="secretpassword",
        )
        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="secretpassword",
        )
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secretpassword",
        )
        self.owned_comp = Competition.objects.create(
            title="Owned Comp",
            slug="owned-comp",
            owner=self.owner,
            end_date=timezone.now().date(),
            published=True,
        )
        self.unowned_comp = Competition.objects.create(
            title="Unowned Comp",
            slug="unowned-comp",
            owner=None,
            end_date=timezone.now().date(),
            published=True,
        )
        self.doc = CompetitionDocument.objects.create(
            title="Doc",
            slug="doc",
            competition=self.owned_comp,
            text="text",
        )

    def test_can_admin_competition(self) -> None:
        self.assertFalse(can_admin_competition(self.anon, self.owned_comp))
        self.assertFalse(
            can_admin_competition(self.other_user, self.owned_comp)
        )
        self.assertTrue(can_admin_competition(self.owner, self.owned_comp))
        self.assertTrue(can_admin_competition(self.admin, self.owned_comp))

        # Unowned competition
        self.assertFalse(can_admin_competition(self.anon, self.unowned_comp))
        self.assertFalse(
            can_admin_competition(self.other_user, self.unowned_comp)
        )
        self.assertTrue(can_admin_competition(self.admin, self.unowned_comp))

    def test_can_view_competition_and_document(self) -> None:
        self.assertTrue(can_view_competition(self.anon, self.owned_comp))
        self.assertTrue(can_view_competition(self.other_user, self.owned_comp))
        self.assertTrue(can_view_competition_document(self.anon, self.doc))
        self.assertTrue(
            can_view_competition_document(self.other_user, self.doc)
        )
