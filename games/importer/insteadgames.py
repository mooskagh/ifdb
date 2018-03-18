from .tools import CategorizeUrl
from core.crawler import FetchUrlToString
from html import unescape
from html2text import HTML2Text
from logging import getLogger
import datetime
import re
import xml.etree.ElementTree as ET

logger = getLogger('crawler')

INSTEAD_URL = re.compile(r'https?://instead-games\.ru/game\.php\?ID=\d+')


class InsteadGamesImporter:
    def MatchWithCat(self, url, cat):
        return cat == 'game_page' and self.Match(url)

    def Match(self, url):
        return INSTEAD_URL.match(url)

    def MatchAuthor(self, url):
        return False

    def GetUrlCandidates(self):
        return GetGameList()

    def GetDirtyUrls(self, age_minutes=60 * 14):
        return []

    def Import(self, url):
        return ImportFromInstead(url)


GAMELIST_XMLS = [
    'http://instead-games.ru/xml.php',
    'http://instead-games.ru/xml.php?approved=0',
]


def GetGameList():
    res = []
    for x in GAMELIST_XMLS:
        xml_text = FetchUrlToString(x, use_cache=False)
        xml = ET.fromstring(xml_text)
        for y in xml.findall('.//descurl'):
            res.append(''.join(y.itertext()))
    return res


INS_HEAD = re.compile('<h2>(.*?)</h2>')
INS_DESC = re.compile('<div class="gamedsc">(.*?)</div>', re.DOTALL)
INS_SCREENSHOTS = re.compile('<div id="screenshots">(.*?)</div>', re.DOTALL)
INS_SCREENSHOT = re.compile('<img class="border" src="([^"]+)"')
INS_PANEL = re.compile('<div id="panel">(.*?)</div>', re.DOTALL)
INS_AUTHOR = re.compile('<b>Автор</b>: ([^<]+)<br>')
INS_DATE = re.compile(r'<b>Дата</b>: (\d{4}\.\d{2}\.\d{2})<br>')
INS_LINK = re.compile(r'<a href="([^"]+)">([^<]+)</a>')

INS_PREFIX = 'instead-games.ru'

#CategorizeUrl(url, desc='', category=None, base=None):


def ImportFromInstead(url):
    try:
        html = FetchUrlToString(url)
    except:
        return {'error': 'Не открывается что-то этот URL.'}

    res = {'priority': 80}
    res['urls'] = [CategorizeUrl(url, '', base=url)]
    res['tags'] = [{'cat_slug': 'platform', 'tag': 'INSTEAD'}]
    res['authors'] = []

    m = INS_HEAD.search(html)
    if not m:
        return {'error': 'Не найдена игра на странице'}
    res['title'] = unescape(m.group(1))

    m = INS_DESC.search(html)
    if m:
        tt = HTML2Text()
        tt.body_width = 0
        res['desc'] = (tt.handle(m.group(1)) +
                       '\n\n_(описание взято с сайта instead-games.ru)_')

    m = INS_SCREENSHOTS.search(html)
    if m:
        for m in INS_SCREENSHOT.finditer(m.group(1)):
            res['urls'].append(
                CategorizeUrl(
                    unescape(m.group(1)), 'Скриншот', 'screenshot', base=url))

    m = INS_PANEL.search(html)
    if m:
        panel = m.group(1)
        m = INS_AUTHOR.search(panel)
        if m:
            authors = re.split(r',\s*', unescape(m.group(1)))
            for author in authors:
                res['authors'].append({'role_slug': 'author', 'name': author})

        m = INS_DATE.search(panel)
        if m:
            res['release_date'] = datetime.datetime.strptime(
                m.group(1), "%Y.%m.%d").date()

        for m in INS_LINK.finditer(panel):
            u = unescape(m.group(1))
            if u.startswith(INS_PREFIX):
                u = u[len(INS_PREFIX):]
            res['urls'].append(
                CategorizeUrl(u, unescape(m.group(2)), base=url))

    return res
