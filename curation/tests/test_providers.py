from io import StringIO
from unittest.mock import patch
from urllib.parse import quote

from django.core.management import call_command
from django.test import TestCase

from curation.providers import (
    AperoProvider,
    AxmaProvider,
    CanonicalAuthor,
    HyperbookProvider,
    IfictionProvider,
    IfwikiProvider,
    InsteadGamesProvider,
    PlutProvider,
    QspSuProvider,
    QuestBookProvider,
    RilarhivProvider,
)
from games.gameinfo import parse


class ProviderTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def assert_round_trips(self, info):
        """The canonical doc re-parses to itself (text-level idempotence)."""
        canonical = info.to_canonical()
        self.assertEqual(parse(canonical).to_canonical(), canonical)

    def _tag_texts(self, info):
        return [t.text or t.slug for t in info.tags]

    def _person_names(self, info, role):
        return [p.name for p in info.personalities.get(role, [])]

    def _url_cats(self, info):
        return {u.category for u in info.urls}


APERO_HTML = """
<dd itemprop="name"><div title="t">Аперо игра</div></dd>
<meta itemprop="datePublished" content="2021-03-04">
<dt>Описание:</dt>
<dd><div>Описание тут.</div>
<a itemprop="author" href="http://apero.ru/x">Alice</a>
"""

APERO_AUTHOR_HTML = "<dt>О себе:</dt><dd>Биография.</dd>"


class AperoProviderTest(ProviderTestBase):
    url = "https://apero.ru/" + quote("Текстовые-игры") + "/Игра"

    def test_canonicalize(self):
        info = AperoProvider().canonicalize(APERO_HTML, self.url)
        self.assertEqual(info.name, "Аперо игра")
        self.assertEqual(info.date, "2021-03-04")
        self.assertIn("Описание тут.", info.description)
        self.assertEqual(self._person_names(info, "author"), ["Alice"])
        self.assertIn("Аперо", self._tag_texts(info))
        self.assertIn("play_online", self._url_cats(info))
        self.assertEqual([a.name for a in info.attributions], ["apero.ru"])
        self.assert_round_trips(info)

    def test_canonicalize_author(self):
        url = "http://apero.ru/" + quote("Участники") + "/Alice"
        author = AperoProvider().canonicalize_author(APERO_AUTHOR_HTML, url)
        self.assertIsInstance(author, CanonicalAuthor)
        self.assertEqual(author.name, "Alice")
        self.assertIn("Биография.", author.bio)
        self.assertTrue(author.urls)


IFWIKI_WIKITEXT = """{{game info
|название=Таинственный гараж
|автор=[[автор:Crem]]
|вышла=01.01.2020
|платформа=INSTEAD
|язык=Русский
|темы=детектив, фантастика
|обложка=Garage_cover.jpg
|IFID=12345-67890-ABCDE
}}

'''Таинственный гараж''' — детектив с элементами фантастики.

== Ссылки ==
{{Ссылка|на=http://example.com/game.zip|1=Скачать игру}}

[[Категория:Игры]]
"""

IFWIKI_AUTHOR_WIKITEXT = """Crem — автор интерактивной литературы.

[[Категория:Авторы]]
"""


class IfwikiProviderTest(ProviderTestBase):
    url = "https://ifwiki.ru/Таинственный_гараж"

    def test_canonicalize(self):
        info = IfwikiProvider().canonicalize(IFWIKI_WIKITEXT, self.url)
        self.assertEqual(info.name, "Таинственный гараж")
        self.assertEqual(info.date, "2020-01-01")
        self.assertEqual(self._person_names(info, "author"), ["Crem"])
        texts = self._tag_texts(info)
        self.assertIn("INSTEAD", texts)
        self.assertIn("детектив", texts)
        self.assertIn("12345-67890-ABCDE", texts)
        self.assertIn("game_page", self._url_cats(info))
        self.assertIn("download_direct", self._url_cats(info))
        self.assertEqual([a.name for a in info.attributions], ["ifwiki.ru"])
        self.assert_round_trips(info)

    def test_canonicalize_extracts_markdown_links(self):
        raw = """
== Ссылки ==
* [Обсуждение на форуме](http://instead-games.ru/forum/index.php?p=/discussion/560)
"""
        info = IfwikiProvider().canonicalize(raw, self.url)

        self.assertIn(
            ("forum", "Обсуждение на форуме", None),
            [(u.category, u.description, u.url_id) for u in info.urls],
        )
        self.assertIn(
            "http://instead-games.ru/forum/index.php?p=/discussion/560",
            [u.url for u in info.urls],
        )

    def test_canonicalize_author(self):
        author = IfwikiProvider().canonicalize_author(
            IFWIKI_AUTHOR_WIKITEXT, "https://ifwiki.ru/Автор:Crem"
        )
        self.assertIsInstance(author, CanonicalAuthor)
        self.assertEqual(author.name, "Автор:Crem")
        self.assertIn("ifwiki.ru", author.bio)


