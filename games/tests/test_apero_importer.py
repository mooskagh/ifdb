from unittest import TestCase
from unittest.mock import patch
from urllib.parse import quote

from games.importer.apero import (
    FetchCandidateUrls,
    _catalog_page_count,
    _extract_candidate_urls,
)


def catalog_html(*game_urls, pages=()):
    pagination = "".join(f'<a data-page="{page}"></a>' for page in pages)
    games = "".join(f'<h2><a href="{url}">Title</a></h2>' for url in game_urls)
    return pagination + games


class AperoDiscoveryTest(TestCase):
    def test_extract_candidate_urls_accepts_current_https_listing(self):
        urls = _extract_candidate_urls(
            catalog_html("https://apero.ru/Текстовые-игры/Пять-костей")
        )

        self.assertEqual(urls, ["https://apero.ru/Текстовые-игры/Пять-костей"])

    def test_catalog_page_count_uses_largest_pagination_page(self):
        html = catalog_html(pages=[1, 2, 23, 24])

        self.assertEqual(_catalog_page_count(html), 24)

    def test_catalog_page_count_defaults_to_one_without_pagination(self):
        self.assertEqual(_catalog_page_count(""), 1)

    @patch("games.importer.apero.FetchUrlToString")
    def test_fetch_candidate_urls_crawls_catalog_pages(self, fetch):
        fetch.side_effect = [
            catalog_html(
                "https://apero.ru/Текстовые-игры/Первая",
                "https://apero.ru/Текстовые-игры/Повтор",
                pages=[1, 2],
            ),
            catalog_html(
                "https://apero.ru/Текстовые-игры/Повтор",
                "https://apero.ru/Текстовые-игры/Вторая",
            ),
        ]

        urls = FetchCandidateUrls()

        self.assertEqual(
            [call.args[0] for call in fetch.call_args_list],
            [
                "https://apero.ru/" + quote("Текстовые-игры") + "/Каталог/1",
                "https://apero.ru/" + quote("Текстовые-игры") + "/Каталог/2",
            ],
        )
        self.assertEqual(
            urls,
            [
                "https://apero.ru/"
                + quote("Текстовые-игры")
                + "/"
                + quote("Первая"),
                "https://apero.ru/"
                + quote("Текстовые-игры")
                + "/"
                + quote("Повтор"),
                "https://apero.ru/"
                + quote("Текстовые-игры")
                + "/"
                + quote("Вторая"),
            ],
        )
