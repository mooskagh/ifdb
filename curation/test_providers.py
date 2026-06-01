from io import StringIO
from unittest.mock import patch
from urllib.parse import quote

from django.core.management import call_command
from django.test import TestCase

from .gameinfo import parse
from .providers import (
    AperoProvider,
    CanonicalAuthor,
    IfictionProvider,
    IfwikiProvider,
    InsteadGamesProvider,
    PlutProvider,
    QspSuProvider,
    QuestBookProvider,
)


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


QSP_HTML = """
<table class="sobi2Details">
<tr><h1>QSP игра</h1></tr>
<tr><span id="sobi2Details_field_author">Alice</span></tr>
<tr><span id="sobi2Details_field_description">Описание QSP.</span></tr>
</table>
<table class="sobi2DetailsFooter">Добавлено: 04.03.2021&nbsp;&nbsp;</table>
"""


class QspSuProviderTest(ProviderTestBase):
    url = "http://qsp.su/index.php?option=com_sobi2&Itemid=55&sobi2Id=123"

    def test_canonicalize(self):
        info = QspSuProvider().canonicalize(QSP_HTML, self.url)
        self.assertEqual(info.name, "QSP игра")
        self.assertEqual(info.date, "2021-03-04")
        self.assertEqual(self._person_names(info, "author"), ["Alice"])
        self.assertIn("QSP", self._tag_texts(info))
        self.assertIn("game_page", self._url_cats(info))
        self.assertEqual([a.name for a in info.attributions], ["qsp.su"])
        self.assert_round_trips(info)


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
        ]
        for provider, url in cases:
            with self.subTest(provider=type(provider).__name__):
                self.assertTrue(provider.owns(url))
                for other, _ in cases:
                    if type(other) is not type(provider):
                        self.assertFalse(other.owns(url))

    def test_provider_fetches_bypass_crawler_file_cache(self):
        cases = [
            (AperoProvider(), "FetchApero", AperoProviderTest.url),
            (IfwikiProvider(), "FetchIfwikiRaw", IfwikiProviderTest.url),
            (
                InsteadGamesProvider(),
                "FetchInstead",
                InsteadGamesProviderTest.url,
            ),
            (
                QuestBookProvider(),
                "FetchQuestBook",
                QuestBookProviderTest.url,
            ),
            (IfictionProvider(), "FetchIfiction", IfictionProviderTest.url),
            (QspSuProvider(), "FetchQsp", QspSuProviderTest.url),
            (PlutProvider(), "FetchPlut", PlutProviderTest.url),
        ]

        for provider, fetch_name, url in cases:
            with self.subTest(provider=type(provider).__name__):
                with patch(
                    f"curation.providers.{fetch_name}", return_value="raw"
                ) as fetch:
                    self.assertEqual(provider.fetch(url), "raw")
                    fetch.assert_called_once_with(url, use_cache=False)