INSTEAD_HTML = """
<h2>[URQ] Моя инстед-игра</h2>
<div class="gamedsc">Описание.</div>
<div id="panel"><b>Автор</b>: Alice, Bob<br><b>Дата</b>: 2020.05.06<br></div>
"""


class InsteadGamesProviderTest(ProviderTestBase):
    url = "http://instead-games.ru/game.php?ID=42"

    def test_canonicalize(self):
        info = InsteadGamesProvider().canonicalize(INSTEAD_HTML, self.url)
        self.assertEqual(info.name, "Моя инстед-игра")  # [URQ] prefix trimmed
        self.assertEqual(info.date, "2020-05-06")
        self.assertEqual(self._person_names(info, "author"), ["Alice", "Bob"])
        self.assertIn("INSTEAD", self._tag_texts(info))
        self.assertIn("game_page", self._url_cats(info))
        self.assert_round_trips(info)

    def test_no_author_canonicalization(self):
        self.assertIsNone(
            InsteadGamesProvider().canonicalize_author("", self.url)
        )


QUESTBOOK_HTML = """
<h2 class="mt-1">Квестбук игра</h2>
<td class="text-left">Краткое описание</td>
<td class="text-left">Краткое.</td>
"""


class QuestBookProviderTest(ProviderTestBase):
    url = "https://quest-book.ru/online/view/123"

    def test_canonicalize(self):
        info = QuestBookProvider().canonicalize(QUESTBOOK_HTML, self.url)
        self.assertEqual(info.name, "Квестбук игра")
        self.assertIn("Краткое.", info.description)
        self.assertIn("Questbook", self._tag_texts(info))
        self.assertIn("game_page", self._url_cats(info))
        self.assertEqual(
            [a.name for a in info.attributions], ["quest-book.ru"]
        )
        self.assert_round_trips(info)


IFICTION_HTML = """
<h1><b><span>Моя игра</span></b></h1>
<div id="game_authors">Автор: \
<a href="http://forum.ifiction.ru/profile.php?id=1">Alice</a> &middot; \
Платформа: <a href="http://example.com/p">INSTEAD</a></div>
<div align="justify" style="font-size:1.2em; margin-top:10px;">Описание.</div>
<td valign="top" style="border:0; padding:0px 0 0 5px;">\
<a href="http://example.com/game.zip"><b>Скачать</b></a></td>
"""


class IfictionProviderTest(ProviderTestBase):
    url = "http://forum.ifiction.ru/viewtopic.php?id=99"

    def test_canonicalize(self):
        info = IfictionProvider().canonicalize(IFICTION_HTML, self.url)
        self.assertEqual(info.name, "Моя игра")
        self.assertEqual(self._person_names(info, "author"), ["Alice"])
        self.assertIn("INSTEAD", self._tag_texts(info))
        self.assertIn("download_direct", self._url_cats(info))
        self.assertEqual([a.name for a in info.attributions], ["ifiction.ru"])
        self.assert_round_trips(info)


