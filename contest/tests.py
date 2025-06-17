import datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .views import _seconds_until_midnight, get_competitions_data


class CacheUtilsTest(TestCase):
    def test_seconds_until_midnight(self):
        """Test that _seconds_until_midnight calculates correctly."""
        # Mock timezone.now to return a known time
        mock_time = timezone.now().replace(hour=14, minute=30, second=0, microsecond=0)
        
        with patch('contest.views.timezone.now', return_value=mock_time):
            seconds = _seconds_until_midnight()
            
            # Should be approximately 9.5 hours (34200 seconds) until midnight
            expected = 9.5 * 60 * 60  # 9.5 hours in seconds
            self.assertAlmostEqual(seconds, expected, delta=60)  # Allow 1 minute variance

    def test_get_competitions_data_caching(self):
        """Test that get_competitions_data properly caches data."""
        # Clear cache first
        cache.delete('contest:competitions_list_data')
        
        # Mock the database queries to return empty results
        with patch('contest.views.Competition.objects') as mock_comp, \
             patch('contest.views.CompetitionSchedule.objects') as mock_schedule, \
             patch('contest.views.CompetitionURL.objects') as mock_url:
            
            mock_comp.filter.return_value.order_by.return_value = []
            mock_schedule.filter.return_value.order_by.return_value = []
            mock_url.filter.return_value.select_related.return_value = []
            
            # First call should hit database
            data1 = get_competitions_data()
            
            # Second call should use cache
            data2 = get_competitions_data()
            
            # Data should be the same
            self.assertEqual(data1, data2)
            
            # Database should only be called once for competitions
            self.assertEqual(mock_comp.filter.call_count, 1)

    def tearDown(self):
        """Clean up cache after each test."""
        cache.clear()
