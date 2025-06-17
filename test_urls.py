"""
Simple URL routing tests for the IFDB project.
Tests that URL patterns can be resolved correctly after modernization.
"""

from django.test import TestCase
from django.urls import resolve, reverse


class URLRoutingTests(TestCase):
    """Test URL routing and reversal."""

    def test_main_urls_reverse(self):
        """Test that main URLs can be reversed correctly."""
        # Test basic URL reversal
        urls_to_test = [
            ("index", "/index/"),
            ("add_game", "/game/add/"),
            ("list_games", "/game/"),
            ("list_authors", "/author/"),
            ("list_competitions", "/jam/"),
        ]

        for url_name, expected_path in urls_to_test:
            with self.subTest(url_name=url_name):
                actual_path = reverse(url_name)
                self.assertEqual(actual_path, expected_path)

    def test_parameterized_urls_reverse(self):
        """Test that parameterized URLs can be reversed correctly."""
        # Test URLs with parameters
        self.assertEqual(
            reverse("show_game", kwargs={"game_id": 123}), "/game/123/"
        )
        self.assertEqual(
            reverse("edit_game", kwargs={"game_id": 456}), "/game/edit/456/"
        )
        self.assertEqual(
            reverse("show_author", kwargs={"author_id": 789}), "/author/789/"
        )

    def test_url_resolution(self):
        """Test that URLs resolve to correct view names."""
        # Test that paths resolve correctly
        resolver = resolve("/index/")
        self.assertEqual(resolver.url_name, "index")

        resolver = resolve("/game/123/")
        self.assertEqual(resolver.url_name, "show_game")
        self.assertEqual(resolver.kwargs, {"game_id": 123})

        resolver = resolve("/author/456/")
        self.assertEqual(resolver.url_name, "show_author")
        self.assertEqual(resolver.kwargs, {"author_id": 456})

    def test_competition_urls(self):
        """Test competition-related URL patterns."""
        # Test competition list
        self.assertEqual(reverse("list_competitions"), "/jam/")

        # Test competition detail with slug and doc
        resolver = resolve("/jam/test-comp/rules.html")
        self.assertEqual(resolver.url_name, "show_competition")
        self.assertEqual(
            resolver.kwargs, {"slug": "test-comp", "doc": "rules.html"}
        )

    def test_api_urls(self):
        """Test API endpoint URLs."""
        api_urls = [
            ("json_gameinfo", "/json/gameinfo/"),
            ("json_search", "/json/search/"),
            ("upload", "/json/upload/"),
        ]

        for url_name, expected_path in api_urls:
            with self.subTest(url_name=url_name):
                actual_path = reverse(url_name)
                self.assertEqual(actual_path, expected_path)