QSP_JSON = """
{
  "data": {
    "slug": "123-qsp-igra",
    "name": "QSP игра",
    "lang": "ru",
    "ver": "1.0",
    "authors": "Alice, Bob",
    "translators": "Carol",
    "description_html": "<p>Описание QSP.</p>",
    "cover_url": "https://qsp.org/storage/games/123/cover.png",
    "icon_url": null,
    "file_url": "https://qsp.org/games/123-qsp-igra/download",
    "created_at": "2021-03-04T10:20:30+00:00"
  }
}
"""


class QspSuProviderTest(ProviderTestBase):
    url = "https://qsp.org/games/123-qsp-igra"

    def test_canonicalize(self):
        info = QspSuProvider().canonicalize(QSP_JSON, self.url)
        self.assertEqual(info.name, "QSP игра")
        self.assertEqual(info.date, "2021-03-04")
        self.assertEqual(self._person_names(info, "author"), ["Alice", "Bob"])
        self.assertEqual(self._person_names(info, "translator"), ["Carol"])
        self.assertIn("QSP", self._tag_texts(info))
        self.assertIn("1.0", self._tag_texts(info))
        self.assertIn("русский", self._tag_texts(info))
        self.assertIn("game_page", self._url_cats(info))
        self.assertIn("download_direct", self._url_cats(info))
        self.assertIn("poster", self._url_cats(info))
        self.assertEqual([a.name for a in info.attributions], ["qsp.org"])
        self.assert_round_trips(info)

    def test_qsp_language_untranslated_for_unknown(self):
        json_en = QSP_JSON.replace('"lang": "ru"', '"lang": "en"')
        info_en = QspSuProvider().canonicalize(json_en, self.url)
        self.assertIn("английский", self._tag_texts(info_en))

        json_fr = QSP_JSON.replace('"lang": "ru"', '"lang": "fr"')
        info_fr = QspSuProvider().canonicalize(json_fr, self.url)
        self.assertIn("fr", self._tag_texts(info_fr))

    def test_discover_reads_api_pages(self):
        pages = {
            1: '{"data":[{"slug":"1-one"}],"meta":{"last_page":2}}',
            2: '{"data":[{"slug":"2-two"}],"meta":{"last_page":2}}',
        }

        with patch(
            "curation.providers.FetchQspApiGameList",
            side_effect=lambda page, use_cache: pages[page],
        ) as fetch:
            urls = [source.url for source in QspSuProvider().discover()]

        self.assertEqual(
            urls,
            ["https://qsp.org/games/1-one", "https://qsp.org/games/2-two"],
        )
        self.assertEqual(fetch.call_count, 2)


PLUT_HTML = """
<h1 class="title">Плут игра</h1>
<div class="field-label">Статус:</div><div class="field-items">\
<a href="/x">готовая</a></div>
<div class="field-label">Авторы:</div><div class="field-items">\
<a href="/author/alice">Alice</a></div>
"""


class PlutProviderTest(ProviderTestBase):
    url = "http://urq.plut.info/node/123"

    def test_canonicalize(self):
        info = PlutProvider().canonicalize(PLUT_HTML, self.url)
        self.assertEqual(info.name, "Плут игра")
        self.assertEqual(self._person_names(info, "author"), ["Alice"])
        self.assertIn("released", self._tag_texts(info))  # "готовая" → slug
        self.assertIn("game_page", self._url_cats(info))
        self.assert_round_trips(info)

    def test_canonicalize_stabilizes_cloudflare_email_links(self):
        def html(email_href_hash, email_data_hash):
            return (
                '<h1 class="title">Плут игра</h1>'
                '<div class="field field-name-body '
                'field-type-text-with-summary field-label-hidden">'
                '<div class="field-items"><p>Пишите '
                f'<a href="/cdn-cgi/l/email-protection#{email_href_hash}">'
                f'<span class="__cf_email__" data-cfemail="{email_data_hash}">'
                "[email&#160;protected]</span></a>.</p></div></div>"
            )

        first = PlutProvider().canonicalize(html("111", "222"), self.url)
        second = PlutProvider().canonicalize(html("333", "444"), self.url)

        canonical = first.to_canonical()
        self.assertEqual(canonical, second.to_canonical())
        self.assertNotIn("email-protection", canonical)
        self.assertNotIn("cdn-cgi", canonical)


