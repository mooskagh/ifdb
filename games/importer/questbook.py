import re
from logging import getLogger
from html import unescape
from core.crawler import FetchUrlToString
from html2text import HTML2Text
from .tools import CategorizeUrl
from urllib.parse import urljoin
import datetime

logger = getLogger('crawler')

QUESTBOOK_GAMEDETAIL_URL = re.compile(r'https?://quest-book.ru/online/view/.*')


class QuestBookImporter:
    def MatchWithCat(self, url, cat):
        return cat == 'game_page' and self.Match(url)

    def Match(self, url):
        return QUESTBOOK_GAMEDETAIL_URL.match(url)

    def MatchAuthor(self, url):
        return False

    def GetUrlCandidates(self):
        return GetCandidates()

    def Import(self, url):
        return ImportFromQuestBook(url)

    def GetDirtyUrls(self):
        return []


QUESTBOOK_LISTING_RE = re.compile(
    r'<a [^>]*href="(view/[^"]+)"[^>]*>')  # [^\n]*Подробнее</a>


def GetCandidates():
    page = 1
    res = []
    while True:
        r = FetchUrlToString(
            'https://quest-book.ru/online/?s=%d' % page, use_cache=False)

        found = False

        for m in QUESTBOOK_LISTING_RE.finditer(r):
            res.append('https://quest-book.ru/online/%s' % m.group(1))
            found = True

        if not found:
            break

        page += 10
    return res


QUESTBOOK_TITLE = re.compile(r'<h2 class="mt-1">([^<]+)</h2>')
QUESTBOOK_SHORTDESC = re.compile(
    r'<td class="text-left">Краткое описание</td>\s*'
    r'<td class="text-left">([^<]+)</td>')
QUESTBOOK_FIRSTPOST = re.compile(
    r'(?s)<div class="card-body">(.*?)<!--MESSAGE-BODY-END-->')
QUESTBOOK_POSTBODY = re.compile(r'(?s)<div class="postbody">(.*?)</div')
QUESTBOOK_TIME = re.compile(r'<i class="fal fa-clock"></i> <small>'
                            r'.. (...) (\d{2}), (\d{4}) \d{2}:\d{2}</small>')
QUESTBOOK_AUTHOR_BOX = re.compile(
    r'(?s)<td class="text-left" style="width: 35%">Автор</td>(.*?)</td>')
QUESTBOOK_AUTHOR_NAME = re.compile(r'>\s*([^<]+)</a>')
QUESTBOOK_AUTHOR_URL = re.compile(
    r'<a href="([^"]+)">все сторигеймы автора</a>')

QUESTBOOK_TAG_BOX = re.compile(
    r'(?s)<td class="text-left">Категории</td>(.*?)</td>')
QUESTBOOK_TAG_ITEM = re.compile(r'>([^>]+)</a>')

QUESTBOOK_IMAGE = re.compile(r'<meta property="og:image" content="([^"]+)">')
QUESTBOOK_LINK = re.compile(r'<a class="btn [^>]+ href="([^"]+)".*ать</a>')

MONTH = [
    'Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт',
    'Ноя', 'Дек'
]


def ImportFromQuestBook(url):
    try:
        html = FetchUrlToString(url, encoding='cp1251')
    except Exception:
        return {'error': 'Не открывается что-то этот URL.'}

    res = {'priority': 51, 'authors': []}
    tags = [{'cat_slug': 'platform', 'tag': 'Questbook'}]
    urls = [{
        'urlcat_slug': 'game_page',
        'description': 'Страница на квестбуке',
        'url': url,
    }]

    m = QUESTBOOK_TITLE.search(html)
    if not m:
        return {'error': 'Не найдена игра на странице'}
    res['title'] = unescape(m.group(1))

    desc = ''
    m = QUESTBOOK_SHORTDESC.search(html)
    if m:
        desc += unescape(m.group(1))

    m = QUESTBOOK_FIRSTPOST.search(html)
    if m:
        m2 = QUESTBOOK_POSTBODY.search(m.group(1))
        if m2:
            if desc:
                desc += '\n\n'
            tt = HTML2Text()
            tt.body_width = 0
            desc += tt.handle(m2.group(1))
        m2 = QUESTBOOK_TIME.search(m.group(1))
        if m2:
            res['release_date'] = datetime.datetime(
                year=int(m2.group(3)),
                month=MONTH.index(m2.group(1)) + 1,
                day=int(m2.group(2))).date()

    if desc:
        res['desc'] = desc + '\n\n_(описание взято с сайта quest-book.ru)_'

    m = QUESTBOOK_AUTHOR_BOX.search(html)
    if m:
        m2 = QUESTBOOK_AUTHOR_NAME.search(m.group(1))
        m3 = QUESTBOOK_AUTHOR_URL.search(m.group(1))
        res['authors'].append({
            'role_slug': 'author',
            'name': unescape(m2.group(1)),
            'url': urljoin(url, m3.group(1)),
            'urldesc': 'Страница автора на quest-book.ru',
        })

    m = QUESTBOOK_TAG_BOX.search(html)
    if m:
        for m2 in QUESTBOOK_TAG_ITEM.finditer(m.group(1)):
            tags.append({'cat_slug': 'tag', 'tag': unescape(m2.group(1))})
    res['tags'] = tags

    m = QUESTBOOK_IMAGE.search(html)
    if m:
        urls.append(CategorizeUrl(m.group(1), 'Обложка', 'poster', base=url))

    for m in QUESTBOOK_LINK.finditer(html):
        urls.append(CategorizeUrl(m.group(1), base=url))

    res['urls'] = urls

    return res
