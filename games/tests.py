import unittest
from unittest.mock import patch

from games.importer.ifwiki import IfwikiImporter, ImportFromIfwiki


class TestIfwikiImporter(unittest.TestCase):
    """Test the existing MediaWiki importer with real ifwiki.ru page."""

    def setUp(self):
        self.importer = IfwikiImporter()
        self.test_url = "https://ifwiki.ru/Таинственный_гараж"

    def test_url_matching(self):
        """Test that the importer correctly matches ifwiki.ru URLs."""
        # Test valid URLs
        valid_urls = [
            "https://ifwiki.ru/Таинственный_гараж",
            "http://ifwiki.ru/Some_Game",
            "https://ifwiki.ru/Автор:Crem",
        ]

        for url in valid_urls:
            with self.subTest(url=url):
                self.assertTrue(self.importer.Match(url))

        # Test invalid URLs
        invalid_urls = [
            "https://example.com/game",
            "https://ifwiki.org/game",  # Different domain
            "https://ifwiki.ru",  # Base URL without page
        ]

        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertFalse(self.importer.Match(url))

    @patch("games.importer.ifwiki.FetchUrlToString")
    def test_real_page_parsing(self, mock_fetch):
        """Test parsing of real Таинственный гараж page from ifwiki.ru."""
        # This is the actual wikitext from the page (simplified for testing)
        mock_wikitext = """{{game info
|название=Таинственный гараж
|автор=[[автор:Crem]]
|вышла=01.01.2020
|платформа=INSTEAD
|язык=Русский
|темы=детектив, фантастика
|обложка=Garage_cover.jpg
|IFID=12345-67890-ABCDE
}}

'''Таинственный гараж''' — это интерактивная игра в жанре \
[[Тема:детектив|детектива]] с элементами фантастики.

== Сюжет ==
Игра рассказывает о загадочном гараже, где происходят странные события...

== Особенности ==
* Нелинейный сюжет
* Множественные концовки
* Атмосферная музыка

== Ссылки ==
{{Ссылка|на=http://example.com/game.zip|1=Скачать игру}}

[[Категория:Игры]]
[[Категория:INSTEAD]]
"""

        mock_fetch.return_value = mock_wikitext

        # Call the importer
        result = ImportFromIfwiki(self.test_url)

        # Verify the result structure
        self.assertIsInstance(result, dict)
        self.assertNotIn("error", result)

        # Check extracted data
        self.assertEqual(result["title"], "Таинственный гараж")
        self.assertIn("desc", result)
        self.assertIn("Таинственный гараж", result.get("desc", ""))

        # Check authors
        self.assertIn("authors", result)
        authors = result["authors"]
        self.assertIsInstance(authors, list)
        self.assertTrue(len(authors) > 0)

        # Check for the main author
        main_author = next(
            (a for a in authors if a.get("name") == "Crem"), None
        )
        self.assertIsNotNone(main_author)
        self.assertEqual(main_author["role_slug"], "author")

        # Check tags
        self.assertIn("tags", result)
        tags = result["tags"]
        self.assertIsInstance(tags, list)

        # Check for expected tags
        tag_names = [tag.get("tag", "") for tag in tags]
        self.assertIn("INSTEAD", tag_names)  # Platform
        self.assertIn("Русский", tag_names)  # Language
        self.assertIn("детектив", tag_names)  # Theme
        self.assertIn("фантастика", tag_names)  # Theme

        # Check IFID tag
        ifid_tags = [tag for tag in tags if tag.get("cat_slug") == "ifid"]
        self.assertTrue(len(ifid_tags) > 0)
        self.assertEqual(ifid_tags[0]["tag"], "12345-67890-ABCDE")

        # Check URLs
        self.assertIn("urls", result)
        urls = result["urls"]
        self.assertIsInstance(urls, list)
        self.assertTrue(len(urls) > 0)

        # Check for game page URL
        game_page_url = next(
            (u for u in urls if u.get("url") == self.test_url), None
        )
        self.assertIsNotNone(game_page_url)

        # Check for download link
        download_urls = [u for u in urls if "example.com" in u.get("url", "")]
        self.assertTrue(len(download_urls) > 0)

        # Check for cover image (uses urlcat_slug instead of category)
        cover_urls = [u for u in urls if u.get("urlcat_slug") == "poster"]
        self.assertTrue(len(cover_urls) > 0)

        # Check release date
        self.assertIn("release_date", result)
        release_date = result["release_date"]
        self.assertIsNotNone(release_date)
        self.assertEqual(release_date.year, 2020)
        self.assertEqual(release_date.month, 1)
        self.assertEqual(release_date.day, 1)

        # Check priority
        self.assertEqual(result.get("priority"), 100)

        # Verify that description contains ifwiki.ru attribution
        desc = result.get("desc", "")
        self.assertIn("ifwiki.ru", desc.lower())

    def test_template_parsing(self):
        """Test parsing of various MediaWiki templates."""
        # Test competition template
        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = """{{ЛОК|2020}}

Игра участвовала в конкурсе ЛОК 2020.
"""
            result = ImportFromIfwiki(self.test_url)

            # Check for competition tag
            competition_tags = [
                tag
                for tag in result.get("tags", [])
                if tag.get("cat_slug") == "competition"
            ]
            self.assertTrue(len(competition_tags) > 0)
            self.assertEqual(competition_tags[0]["tag"], "ЛОК-2020")

    def test_redirect_handling(self):
        """Test handling of redirect pages."""
        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            # Mock a redirect response
            mock_fetch.return_value = "#REDIRECT [[Таинственный гараж]]"

            result = ImportFromIfwiki("https://ifwiki.ru/Redirect_Page")

            # The result should be empty for redirects since they're handled
            # recursively
            # but we should not get an error
            self.assertIsInstance(result, dict)

    def test_error_handling(self):
        """Test error handling for network failures."""
        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.side_effect = Exception("Network error")

            result = ImportFromIfwiki(self.test_url)

            # Should return error message
            self.assertIn("error", result)
            self.assertIn("открывается", result["error"])

    def test_malformed_wikitext(self):
        """Test handling of malformed wikitext."""
        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            # Mock malformed wikitext that might cause parsing errors
            mock_fetch.return_value = """{{game info
|название=Test Game
|broken template without closing}}

Incomplete wikitext...
"""

            result = ImportFromIfwiki(self.test_url)

            # Should either parse successfully or return parsing error
            if "error" in result:
                self.assertIn("парсинге", result["error"])
            else:
                # If it parses, we should get basic structure
                self.assertIsInstance(result, dict)
                self.assertIn("title", result)

    def test_empty_page(self):
        """Test handling of empty pages."""
        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = ""

            result = ImportFromIfwiki(self.test_url)

            # Should handle empty pages gracefully
            self.assertIsInstance(result, dict)
            self.assertNotIn("error", result)

    def test_author_import(self):
        """Test author import functionality."""
        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = """
Crem (настоящее имя неизвестно) — российский автор интерактивной литературы.

== Биография ==
Начал писать игры в 2015 году...

== Игры ==
* [[Таинственный гараж]] (2020)
* [[Другая игра]] (2021)

[[Категория:Авторы]]
"""

            result = self.importer.ImportAuthor("https://ifwiki.ru/Автор:Crem")

            # Check result structure
            self.assertIsInstance(result, dict)
            self.assertIn("name", result)
            self.assertIn("bio", result)
            self.assertIn("urls", result)

            # Check that ifwiki attribution is added
            self.assertIn("ifwiki.ru", result["bio"])


