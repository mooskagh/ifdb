import re
from urllib.parse import quote, urljoin, urlparse, urlsplit, urlunsplit

from .enrichment import enricher

RE_WORD = re.compile(r"\w+")
MIN_SIMILARITY = 0.67
REGISTERED_IMPORTERS = []

URL_CATEGORIZER_RULES = [  # hostname, path, query, slug, desc
    ("qsp.su", "^/?$", "^$", None, None),
    ("urq.plut.info", "^/?$", "^$", None, None),
    ("rilarhiv.ru", "^/?$", "^$", None, None),
    ("ifwiki.ru", "^/?$", "^$", None, None),
    ("www.youtube.com", "^/?$", "^$", None, None),
    ("youtube.com", "^/?$", "^$", None, None),
    ("youtu.be", "^/?$", "^$", None, None),
    ("apero.ru", "^/?$", "^$", None, None),
    ("storymaze.ru", "^/?$", "^$", None, None),
    (
        "",
        r"(?i).*screenshot.*\.(png|jpg|gif|bmp|jpeg)",
        "",
        "screenshot",
        "Скриншот",
    ),
    ("", r"(?i).*\.(png|jpg|gif|bmp|jpeg)", "", "poster", "Обложка"),
    ("db.crem.xyz", "/f/uploads/.*", "", "download_direct", "Скачать"),
    (
        "ifiction.ru",
        "/game.php",
        "",
        "download_landing",
        "Скачать с ifiction.ru",
    ),
    ("ifwiki.ru", "/files/.*", "", "download_direct", "Скачать с IfWiki"),
    ("ifwiki.ru", "", "", "game_page", "Страница на IfWiki"),
    ("ifwiki.org", "", "", "game_page", "Страница на ifwiki.org"),
    ("ludumdare.com", "", "", "game_page", "Страница на Ludum Dare"),
    ("urq.plut.info", ".*/files/.*", "", "download_direct", "Скачать с плута"),
    (
        "plut.info",
        "/urq/.*/files/.*",
        "",
        "download_direct",
        "Скачать с плута",
    ),
    ("urq.plut.info", "", "", "game_page", "Страница на плуте"),
    ("plut.info", "/urq/.*", "", "game_page", "Страница на плуте"),
    ("store.steampowered.com", "", "", "game_page", "Страница на стиме"),
    ("yadi.sk", "", "", "download_landing", "Скачать с Яндекс.диска"),
    ("rilarhiv.ru", "", "", "download_direct", "Скачать с РилАрхива"),
    (
        "instead-games.ru",
        ".*/download/.*",
        "",
        "download_direct",
        "Скачать с инстеда",
    ),
    (
        "quest-book.ru",
        "/online/view/.*",
        "",
        "game_page",
        "Страница на квестбуке",
    ),
    (
        "quest-book.ru",
        "/online/mitril/download/.*/pdf/",
        "",
        "download_direct",
        "PDF версия",
    ),
    (
        "quest-book.ru",
        "/online/[^/]+/",
        "",
        "play_online",
        "Играть на квестбуке",
    ),
    ("instead-games.ru", "/instead-em/.*", "", "play_online", "Играть онлайн"),
    ("instead-games.ru", "/forum/.*", "", "forum", "Форум на инстеде"),
    ("instead-games.ru", "", "", "game_page", "Страница на инстеде"),
    ("instead.syscall.ru", ".*/forum/.*", "", "forum", "Форум на инстеде"),
    ("youtube.com", "", "", "video", "Видео игры"),
    ("youtu.be", "", "", "video", "Видео игры"),
    ("www.youtube.com", "", "", "video", "Видео игры"),
    (
        "forum.ifiction.ru",
        "/file.php",
        "",
        "download_direct",
        "Скачать с ifiction.ru",
    ),
    ("forum.ifiction.ru", "", "", "forum", "Обсуждение на форуме"),
    ("urq.borda.ru", "", "", "forum", "Обсуждение на форуме"),
    ("ifhub.club", "", "", "review", "Обзор на ifhub.club"),
    ("qsp.su", "", ".*=dd_download.*", "download_direct", "Скачать с qsp.ru"),
    ("qsp.su", "/tools/aero/.*", "", "play_online", "Играть онлайн на qsp.ru"),
    ("qsp.su", "", "", "game_page", "Игра на qsp.ru"),
    (r"@.*\.github\.io", "", "", "play_online", "Играть онлайн"),
    ("iplayif.com", "", "", "play_online", "Играть онлайн"),
    ("apero.ru", "", "", "play_online", "Играть онлайн"),
    ("storymaze.ru", "", "", "play_online", "Играть онлайн"),
    (
        "hyperbook.ru",
        "/download.php",
        "",
        "download_direct",
        "Скачать с hyperbook.ru",
    ),
    (
        "",
        r"(?i).*\.(zip|rar|z5)",
        "",
        "download_direct",
        "Ссылка для скачивания",
    ),
]


