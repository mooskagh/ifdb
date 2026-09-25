import datetime

from django.contrib.auth.models import AnonymousUser
from django.test import Client, TestCase
from django.utils import timezone

from contest.models import (
    Competition,
    CompetitionDocument,
    CompetitionSchedule,
)
from contest.permissions import (
    can_admin_competition,
    can_view_competition,
    can_view_competition_document,
)
from core.models import User


class ShowCompetitionViewTest(TestCase):
    """Test the show_competition view that uses markdown rendering."""

    def setUp(self):
        self.client = Client()

    def test_show_competition_with_markdown_rendering(self):
        """Test that show_competition view doesn't crash on markdown."""
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

        response = self.client.get(f"/jam/{competition.slug}/{document.slug}")
        self.assertEqual(response.status_code, 200)

    def test_show_competition_schedule(self):
        """Test that contest schedule is displayed on competition page."""
        competition = Competition.objects.create(
            title="Jam 2025",
            slug="jam-2025",
            end_date=timezone.now().date(),
            published=True,
        )
        CompetitionDocument.objects.create(
            title="Main Doc",
            slug="",
            competition=competition,
            text="Hello contest",
        )
        now = timezone.now()
        past_event = CompetitionSchedule.objects.create(
            competition=competition,
            title="Начало конкурса",
            when=now - datetime.timedelta(days=10),
            show=True,
            done=False,
        )
        future_event = CompetitionSchedule.objects.create(
            competition=competition,
            title="Конец приёма игр",
            when=now + datetime.timedelta(days=10),
            show=True,
            done=False,
        )
        hidden_event = CompetitionSchedule.objects.create(
            competition=competition,
            title="Секретный этап",
            when=now + datetime.timedelta(days=20),
            show=False,
            done=False,
        )

        response = self.client.get(f"/jam/{competition.slug}/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn("card--orange", content)
        self.assertIn("Расписание", content)
        self.assertIn(past_event.title, content)
        self.assertIn(future_event.title, content)
        self.assertNotIn(hidden_event.title, content)

        # Ensure schedule appears in the sidebar
        sidebar_idx = content.find("game--content-sidebar")
        schedule_idx = content.find("card--orange")
        self.assertNotEqual(sidebar_idx, -1)
        self.assertGreater(schedule_idx, sidebar_idx)

    def test_show_competition_document_navigation(self):
        """Test document navigation renders as links with current bold."""
        competition = Competition.objects.create(
            title="Jam 2025",
            slug="jam-2025",
            end_date=timezone.now().date(),
            published=True,
        )
        CompetitionDocument.objects.create(
            title="О фестивале",
            slug="",
            competition=competition,
            text="Описание",
            order=0,
        )
        CompetitionDocument.objects.create(
            title="Участники",
            slug="games",
            competition=competition,
            text="Список игр",
            order=1,
        )

        response = self.client.get(f"/jam/{competition.slug}/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn("contest--docs-menu", content)
        self.assertIn(
            '<span class="contest--docs-item current">О фестивале</span>',
            content,
        )
        self.assertIn(
            '<a href="/jam/jam-2025/games" '
            'class="contest--docs-item">Участники</a>',
            content,
        )
        self.assertNotIn("game--tag-genre", content)
        self.assertNotIn("button-salad", content)


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