RILARHIV_QSP_HTML = """
<P><b><a href="qsp/Battle.rar">"Битва колдунов" Lostas 21</a></b>
(21 Кбайт) </P>
"""

RILARHIV_ONLINE_HTML = """
<P><b><a href="vneplatform/Voprosi.zip">"Вопросы"
(Ілля Feelviy Васильев; Inklewriter) </a></b> (3 Кбайт) //
<STRONG><a href="https://writer.inklestudios.com/stories/rhcb"
TARGET="_blank">(играть онлайн)</a></STRONG> </P>
"""

RILARHIV_EXTERNAL_HTML = """
<P><b><a href="http://narmiel.github.io/UrqW/#support"
TARGET="_blank">"Драконий остров" (Шушкарт; UrqW)</a></b></P>
"""

RILARHIV_SPECTRUM_HTML = """
<P><b><a href="spectrum/APOLLO.rar">"APOLLO" Jokersoft, 1996</a></b>
(63 Кбайт) </P>
"""

RILARHIV_TRANSLATION_HTML = """
<P><b><a href="rinform/TangleR.rar">"Spider And Web"
Andrew Plotkin, 1998 год /перевод Всеволода Зубарева, 2009 г./</a></b>
(151 Кбайт) </P>
"""


class RilarhivProviderTest(ProviderTestBase):
    qsp_url = "http://rilarhiv.ru/qsp.htm#qsp%2FBattle.rar"

    def test_canonicalize_archive_row(self):
        info = RilarhivProvider().canonicalize(RILARHIV_QSP_HTML, self.qsp_url)

        self.assertEqual(info.name, "Битва колдунов")
        self.assertEqual(self._person_names(info, "author"), ["Lostas 21"])
        self.assertIn("QSP", self._tag_texts(info))
        self.assertIn("download_direct", self._url_cats(info))
        self.assertEqual(
            [u.url for u in info.urls],
            ["http://rilarhiv.ru/qsp/Battle.rar"],
        )
        self.assert_round_trips(info)

    def test_canonicalize_row_with_release_date(self):
        info = RilarhivProvider().canonicalize(
            RILARHIV_SPECTRUM_HTML,
            "http://rilarhiv.ru/spectrum.htm#spectrum%2FAPOLLO.rar",
        )

        self.assertEqual(info.name, "APOLLO")
        self.assertEqual(info.date, "1996")
        self.assertEqual(self._person_names(info, "author"), ["Jokersoft"])
        self.assertIn("ZX Spectrum", self._tag_texts(info))
        self.assertIn("download_direct", self._url_cats(info))
        self.assertEqual(
            [u.url for u in info.urls],
            ["http://rilarhiv.ru/spectrum/APOLLO.rar"],
        )
        self.assert_round_trips(info)
        canonical = info.to_canonical()
        self.assertIn('- release_date: "1996"\n', canonical)
        self.assertNotIn(
            "1996", [p.name for p in info.personalities.get("author", [])]
        )

    def test_canonicalize_row_ignores_translation_date(self):
        info = RilarhivProvider().canonicalize(
            RILARHIV_TRANSLATION_HTML,
            "http://rilarhiv.ru/rinform.htm#rinform%2FTangleR.rar",
        )

        self.assertEqual(info.name, "Spider And Web")
        self.assertEqual(info.date, "1998")
        self.assertEqual(
            self._person_names(info, "author"), ["Andrew Plotkin"]
        )
        self.assertIn("Rinform", self._tag_texts(info))
        self.assertEqual(
            [u.url for u in info.urls],
            ["http://rilarhiv.ru/rinform/TangleR.rar"],
        )
        self.assert_round_trips(info)
        canonical = info.to_canonical()
        self.assertIn('- release_date: "1998"\n', canonical)
        self.assertNotIn("2009", canonical)

    def test_canonicalize_includes_secondary_online_link(self):
        info = RilarhivProvider().canonicalize(
            RILARHIV_ONLINE_HTML,
            "http://rilarhiv.ru/vneplatform.htm#vneplatform%2FVoprosi.zip",
        )

        self.assertEqual(info.name, "Вопросы")
        self.assertIn("download_direct", self._url_cats(info))
        self.assertIn("play_online", self._url_cats(info))
        self.assertEqual(
            [u.url for u in info.urls],
            [
                "http://rilarhiv.ru/vneplatform/Voprosi.zip",
                "https://writer.inklestudios.com/stories/rhcb",
            ],
        )
        self.assert_round_trips(info)

    def test_canonicalize_external_first_link_with_own_fragment(self):
        info = RilarhivProvider().canonicalize(
            RILARHIV_EXTERNAL_HTML,
            "http://rilarhiv.ru/urq.htm#"
            "http%3A%2F%2Fnarmiel.github.io%2FUrqW%2F%23support",
        )

        self.assertEqual(info.name, "Драконий остров")
        self.assertIn("URQ", self._tag_texts(info))
        self.assertEqual(
            [u.url for u in info.urls],
            ["http://narmiel.github.io/UrqW/#support"],
        )
        self.assert_round_trips(info)

    def test_discover_uses_page_fragment_identity(self):
        listings = {
            "http://rilarhiv.ru/qsp.htm": RILARHIV_QSP_HTML,
            "http://rilarhiv.ru/urq.htm": RILARHIV_EXTERNAL_HTML,
        }

        with (
            patch(
                "curation.providers.RILARHIV_LISTINGS",
                {"qsp": "QSP", "urq": "URQ"},
            ),
            patch(
                "curation.providers.FetchRilarhivListing",
                side_effect=lambda url, use_cache: listings[url],
            ),
        ):
            urls = [source.url for source in RilarhivProvider().discover()]

        self.assertEqual(
            urls,
            [
                "http://rilarhiv.ru/qsp.htm#qsp%2FBattle.rar",
                "http://rilarhiv.ru/urq.htm#"
                "http%3A%2F%2Fnarmiel.github.io%2FUrqW%2F%23support",
            ],
        )

    def test_discover_ignores_sidebar_navigation_links(self):
        html = """
        <div id="bl-left"><p><b><a href="qsp.htm">QSP</a></b></p></div>
        <div id="bl-right">
        <P><b><a href="spectrum/game.zip">"ZX Game" Alice</a></b></P>
        </div>
        """

        with (
            patch(
                "curation.providers.RILARHIV_LISTINGS",
                {"spectrum": "ZX Spectrum"},
            ),
            patch(
                "curation.providers.FetchRilarhivListing",
                return_value=html,
            ),
        ):
            urls = [source.url for source in RilarhivProvider().discover()]

        self.assertEqual(
            urls,
            ["http://rilarhiv.ru/spectrum.htm#spectrum%2Fgame.zip"],
        )

    def test_source_key_matches_direct_archive_url(self):
        provider = RilarhivProvider()

        self.assertEqual(
            provider.source_key("http://rilarhiv.ru/qsp/Battle.rar"),
            provider.source_key(self.qsp_url),
        )


