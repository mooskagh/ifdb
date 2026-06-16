import unittest
from unittest.mock import patch

from games.importer.plut import GetCandidates, ImportFromPlut, PLUT_HEADERS


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
            "http://urq.plut.info/node/961", headers=PLUT_HEADERS
        )