def QuoteUtf8(s):
    if s is str:
        s = s.encode("utf-8")
    return quote(s, safe="/+=&?%:@;!#$*()_-")


def GetBagOfWords(x):
    return set(RE_WORD.findall(x.lower().replace("ё", "е")))


def ComputeSimilarity(s1, s2):
    if not s1:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def CategorizeUrl(url, desc="", category=None, base=None):
    if desc == url:
        desc = ""
    if base:
        url = urljoin(base, url)
    purl = urlparse(url)
    cat_slug = "unknown"

    for host, path, query, slug, ddesc in URL_CATEGORIZER_RULES:
        if host:
            if host.startswith("@"):
                if not purl.hostname or not re.match(host[1:], purl.hostname):
                    continue
            elif host != purl.hostname:
                continue
        if path and not re.match(path, purl.path):
            continue
        if query and not re.match(query, purl.query):
            continue
        cat_slug = slug
        if not desc:
            desc = ddesc
        break

    if cat_slug == "unknown":
        if desc.lower() == "играть онлайн":
            cat_slug = "play_online"
        elif "скачать" in desc.lower():
            cat_slug = "download_landing"

    if not desc:
        desc = url

    if category:
        cat_slug = category

    return {"urlcat_slug": cat_slug, "description": desc, "url": url}


AUTHOR_URL_CATEGORIZER_RULES = [  # hostname, path, query, slug, desc
    ("apero.ru", "^/?$", "^$", None, None),
    ("forum.ifiction.ru", "^/?$", "^$", None, None),
    ("ifhub.club", "^/?$", "^$", None, None),
    ("ifiction.ru", "^/?$", "^$", None, None),
    ("ifwiki.ru", "^/?$", "^$", None, None),
    ("kril.ifiction.ru", "", "", None, None),
    ("plut.info", "^/?$", "^$", None, None),
    ("qsp.su", "^/?$", "^$", None, None),
    ("rilarhiv.ru", "^/?$", "^$", None, None),
    ("storymaze.ru", "^/?$", "^$", None, None),
    ("urq.plut.info", "^/?$", "^$", None, None),
    ("www.youtube.com", "^/?$", "^$", None, None),
    ("youtu.be", "^/?$", "^$", None, None),
    ("youtube.com", "^/?$", "^$", None, None),
    ("", r".*\.(png|jpg|gif|bmp|jpeg)", "", "avatar", "Изображение"),
    ("ifwiki.ru", "", "", "other_site", "Страница на IfWiki"),
    (
        "apero.ru",
        ".*/%D0%A3%D1%87%D0%B0%D1%81%D1%82%D0%BD%D0%B8%D0%BA%D0%B8/",
        "",
        "other_site",
        "Страница на Аперо",
    ),
    ("twitter.com", "", "", "social", "Страница в Твиттере"),
    (r"@.+\.ifiction\.ru", "^/?$", "", "personal_page", "Блог на ifiction.ru"),
    ("vk.com", "", "", "social", "Страница вКонтакте"),
]


def CategorizeAuthorUrl(url, desc="", category=None, base=None):
    if base:
        url = urljoin(base, url)
    purl = urlparse(url)
    cat_slug = "other"

    for host, path, query, slug, ddesc in AUTHOR_URL_CATEGORIZER_RULES:
        if host:
            if host.startswith("@"):
                if purl.hostname and not re.match(host[1:], purl.hostname):
                    continue
            elif host != purl.hostname:
                continue
        if path and not re.match(path, purl.path):
            continue
        if query and not re.match(query, purl.query):
            continue
        cat_slug = slug
        if not desc:
            desc = ddesc
        break

    if cat_slug == "other":
        if desc.lower() == "интервью":
            cat_slug = "interview"
        elif "сайт" in desc.lower():
            cat_slug = "personal_page"
        elif "блог" in desc.lower():
            cat_slug = "personal_page"
    if not desc:
        desc = url

    if category:
        cat_slug = category

    return {"urlcat_slug": cat_slug, "description": desc, "url": url}


