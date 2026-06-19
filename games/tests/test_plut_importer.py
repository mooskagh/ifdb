import unittest
from unittest.mock import patch

from games.importer.plut import (
    PLUT_HEADERS,
    FetchPlut,
    GetCandidates,
    ImportFromPlut,
    ParsePlut,
)

PLUT_BODY_OPEN = (
    '<div class="field field-name-body field-type-text-with-summary '
    'field-label-hidden"><div class="field-items">'
)


def plut_html(body):
    return (
        f'<h1 class="title">Test Game</h1>{PLUT_BODY_OPEN}{body}</div></div>'
    )


class TestPlutImporter(unittest.TestCase):
    @patch("games.importer.plut.FetchUrlToString")
    def test_get_candidates_uses_curl_user_agent(self, mock_fetch):
        mock_fetch.return_value = ""

        self.assertEqual(GetCandidates(), [])

        mock_fetch.assert_called_once_with(
            "http://urq.plut.info/games?page=0",
            use_cache=False,
            headers=PLUT_HEADERS,
        )

    @patch("games.importer.plut.FetchUrlToString")
    def test_import_from_plut_uses_curl_user_agent(self, mock_fetch):
        mock_fetch.return_value = '<h1 class="title">Test Game</h1>'

        result = ImportFromPlut("http://urq.plut.info/node/961")

        self.assertEqual(result["title"], "Test Game")
        mock_fetch.assert_called_once_with(
            "http://urq.plut.info/node/961",
            use_cache=False,
            headers=PLUT_HEADERS,
        )

    def test_parse_plut_filters_cloudflare_email_protection_links(self):
        result = ParsePlut(
            plut_html(
                '<p>Напишите <a href="/cdn-cgi/l/email-protection#111">'
                '<span class="__cf_email__" data-cfemail="222">'
                "[email&#160;protected]</span></a>.</p>"
            ),
            "http://urq.plut.info/node/54",
        )

        self.assertIn("protected", result["desc"])
        self.assertNotIn("email-protection", result["desc"])
        self.assertFalse(
            any("email-protection" in url["url"] for url in result["urls"])
        )

    def test_parse_plut_resolves_relative_description_links(self):
        result = ParsePlut(
            plut_html('<p><a href="/texts/info">Материалы</a></p>'),
            "http://urq.plut.info/node/54",
        )

        self.assertIn(
            {
                "urlcat_slug": "game_page",
                "description": "Материалы",
                "url": "http://urq.plut.info/texts/info",
            },
            result["urls"],
        )

    @patch("games.importer.plut.FetchUrlToString")
    def test_fetch_plut_applies_curl_user_agent(self, mock_fetch):
        mock_fetch.return_value = "html"

        self.assertEqual(FetchPlut("http://urq.plut.info/node/961"), "html")

        mock_fetch.assert_called_once_with(
            "http://urq.plut.info/node/961",
            use_cache=False,
            headers=PLUT_HEADERS,
        )
