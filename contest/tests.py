from django.test import Client, TestCase
from django.utils import timezone

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
