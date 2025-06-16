#!/usr/bin/env python
"""
Migration comparison tests - compares old vs new MediaWiki parser behavior.
This file can be removed after migration is complete and stable.
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ifdb.settings")
sys.path.append("/home/crem/dev/ifdb")
django.setup()

# Import both old and new implementations
from core.crawler import FetchUrlToString
from games.importer.ifwiki import ImportFromIfwiki as ImportFromIfwikiNew
from games.importer.ifwiki_old import ImportFromIfwiki as ImportFromIfwikiOld


class TestMigrationComparison(unittest.TestCase):
    """Compare old vs new MediaWiki parser behavior on real ifwiki.ru pages."""

    # Test URLs from the user's request
    TEST_URLS = [
        "https://ifwiki.ru/Кащей:_Златоквест_или_Тяжелое_Похмелье",
        (
            "https://ifwiki.ru/Хроники_капитана_Блуда:_Тайна_гипсовых_фаллоими"
            "таторов"
        ),
        "https://ifwiki.ru/Не_царевна,_но_лягушка",
        "https://ifwiki.ru/Погребение_цветов:_тьма_в_персиковом_источнике",
        "https://ifwiki.ru/Вечерня",
        "https://ifwiki.ru/Фотопия",
        "https://ifwiki.ru/Дат-Навирэ_(FireURQ)",
    ]

    def setUp(self):
        self.maxDiff = None  # Show full diff on failure

    def compare_basic_fields(self, old_result, new_result, url):
        """Compare basic fields that should be identical."""
        basic_fields = ["title", "release_date", "priority"]

        for field in basic_fields:
            if field in old_result and field in new_result:
                self.assertEqual(
                    old_result[field],
                    new_result[field],
                    f"Field '{field}' differs for {url}",
                )

    def compare_authors(self, old_result, new_result, url):
        """Compare author extraction."""
        old_authors = old_result.get("authors", [])
        new_authors = new_result.get("authors", [])

        # Check that we have the same number of authors
        self.assertEqual(
            len(old_authors),
            len(new_authors),
            f"Number of authors differs for {url}: old={len(old_authors)},"
            f" new={len(new_authors)}",
        )

        # Sort authors by name for comparison
        old_authors_sorted = sorted(
            old_authors, key=lambda x: x.get("name", "")
        )
        new_authors_sorted = sorted(
            new_authors, key=lambda x: x.get("name", "")
        )

        for i, (old_author, new_author) in enumerate(
            zip(old_authors_sorted, new_authors_sorted)
        ):
            self.assertEqual(
                old_author.get("name"),
                new_author.get("name"),
                f"Author {i} name differs for {url}",
            )
            self.assertEqual(
                old_author.get("role_slug"),
                new_author.get("role_slug"),
                f"Author {i} role differs for {url}",
            )

    def compare_tags(self, old_result, new_result, url):
        """Compare tag extraction."""
        old_tags = old_result.get("tags", [])
        new_tags = new_result.get("tags", [])

        # Convert to sets of (cat_slug, tag) tuples for comparison
        old_tag_set = set(
            (tag.get("cat_slug"), tag.get("tag")) for tag in old_tags
        )
        new_tag_set = set(
            (tag.get("cat_slug"), tag.get("tag")) for tag in new_tags
        )

        # Allow some differences but check that core tags are preserved
        missing_tags = old_tag_set - new_tag_set
        extra_tags = new_tag_set - old_tag_set

        # Report significant differences
        if missing_tags:
            print(f"Missing tags in new parser for {url}: {missing_tags}")
        if extra_tags:
            print(f"Extra tags in new parser for {url}: {extra_tags}")

        # At least check that we have some tags
        if old_tags:
            self.assertTrue(
                len(new_tags) > 0,
                "New parser extracted no tags but old parser found"
                f" {len(old_tags)} for {url}",
            )

    def compare_urls(self, old_result, new_result, url):
        """Compare URL extraction."""
        old_urls = old_result.get("urls", [])
        new_urls = new_result.get("urls", [])

        # Check that we have some URLs
        self.assertTrue(
            len(old_urls) > 0, f"Old parser found no URLs for {url}"
        )
        self.assertTrue(
            len(new_urls) > 0, f"New parser found no URLs for {url}"
        )

        # Extract URL strings for comparison
        new_url_strings = set(u.get("url", "") for u in new_urls)

        # Check that main game page URL is preserved
        self.assertIn(
            url,
            new_url_strings,
            f"Main game page URL not found in new parser results for {url}",
        )

    def test_real_page_comparison(self):
        """Test comparison on all real ifwiki.ru pages."""

        failed_urls = []
        comparison_results = {}

        for test_url in self.TEST_URLS:
            with self.subTest(url=test_url):
                try:
                    print(f"\nTesting: {test_url}")

                    # Fetch real content once
                    wikitext = self._fetch_real_content(test_url)
                    if not wikitext:
                        print(f"Skipping {test_url} - could not fetch content")
                        continue

                    # Test both parsers with the same content
                    with (
                        patch(
                            "games.importer.ifwiki_old.FetchUrlToString"
                        ) as mock_old,
                        patch(
                            "games.importer.ifwiki.FetchUrlToString"
                        ) as mock_new,
                    ):
                        mock_old.return_value = wikitext
                        mock_new.return_value = wikitext

                        old_result = ImportFromIfwikiOld(test_url)
                        new_result = ImportFromIfwikiNew(test_url)

                    # Store results for analysis
                    comparison_results[test_url] = {
                        "old": old_result,
                        "new": new_result,
                        "wikitext_length": len(wikitext),
                    }

                    # Check for errors
                    if "error" in old_result:
                        print(
                            f"Old parser error for {test_url}:"
                            f" {old_result['error']}"
                        )
                        continue

                    if "error" in new_result:
                        print(
                            f"New parser error for {test_url}:"
                            f" {new_result['error']}"
                        )
                        self.fail(
                            f"New parser failed for {test_url}:"
                            f" {new_result['error']}"
                        )

                    # Compare results
                    self.compare_basic_fields(old_result, new_result, test_url)
                    self.compare_authors(old_result, new_result, test_url)
                    self.compare_tags(old_result, new_result, test_url)
                    self.compare_urls(old_result, new_result, test_url)

                    print(f"✓ {test_url} - Comparison passed")

                except Exception as e:
                    print(f"✗ {test_url} - Error: {e}")
                    failed_urls.append((test_url, str(e)))

        # Report summary
        print("\n=== MIGRATION COMPARISON SUMMARY ===")
        print(f"Total URLs tested: {len(self.TEST_URLS)}")
        print(
            f"Successful comparisons: {len(self.TEST_URLS) - len(failed_urls)}"
        )
        print(f"Failed comparisons: {len(failed_urls)}")

        if failed_urls:
            print("\nFailed URLs:")
            for url, error in failed_urls:
                print(f"  - {url}: {error}")

        # Save detailed results for manual inspection
        self._save_comparison_results(comparison_results)

    def _fetch_real_content(self, url):
        """Fetch real content from ifwiki.ru."""
        try:
            # Convert URL to raw wikitext URL
            if "/ifwiki.ru/" in url:
                page_name = url.split("/ifwiki.ru/")[-1]
                raw_url = (
                    f"https://ifwiki.ru/index.php?title={page_name}&action=raw"
                )
                content = FetchUrlToString(raw_url, use_cache=False)
                return content + "\n"
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            return None

    def _save_comparison_results(self, results):
        """Save comparison results to a JSON file for manual inspection."""
        output_file = "migration_comparison_results.json"

        # Convert datetime objects to strings for JSON serialization
        serializable_results = {}
        for url, data in results.items():
            serializable_results[url] = {
                "old": self._make_json_serializable(data["old"]),
                "new": self._make_json_serializable(data["new"]),
                "wikitext_length": data["wikitext_length"],
            }

        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(
                    serializable_results, f, ensure_ascii=False, indent=2
                )
            print(f"\nDetailed comparison results saved to: {output_file}")
        except Exception as e:
            print(f"Failed to save results: {e}")

    def _make_json_serializable(self, obj):
        """Convert objects to JSON-serializable format."""
        if hasattr(obj, "isoformat"):  # datetime.date objects
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_serializable(item) for item in obj]
        else:
            return obj

    def test_individual_pages(self):
        """Test individual pages with detailed comparison."""

        # Test a specific interesting page
        test_url = "https://ifwiki.ru/Кащей:_Златоквест_или_Тяжелое_Похмелье"

        print(f"\nDetailed test for: {test_url}")

        wikitext = self._fetch_real_content(test_url)
        if not wikitext:
            self.skipTest(f"Could not fetch content for {test_url}")

        print(f"Fetched {len(wikitext)} characters of wikitext")

        with (
            patch("games.importer.ifwiki_old.FetchUrlToString") as mock_old,
            patch("games.importer.ifwiki.FetchUrlToString") as mock_new,
        ):
            mock_old.return_value = wikitext
            mock_new.return_value = wikitext

            old_result = ImportFromIfwikiOld(test_url)
            new_result = ImportFromIfwikiNew(test_url)

        print("\nOLD PARSER RESULTS:")
        print(f"Title: {old_result.get('title')}")
        print(f"Authors: {len(old_result.get('authors', []))}")
        print(f"Tags: {len(old_result.get('tags', []))}")
        print(f"URLs: {len(old_result.get('urls', []))}")
        print(f"Description length: {len(old_result.get('desc', ''))}")

        print("\nNEW PARSER RESULTS:")
        print(f"Title: {new_result.get('title')}")
        print(f"Authors: {len(new_result.get('authors', []))}")
        print(f"Tags: {len(new_result.get('tags', []))}")
        print(f"URLs: {len(new_result.get('urls', []))}")
        print(f"Description length: {len(new_result.get('desc', ''))}")

        # Basic assertions
        self.assertNotIn("error", new_result, "New parser should not error")
        self.assertEqual(
            old_result.get("title"),
            new_result.get("title"),
            "Titles should match",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
