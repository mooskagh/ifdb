import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

from games.importer.axma import AxmaImporter, FetchCandidateUrls, ParseAxma


class AxmaImporterTest(TestCase):
    def setUp(self) -> None:
        self.importer = AxmaImporter()

    def test_match(self) -> None:
        self.assertTrue(
            self.importer.Match("https://axmajs.ru/library/?id=224")
        )
        self.assertTrue(self.importer.Match("http://axmajs.ru/library/?id=1"))
        self.assertFalse(self.importer.Match("https://axmajs.ru/library/"))
        self.assertFalse(
            self.importer.Match("https://axmajs.ru/library/?sort=last")
        )
        self.assertFalse(
            self.importer.Match("https://example.com/library/?id=224")
        )

    def test_match_with_cat(self) -> None:
        self.assertTrue(
            self.importer.MatchWithCat(
                "https://axmajs.ru/library/?id=224", "game_page"
            )
        )
        self.assertFalse(
            self.importer.MatchWithCat(
                "https://axmajs.ru/library/?id=224", "play_online"
            )
        )

    @patch("games.importer.axma.FetchUrlToString")
    def test_fetch_candidate_urls(self, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = [
            (
                "<div>"
                "<a nohr='/include/download_zip.php?id=101'></a>"
                "<a nohr='/include/download_zip.php?id=102'></a>"
                "</div>"
            ),
            ("<div><a nohr='/include/download_zip.php?id=103'></a></div>"),
            "<div><p>Empty page</p></div>",
        ]

        candidates = FetchCandidateUrls()

        self.assertEqual(
            candidates,
            [
                "https://axmajs.ru/library/?id=101",
                "https://axmajs.ru/library/?id=102",
                "https://axmajs.ru/library/?id=103",
            ],
        )
        self.assertEqual(mock_fetch.call_count, 3)

    def test_parse_axma_full(self) -> None:
        sample_html = (
            "<article>"
            "<a href='https://lib.axmajs.ru/BV2APb6M/' target='_blank'>"
            "<h5>Кухонный нож и новогодний прием (16+)"
            "<span class='version'>v5</span>"
            "<span class='author'>Автор: Психолог Макс</span></h5>"
            "</a>"
            "<div class='pubinfo small' style='float:left;'>"
            "Параграфов:&nbsp;137. Размер:&nbsp;771&nbsp;Кб</div>"
            "<div class='small' style='float:right;'>09.12.21</div>"
            "<div style='clear:both;'>"
            "<a href='https://lib.axmajs.ru/BV2APb6M/' target='_blank'>"
            "<img class='coverlib' src='/lib/BV2APb6M/cover.jpg'></a></div>"
            "<div class='pubbuttons small'>"
            "<a href='https://lib.axmajs.ru/BV2APb6M/' target='_blank'>"
            "<button style='margin-bottom:1em;'>Запустить</button></a>"
            "<a nohr='/include/download_zip.php?id=224' href=''"
            " onclick=\"this.href=this.getAttribute('nohr')\">"
            "<button normal style='margin-left:1em;'>Скачать</button></a>"
            "<p><a href='?id=224#last'>"
            "<span class='date' style='margin:0;'>18</span>"
            "<span class='rating'>★★★★★</span></a></p>"
            "</div>"
            "<div style='clear:both;'></div>ru"
            "<div style='margin-top:1em;' class='small'>"
            "<a href='?tag=2' style='margin-right:1em;'>Фантастика</a>"
            "<a href='?tag=1' style='margin-right:1em;'>Детектив / Триллер</a>"
            "</div>"
            "<div class='subtitle'>Захватывающий детектив.</div>"
            "<h3>Последние комментарии</h3>"
            "<div class='comment_block'>Some comments</div>"
            "</article>"
        )

        url = "https://axmajs.ru/library/?id=224"
        res = ParseAxma(sample_html, url)

        self.assertEqual(res["title"], "Кухонный нож и новогодний прием (16+)")
        self.assertEqual(
            res["authors"], [{"role_slug": "author", "name": "Психолог Макс"}]
        )
        self.assertEqual(res["release_date"], datetime.date(2021, 12, 9))
        self.assertEqual(
            res["desc"],
            "Захватывающий детектив.",
        )
        self.assertEqual(res["description_attributions"], ["axmajs.ru"])

        self.assertIn(
            {"cat_slug": "platform", "tag": "AXMA Story Maker JS"}, res["tags"]
        )
        self.assertIn({"cat_slug": "language", "tag": "Русский"}, res["tags"])
        self.assertIn({"cat_slug": "version", "tag": "v5"}, res["tags"])
        self.assertIn({"cat_slug": "tag", "tag": "Фантастика"}, res["tags"])
        self.assertIn(
            {"cat_slug": "tag", "tag": "Детектив / Триллер"}, res["tags"]
        )

        url_map = {u["urlcat_slug"]: u["url"] for u in res["urls"]}
        self.assertEqual(url_map["game_page"], url)
        self.assertEqual(
            url_map["play_online"], "https://lib.axmajs.ru/BV2APb6M/"
        )
        self.assertEqual(
            url_map["download_direct"],
            "https://axmajs.ru/include/download_zip.php?id=224",
        )
        self.assertEqual(
            url_map["poster"],
            "https://axmajs.ru/lib/BV2APb6M/cover.jpg",
        )

    def test_parse_missing_game(self) -> None:
        res = ParseAxma(
            "<html><body>Empty</body></html>",
            "https://axmajs.ru/library/?id=999",
        )
        self.assertIn("error", res)