def SimilarEnough(w1, w2):
    s1 = GetBagOfWords(w1)
    s2 = GetBagOfWords(w2)
    return ComputeSimilarity(s1, s2) > MIN_SIMILARITY


def HashizeUrl(url):
    url = QuoteUtf8(url)
    purl = urlsplit(url, allow_fragments=False)
    return urlunsplit(("", purl[1], purl[2], purl[3], ""))


class Importer:
    def __init__(self):
        self.importers = [x() for x in REGISTERED_IMPORTERS]

    def IsFamiliarUrl(self, url, cat):
        for x in self.importers:
            if x.MatchWithCat(url, cat):
                return True
        return False

    def DispatchImport(self, url):
        for x in self.importers:
            if x.Match(url):
                return x.Import(url)

        return {"error": "Ссылка на неизвестный ресурс."}

    def GetUrlCandidates(self):
        res = []
        for x in self.importers:
            res.extend(x.GetUrlCandidates())
        return res

    def GetDirtyUrls(self):
        res = []
        for x in self.importers:
            res.extend(x.GetDirtyUrls())
        return res

    def ImportAuthor(self, url):
        for x in self.importers:
            if x.MatchAuthor(url):
                return x.ImportAuthor(url)
        return {"error": "Ссылка на неизвестный ресурс."}

    def Import(self, *seed_url):
        url_errors = dict()
        urls_checked = set()
        urls_to_check = set(seed_url)
        res = []
        title = None

        s_urls = set()
        s_tags = set()
        s_auth = set()

        def MergeImport(y, x):
            for z in ["title", "release_date", "error"]:
                if z not in y and z in x:
                    y[z] = x[z]

            if "desc" in x:
                if "desc" in y:
                    y["desc"] += "\n\n---\n\n"
                else:
                    y["desc"] = ""
                y["desc"] += x["desc"]

            if "urls" in x:
                x["urls"] = [z for z in x["urls"] if z["urlcat_slug"]]

            for setz, field, extractor in [
                (
                    s_urls,
                    "urls",
                    lambda xx: (HashizeUrl(xx["url"]), xx["urlcat_slug"]),
                ),
                (
                    s_tags,
                    "tags",
                    lambda xx: (
                        xx.get("tag_slug"),
                        xx.get("tag"),
                        xx.get("cat_slug"),
                    ),
                ),
                (
                    s_auth,
                    "authors",
                    lambda v: (
                        v.get("role_slug"),
                        v.get("role_slug"),
                        v.get("name"),
                    ),
                ),
            ]:
                if field in x:
                    if field not in y:
                        y[field] = []
                    for z in x[field]:
                        if extractor(z) in setz:
                            continue
                        setz.add(extractor(z))
                        y[field].append(z)

        while urls_to_check:
            url = urls_to_check.pop()
            url_hash = HashizeUrl(url)
            if url_hash in urls_checked:
                continue
            urls_checked.add(url_hash)

            r = self.DispatchImport(url)

            if "error" in r:
                url_errors[url] = r["error"]

            if "priority" not in r:
                r["priority"] = -1000

            append = False
            if "title" in r:
                if title and url not in seed_url:
                    if SimilarEnough(title, r["title"]):
                        append = True
                else:
                    title = r["title"]
                    append = True
            elif not title:
                append = True

            if append:
                res.append(r)
                if "urls" in r:
                    for x in r["urls"]:
                        if self.IsFamiliarUrl(x["url"], x["urlcat_slug"]):
                            urls_to_check.add(x["url"])

        res.sort(key=lambda x: x["priority"], reverse=True)

        r = {}
        for x in res:
            MergeImport(r, x)
        if "title" in r and "error" in r:
            del r["error"]

        enricher.Enrich(r)
        return (r, url_errors)


# Schema:
# title: title
# desc: description, markdown-formatted
# release_date: release-date
# authors[]:
#   role_slug:
#   role: ...         (either role_slug or role is defined)
#   name: ...
# tags[]:
#   tag_slug  (doesn't need anything else
#   cat_slug
#   tag
# urls[]:
#   urlcat_slug
#   description
#   url
#
# Role slugs:
#   artist, author
# Tag slug:
#   in_dev, beta, released, demo
# Cat slug:
#   genre
#   platform
#   country
# Url slug:
#   game_page (ifwiki)
#   download_direct
#   download_landing
#   unknown