AXMA_HTML = (
    "<article>"
    "<h5>Игра<span class='version'>v1</span>"
    "<span class='author'>Автор: Автор</span></h5>"
    "<div class='pubinfo small' style='float:left;'>Параграфов:&nbsp;10.</div>"
    "<div class='small' style='float:right;'>01.02.20</div>"
    "<div style='clear:both;'><img class='coverlib' src='/lib/ABC/cover.jpg'>"
    "</div>"
    "<div class='pubbuttons small'>"
    "<a href='https://lib.axmajs.ru/ABC/'>Запустить</a>"
    "<a nohr='/include/download_zip.php?id=100'>Скачать</a>"
    "</div>"
    "<div style='clear:both;'></div>ru"
    "<div style='margin-top:1em;' class='small'>"
    "<a href='?tag=1'>Фантастика</a></div>"
    "<div class='subtitle'>Описание игры.</div>"
    "</article>"
)


class AxmaProviderTest(ProviderTestBase):
    url = "https://axmajs.ru/library/?id=100"

    def test_owns(self):
        provider = AxmaProvider()
        self.assertTrue(provider.owns(self.url))
        self.assertFalse(provider.owns("https://axmajs.ru/library/"))
        self.assertFalse(provider.owns("https://example.com/"))

    def test_canonicalize(self):
        info = AxmaProvider().canonicalize(AXMA_HTML, self.url)
        self.assertEqual(info.name, "Игра")
        self.assertEqual(info.date, "2020-02-01")
        self.assertIn("Описание игры.", info.description)
        self.assertEqual(self._person_names(info, "author"), ["Автор"])
        self.assertIn("AXMA Story Maker JS", self._tag_texts(info))
        self.assertIn("фантастика", self._tag_texts(info))
        self.assertIn("v1", self._tag_texts(info))
        self.assertEqual(
            self._url_cats(info),
            {"game_page", "poster", "play_online", "download_direct"},
        )
        self.assert_round_trips(info)

    def test_discover(self):
        with patch(
            "curation.providers._axma_candidates",
            return_value=["https://axmajs.ru/library/?id=100"],
        ):
            discovered = list(AxmaProvider().discover())
            self.assertEqual(len(discovered), 1)
            self.assertEqual(
                discovered[0].url, "https://axmajs.ru/library/?id=100"
            )


