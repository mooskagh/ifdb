import re
from core.crawler import FetchUrlToString
from urllib.parse import quote, unquote
from html import unescape
from .tools import CategorizeUrl, CategorizeAuthorUrl, QuoteUtf8
from html2text import HTML2Text
import datetime


class AperoImporter:
    def MatchWithCat(self, url, cat):
        return cat == 'play_online' and self.Match(url)

    def Match(self, url):
        return APERO_URL.match(QuoteUtf8(url))

    def MatchAuthor(self, url):
        return APERO_AUTHOR_URL.match(url)

    def Import(self, url):
        return ImportFromApero(url)

    def ImportAuthor(self, url):
        return ImportAuthorFromApero(url)

    def GetUrlCandidates(self):
        return FetchCandidateUrls()

    def GetDirtyUrls(self):
        return []


APERO_URL = re.compile(
    r'https?://apero\.ru/' + quote('Текстовые-игры') + r'/.*')
APERO_AUTHOR_URL = re.compile(
    r'https?://apero\.ru/' + quote('Участники') + r'/(.*)')
APERO_LISTING_TITLE_RE = re.compile(
    r'<h2><a href="(http://apero.ru/Текстовые-игры/[^"]+)">[^<]*</a></h2>')


def FetchCandidateUrls():
    html = FetchUrlToString(
        r'http://apero.ru/' + quote('Текстовые-игры'), use_cache=False)
    return [
        QuoteUtf8(m.group(1)) for m in APERO_LISTING_TITLE_RE.finditer(html)
    ]


APERO_TITLE = re.compile(
    r'<dd itemprop="name"><div title="[^"]*">([^<]+)</div></dd>')
APERO_RELEASE = re.compile(
    r'<meta itemprop="datePublished" content="([^"]+)">')
APERO_AUTHOR = re.compile(r'<a itemprop="author" href="[^"]*">([^<]+)</a>')
APERO_DESC = re.compile(r'<dt>Описание:</dt>\s*<dd><div>(.*?)</div>',
                        re.DOTALL)
APERO_IMAGE = re.compile(r'<img src="([^"]+)" [^>]* itemprop="image" />')


def ImportFromApero(url):
    try:
        html = FetchUrlToString(url)
    except Exception as e:
        return {'error': 'Не открывается что-то этот URL.'}

    res = {'priority': 49}
    m = APERO_TITLE.search(html)
    if not m:
        return {'error': 'Не найдена игра на странице'}
    res['title'] = unescape(m.group(1))

    m = APERO_DESC.search(html)
    if m:
        tt = HTML2Text()
        tt.body_width = 0
        res['desc'] = (
            tt.handle(m.group(1)) + '\n\n_(описание взято с сайта apero.ru)_')

    m = APERO_RELEASE.search(html)
    if m:
        res['release_date'] = datetime.datetime.strptime(
            m.group(1), "%Y-%m-%d").date()

    res['urls'] = [CategorizeUrl(url, '')]
    authors = []
    for m in APERO_AUTHOR.finditer(html):
        name = unescape(m.group(1))
        authors.append({
            'role_slug': ('author'),
            'name': (name),
            'url':
            ('http://apero.ru/' + quote('Участники') + '/%s' % quote(name)),
            'urldesc': ('Страница автора на apero.ru'),
        })
    res['authors'] = authors
    res['tags'] = [{'cat_slug': 'platform', 'tag': 'Аперо'}]

    m = APERO_IMAGE.search(html)
    if m:
        if m.group(1) != 'http://apero.ru/public/img/games/game.png':
            res['urls'].append(CategorizeUrl(m.group(1)))

    return res


APERO_AUTHOR_BIO = re.compile(r'<dt>О себе:</dt><dd>(.*?)</dd>', re.DOTALL)
APERO_AUTHOR_AVATAR = re.compile(r'<img src="([^"]+)" class="img-circle" />')


def ImportAuthorFromApero(url):
    m = APERO_AUTHOR_URL.match(url)
    if not m:
        return {'error': 'Не похож URL на автора.'}
    try:
        html = FetchUrlToString(url)
    except Exception as e:
        return {'error': 'Не открывается что-то этот URL.'}

    res = {}
    res['name'] = unquote(m.group(1))
    m = APERO_AUTHOR_BIO.search(html)
    if m:
        tt = HTML2Text()
        tt.body_width = 0
        res['bio'] = (
            tt.handle(m.group(1)) + '\n\n_(описание взято с сайта apero.ru)_')

    res['urls'] = []
    res['urls'].append(CategorizeAuthorUrl(url))
    m = APERO_AUTHOR_AVATAR.search(html)
    if m:
        if m.group(1) != 'http://apero.ru/public/img/members/avatar.jpg':
            res['urls'].append(CategorizeAuthorUrl(m.group(1)))

    return res
