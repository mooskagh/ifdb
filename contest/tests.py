from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from .models import Competition, CompetitionDocument
from .views import _seconds_until_midnight, get_competitions_data


class CacheUtilsTest(TestCase):
    def test_seconds_until_midnight(self):
        """Test that _seconds_until_midnight calculates correctly."""
        # Mock timezone.now to return a known time
        mock_time = timezone.now().replace(
            hour=14, minute=30, second=0, microsecond=0
        )

        with patch("contest.views.timezone.now", return_value=mock_time):
            seconds = _seconds_until_midnight()

            # Should be approximately 9.5 hours (34200 seconds) until midnight
            expected = 9.5 * 60 * 60  # 9.5 hours in seconds
            self.assertAlmostEqual(
                seconds, expected, delta=60
            )  # Allow 1 minute variance

    def test_get_competitions_data_caching(self):
        """Test competitions data is properly cached including games."""
        # Clear cache first
        cache.delete("contest:competitions_list_data")

        # Mock the database queries to return empty results
        with (
            patch("contest.views.Competition.objects") as mock_comp,
            patch(
                "contest.views.CompetitionSchedule.objects"
            ) as mock_schedule,
            patch("contest.views.CompetitionURL.objects") as mock_url,
            patch("contest.views.CompetitionGameFetcher") as mock_fetcher,
        ):
            mock_comp.filter.return_value.order_by.return_value = []
            mock_schedule.filter.return_value.order_by.return_value = []
            mock_url.filter.return_value.select_related.return_value = []
            mock_fetcher.return_value.GetCompetitionGamesRaw.return_value = []

            # First call should hit database
            data1 = get_competitions_data()

            # Second call should use cache
            data2 = get_competitions_data()

            # Data should be the same
            self.assertEqual(data1, data2)

            # Database should only be called once for competitions
            self.assertEqual(mock_comp.filter.call_count, 1)

            # Should include competition_games in cached data
            self.assertIn("competition_games", data1)

    def tearDown(self):
        """Clean up cache after each test."""
        cache.clear()


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