HYPERBOOK_HTML = (
    "<a href='preview.php?id=123'><h1 title='запустить'>Игра&nbsp;"
    "<span class='small' style='color:#999999'>v1</span>&nbsp;"
    "<span class='accent'>→</span></h1></a>"
    "<div style='float: left; width: 50%; "
    "margin-bottom:14px; text-align: left;'>"
    "Автор: Автор Редактор: Редактор Художник: Иллюстратор"
    "</div>"
    "<div style='clear:both;'></div>"
    "<div style='float: left; width: 80%; color:#999999;' class='small'>"
    "Параграфов: 25. Размер: <nobr>100 Кб</nobr>. /2.0/</div>"
    "<div style='float: left; width: 20%; text-align:right;' class='small'>"
    "01.02.20</div>"
    "<div style='clear:both; text-align:right;' class='small'>"
    "<a href='file123'><span class='accent'>запустить</span></a> / "
    "<a href='download.php?id=123' target='_blank'>скачать</a>"
    "</div>"
    "<div class='small'>Описание игры.</div>"
    "<div class='sortsel'><a href='lib.php?sort=genre1'>Фантастика</a></div>"
    "<p class='small'><span class='accentsmall'>Награды</span><br>"
    "<img src='medal31-24.png'>Лучшая игра 2020<br></p>"
    "<h3 style='margin-top:2em;'>Комментарии: 5.</h3>"
)


class HyperbookProviderTest(ProviderTestBase):
    url = "https://hyperbook.ru/comments.php?id=123"

    def test_owns(self):
        provider = HyperbookProvider()
        self.assertTrue(provider.owns(self.url))
        self.assertFalse(provider.owns("https://hyperbook.ru/lib.php"))
        self.assertFalse(provider.owns("https://example.com/"))

    def test_canonicalize(self):
        info = HyperbookProvider().canonicalize(HYPERBOOK_HTML, self.url)
        self.assertEqual(info.name, "Игра")
        self.assertEqual(info.date, "2020-02-01")
        self.assertIn("Описание игры.", info.description)
        self.assertIn("Лучшая игра 2020", info.description)
        self.assertEqual(self._person_names(info, "author"), ["Автор"])
        self.assertEqual(self._person_names(info, "member"), ["Редактор"])
        self.assertEqual(self._person_names(info, "artist"), ["Иллюстратор"])
        self.assertIn("AXMA Story Maker", self._tag_texts(info))
        self.assertIn("фантастика", self._tag_texts(info))
        self.assertIn("v1", self._tag_texts(info))
        self.assertEqual(
            self._url_cats(info),
            {"game_page", "play_online", "download_direct"},
        )
        self.assertEqual([a.name for a in info.attributions], ["hyperbook.ru"])
        self.assert_round_trips(info)

    def test_discover(self):
        with patch(
            "curation.providers._hyperbook_candidates",
            return_value=["https://hyperbook.ru/comments.php?id=123"],
        ):
            discovered = list(HyperbookProvider().discover())
            self.assertEqual(len(discovered), 1)
            self.assertEqual(
                discovered[0].url, "https://hyperbook.ru/comments.php?id=123"
            )

    def test_candidates_filter(self):
        mock_html = (
            "<h3><a href='file1'>Игра 1</a></h3>"
            "<div class='small'><img src='medal31-24.png'></div>"
            "<div>Параграфов: 5.</div><div>комментарии (0)</div>"
            "<h3><a href='file2'>Игра 2</a></h3>"
            "<div><span style='color:#999999'>*****</span></div>"
            "<div>Параграфов: 5.</div><div>комментарии (0)</div>"
            "<h3><a href='file3'>Игра 3</a></h3>"
            "<div><span style='color:#999999'></span></div>"
            "<div>Параграфов: 20.</div><div>комментарии (2)</div>"
            "<h3><a href='file4'>Игра 4</a></h3>"
            "<div>Параграфов: 20.</div><div>комментарии (1)</div>"
            "<h3><a href='file5'>Игра 5</a></h3>"
            "<div>Параграфов: 15.</div><div>комментарии (5)</div>"
        )
        with patch(
            "curation.providers.FetchUrlToString",
            side_effect=[mock_html, ""],
        ):
            from curation.providers import _hyperbook_candidates

            candidates = list(_hyperbook_candidates())
            self.assertEqual(
                candidates,
                [
                    "https://hyperbook.ru/comments.php?id=1",
                    "https://hyperbook.ru/comments.php?id=2",
                    "https://hyperbook.ru/comments.php?id=3",
                ],
            )


