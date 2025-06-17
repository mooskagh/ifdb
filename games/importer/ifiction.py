import re
from html import unescape
from urllib.parse import urljoin

from html2text import HTML2Text

from core.crawler import FetchUrlToString

from .tools import CategorizeUrl

IFICTION_URL = re.compile(
    r"https?://forum\.ifiction\.ru/viewtopic\.php\?id=\d+"
)


class IfictionImporter:
    def MatchWithCat(self, url, cat):
        return cat == "game_page" and self.Match(url)

    def Match(self, url):
        return IFICTION_URL.match(url)

    def MatchAuthor(self, url):
        return False

    def Import(self, url):
        return ImportFromIfiction(url)

    def ImportAuthor(self, url):
        return False

    def GetUrlCandidates(self):
        return GetGameList()

    def GetDirtyUrls(self, age_minutes=60 * 14):
        return []


ROOT_URL = "http://forum.ifiction.ru/viewforum.php?id=36d"


def GetGameList():
    root_html = FetchUrlToString(ROOT_URL, use_cache=False)
    res = ParseGameList(root_html, ROOT_URL)
    # for url in ParseSublists(root_html, ROOT_URL):
    #     html = FetchUrlToString(url, use_cache=False)
    #     res.update(ParseGameList(html, url))
    return list(res)


# SUBLIST_RE = re.compile(r'href="(\./viewforum\.php\?id=36&list=\d+)"')

# def ParseSublists(html_text, base):
#     return [
#         urljoin(base, m.group(1)) for m in SUBLIST_RE.finditer(html_text)
#     ]

GAME_RE = re.compile(r'<a href="(\./viewtopic\.php\?id=\d+)">')


def ParseGameList(html_text, base):
    return set([
        urljoin(base, m.group(1)) for m in GAME_RE.finditer(html_text)
    ])


TITLE_RE = re.compile(
    r"<h1[^>]*>(?:<a [^>]+>)?<b><span[^>]*>([^<]+)"
    r"</span></b>(?:</a>)?</h1>"
)
DESC_RE = re.compile(
    r'(?s)<div align="justify" style="font-size:1.2em; margin-top:10px;">'
    "(.*?)</div>"
)
AUTHOR_BLOCK = re.compile(r'(?s)<div id="game_authors">(.*?)</div>')
LINKS_BLOCK = re.compile(
    r'(?s)<td valign="top" style="border:0; padding:0px 0 0 5px;">'
    "(.*?)</td>"
)

LINK_RE = re.compile(r'<a href="([^#][^"]*)"[^>]*>(?:<b>)([^<]+)(?:</b>)</a>')
POSTER_URL = re.compile(r'<img src="([^"]+)" style="max-width:320px;"')
SCREENSHOTS_BLOCK = re.compile(r'(?s)<div id="screenshots"[^>]*>(.*?)</div>')
IMG_URL = re.compile(r'<img src="([^"]+)"')


def ImportFromIfiction(url):
    try:
        html = FetchUrlToString(url, encoding="cp1251")
    except Exception:
        return {"error": "Не открывается что-то этот URL."}

    res = {
        "priority": 45,
        "authors": [],
        "tags": [],
        "urls": [
            {
                "urlcat_slug": "game_page",
                "description": "Страница на ifiction.ru",
                "url": url,
            }
        ],
    }
    m = TITLE_RE.search(html)
    if not m:
        return {"error": "Не найдена игра на странице"}
    res["title"] = unescape(m.group(1))

    m = AUTHOR_BLOCK.search(html)
    if not m:
        return {"error": "Не найдена игра на странице"}
    ParseAuthorBlock(m.group(1), res, url)

    m = DESC_RE.search(html)
    if m:
        tt = HTML2Text()
        tt.body_width = 0
        res["desc"] = (
            tt.handle(m.group(1))
            + "\n\n_(описание взято с сайта ifiction.ru)_"
        )

    m = LINKS_BLOCK.search(html)
    if m:
        for m in LINK_RE.finditer(m.group(1)):
            myurl = ResolveRedirect(m.group(1), url)
            desc = unescape(m.group(2))
            res["urls"].append(CategorizeUrl(myurl, desc, base=url))

    m = POSTER_URL.search(html)
    if m:
        myurl = ResolveRedirect(m.group(1), url)
        res["urls"].append({
            "urlcat_slug": "poster",
            "description": "Постер с ifiction.ru",
            "url": myurl,
        })

    m = SCREENSHOTS_BLOCK.search(html)
    if m:
        for m in IMG_URL.finditer(m.group(1)):
            myurl = ResolveRedirect(m.group(1), url)
            res["urls"].append({
                "urlcat_slug": "screenshot",
                "description": "Скриншот с ifiction.ru",
                "url": myurl,
            })

    return res


AUTHOR_LINK = re.compile(r'<a href="([^"]+)"[^>]*>([^<]+)</a>')
CATEGORY_FILTER = re.compile(r"&middot;|[:,]")


def ParseAuthorBlock(html, res, base_url):
    last_idx = 0
    category = ""
    for m in AUTHOR_LINK.finditer(html):
        cat = CATEGORY_FILTER.sub("", html[last_idx : m.start()]).strip()
        if cat:
            category = cat
        last_idx = m.end()
        url = urljoin(base_url, m.group(1))
        desc = unescape(m.group(2))
        if category in ["Автор", "Авторы"]:
            res["authors"].append({
                "role_slug": "author",
                "name": desc,
                "url": url,
                "urldesc": "Страница автора на forum.ifiction.ru",
            })
        elif category == "Платформа":
            res["tags"].append({
                "cat_slug": "platform",
                "tag": desc,
            })


REDIRECTOR_URL = re.compile(r"https?://forum\.ifiction\.ru/file\.php?.*")
REDIRECT_URL = re.compile(
    r'<meta http-equiv="refresh" content="(?:.*?)URL=([^"]+)"'
)


def ResolveRedirect(url, url_base):
    full_url = urljoin(url_base, url)
    if not REDIRECTOR_URL.match(full_url):
        return full_url
    html = FetchUrlToString(full_url, use_cache=False)
    m = REDIRECT_URL.search(html)
    if not m:
        return full_url
    return m.group(1)