class TestSpecificFunctionality(unittest.TestCase):
    """Test specific functionality that was improved during migration."""

    def setUp(self):
        self.importer = IfwikiImporter()

    def test_pagename_template_processing(self):
        """Test that {{PAGENAME}} template is correctly processed."""
        test_url = "https://ifwiki.ru/Test_Game_Name"

        # Wikitext with PAGENAME template in game info
        wikitext = """{{game info
|название={{PAGENAME}}
|автор=[[автор:TestAuthor]]
|платформа=INSTEAD
}}

Test game content.
"""

        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = wikitext
            result = ImportFromIfwiki(test_url)

        # Title should be extracted from URL and used correctly
        self.assertEqual(result["title"], "Test Game Name")
        self.assertNotIn("{{PAGENAME}}", result.get("desc", ""))

    def test_gameinfo_parameter_processing(self):
        """Test game info parameter extraction and processing."""
        test_url = "https://ifwiki.ru/TestGame"

        wikitext = """{{game info
|название=Test Game
|автор=[[автор:Author One]], [[автор:Author Two]]
|вышла=15.03.2020
|платформа=QSP
|язык=Русский
|темы=фантастика, приключения
|IFID=12345-ABCDE
}}
"""

        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = wikitext
            result = ImportFromIfwiki(test_url)

        self.assertEqual(result["title"], "Test Game")
        self.assertEqual(result["release_date"].year, 2020)
        self.assertEqual(result["release_date"].month, 3)
        self.assertEqual(result["release_date"].day, 15)

        # Check authors
        authors = result["authors"]
        self.assertEqual(len(authors), 2)
        author_names = [a["name"] for a in authors]
        self.assertIn("Author One", author_names)
        self.assertIn("Author Two", author_names)

        # Check tags
        tags = result["tags"]
        tag_data = [(t["cat_slug"], t["tag"]) for t in tags]
        self.assertIn(("platform", "QSP"), tag_data)
        self.assertIn(("language", "Русский"), tag_data)
        self.assertIn(("tag", "фантастика"), tag_data)
        self.assertIn(("tag", "приключения"), tag_data)
        self.assertIn(("ifid", "12345-ABCDE"), tag_data)

    def test_competition_template_processing(self):
        """Test competition template processing."""
        test_url = "https://ifwiki.ru/TestGame"

        wikitext = """{{game info
|название=Test Game
}}
{{ЛОК|2020}}

Game participated in LOK 2020.
"""

        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = wikitext
            result = ImportFromIfwiki(test_url)

        # Check for competition tag
        tags = result["tags"]
        competition_tags = [
            t for t in tags if t.get("cat_slug") == "competition"
        ]
        self.assertEqual(len(competition_tags), 1)
        self.assertEqual(competition_tags[0]["tag"], "ЛОК-2020")

    def test_link_template_processing(self):
        """Test Ссылка template processing."""
        test_url = "https://ifwiki.ru/TestGame"

        wikitext = """{{game info
|название=Test Game
}}

Download: {{Ссылка|на=http://example.com/game.zip|1=Download Game}}
"""

        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = wikitext
            result = ImportFromIfwiki(test_url)

        # Check that URL was extracted
        urls = result["urls"]
        download_urls = [u for u in urls if "example.com" in u.get("url", "")]
        self.assertTrue(len(download_urls) > 0)

        # Check that description contains markdown link (in proper format)
        desc = result["desc"]
        self.assertIn("[Download Game](http://example.com/game.zip)", desc)

    def test_image_url_processing(self):
        """Test image URL processing from обложка parameter."""
        test_url = "https://ifwiki.ru/TestGame"

        wikitext = """{{game info
|название=Test Game
|обложка=test_cover.jpg
}}
"""

        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = wikitext
            result = ImportFromIfwiki(test_url)

        # Check for cover image URL
        urls = result["urls"]
        cover_urls = [u for u in urls if u.get("urlcat_slug") == "poster"]
        self.assertEqual(len(cover_urls), 1)
        # WikiQuote capitalizes first letter
        self.assertIn("Test_cover.jpg", cover_urls[0]["url"])

    def test_theme_tag_processing(self):
        """Test Тема template processing."""
        test_url = "https://ifwiki.ru/TestGame"

        wikitext = """{{game info
|название=Test Game
}}
{{Тема|1=horror}}

This is a horror game.
"""

        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = wikitext
            result = ImportFromIfwiki(test_url)

        # Check for theme tag
        tags = result["tags"]
        theme_tags = [
            t
            for t in tags
            if t.get("cat_slug") == "tag" and t.get("tag") == "horror"
        ]
        self.assertEqual(len(theme_tags), 1)

    def test_invalid_date_handling(self):
        """Test that invalid dates are handled gracefully."""
        test_url = "https://ifwiki.ru/TestGame"

        wikitext = """{{game info
|название=Test Game
|вышла=invalid-date
}}
"""

        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = wikitext
            result = ImportFromIfwiki(test_url)

        # Should not have release_date when date is invalid
        self.assertIsNone(result.get("release_date"))
        self.assertNotIn("error", result)

    def test_markdown_conversion(self):
        """Test basic markdown conversion functionality."""
        test_url = "https://ifwiki.ru/TestGame"

        wikitext = """{{game info
|название=Test Game
}}

'''Bold text''' and ''italic text''.

== Section Header ==
* List item 1
* List item 2

[[Internal Link|Display Text]]
"""

        with patch("games.importer.ifwiki.FetchUrlToString") as mock_fetch:
            mock_fetch.return_value = wikitext
            result = ImportFromIfwiki(test_url)

        desc = result["desc"]

        # Check markdown conversion
        self.assertIn("**Bold text**", desc)
        self.assertIn("_italic text_", desc)
        self.assertIn("## Section Header", desc)
        self.assertIn("* List item", desc)
        # Internal links become bold (without display text processing)
        self.assertIn("**Internal Link**", desc)


if __name__ == "__main__":
    unittest.main()