class OwnsRoutingTest(ProviderTestBase):
    def test_each_provider_claims_only_its_urls(self):
        cases = [
            (AperoProvider(), AperoProviderTest.url),
            (IfwikiProvider(), IfwikiProviderTest.url),
            (InsteadGamesProvider(), InsteadGamesProviderTest.url),
            (QuestBookProvider(), QuestBookProviderTest.url),
            (IfictionProvider(), IfictionProviderTest.url),
            (QspSuProvider(), QspSuProviderTest.url),
            (PlutProvider(), PlutProviderTest.url),
            (RilarhivProvider(), RilarhivProviderTest.qsp_url),
            (AxmaProvider(), AxmaProviderTest.url),
            (HyperbookProvider(), HyperbookProviderTest.url),
        ]
        for provider, url in cases:
            with self.subTest(provider=type(provider).__name__):
                self.assertTrue(provider.owns(url))
                for other, _ in cases:
                    if type(other) is not type(provider):
                        self.assertFalse(other.owns(url))

    def test_provider_fetches_bypass_crawler_file_cache(self):
        cases = [
            (AperoProvider(), "FetchApero", AperoProviderTest.url, None),
            (IfwikiProvider(), "FetchIfwikiRaw", IfwikiProviderTest.url, None),
            (
                InsteadGamesProvider(),
                "FetchInstead",
                InsteadGamesProviderTest.url,
                None,
            ),
            (
                QuestBookProvider(),
                "FetchQuestBook",
                QuestBookProviderTest.url,
                None,
            ),
            (
                IfictionProvider(),
                "FetchIfiction",
                IfictionProviderTest.url,
                None,
            ),
            (QspSuProvider(), "FetchQspApi", QspSuProviderTest.url, None),
            (PlutProvider(), "FetchPlut", PlutProviderTest.url, None),
            (
                RilarhivProvider(),
                "FetchRilarhivListing",
                RilarhivProviderTest.qsp_url,
                "http://rilarhiv.ru/qsp.htm",
            ),
            (AxmaProvider(), "FetchUrlToString", AxmaProviderTest.url, None),
            (
                HyperbookProvider(),
                "FetchUrlToString",
                HyperbookProviderTest.url,
                None,
            ),
        ]

        for provider, fetch_name, url, expected_url in cases:
            with self.subTest(provider=type(provider).__name__):
                with patch(
                    f"curation.providers.{fetch_name}", return_value="raw"
                ) as fetch:
                    self.assertEqual(provider.fetch(url), "raw")
                    fetch.assert_called_once_with(
                        expected_url or url, use_cache=False
                    )
