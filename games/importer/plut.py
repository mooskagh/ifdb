import re
from html import unescape
from .tools import CategorizeUrl
from core.crawler import FetchUrlToString
from html2text import HTML2Text
import datetime


class PlutImporter:
    def Match(self, url):
        return PLUT_URL.match(url)

    def Import(self, url):
        return ImportFromPlut(url)

    def GetUrlCandidates(self):
        return []

    def GetUrlCandidates(self):
        return GetCandidates()


PLUT_LISTING_TITLE_RE = re.compile(
    r'<td class="views-field views-field-title" >\s*<a href="([^"]+)"')


def GetCandidates():
    page = 0
    res = []

    while True:
        r = FetchUrlToString(
            r'https://urq.plut.info/games?page=' + str(page), use_cache=False)

        found = False

        for m in PLUT_LISTING_TITLE_RE.finditer(r):
            res.append('https://urq.plut.info' + unescape(m.group(1)))
            found = True

        if not found:
            break

        page += 1

    return res


PLUT_URL = re.compile(r'https?://urq.plut.info/(?:node/\d+|[^/]+)')
PLUT_TITLE = re.compile(r'<h1 class="title">(.*?)</h1>')
PLUT_DESC = re.compile(
    r'<div class="field field-name-body field-type-text-with-summary '
    r'field-label-hidden"><div class="field-items">(.*?)</div>', re.DOTALL)

PLUT_RELEASE = re.compile(
    r'<div id="block-system-main".*?'
    r'<span property="dc:date dc:created" content="(\d\d\d\d-\d\d-\d\d)',
    re.DOTALL)

PLUT_FIELD = re.compile(r'<div class="field-label">([^<:]+).*?</div>.*?</div>',
                        re.DOTALL)

PLUT_FIELD_ITEM = re.compile(r'<a [^>]+>([^<]+)</a>')
PLUT_DOWNLOAD_LINK = re.compile(
    r'<td><span class="file"><img class="file-icon" [^>]+> '
    r'<a href="([^"]+)"[^>]*>([^<]*)</a>')

MARKDOWN_LINK = re.compile(r'\[([^\]]*)\]\((.*?[^\\])\)|<([^> ]+)>')
MARKDOWN_SPECIAL_ESCAPED = re.compile(r'\\([\\\]\[()])')


def MdUnescape(str):
    return MARKDOWN_SPECIAL_ESCAPED.sub(r'\1', str)


def ParseFields(html):
    res = []
    for m in PLUT_FIELD.finditer(html):
        for n in PLUT_FIELD_ITEM.finditer(m.group()):
            res.append([unescape(m.group(1)), unescape(n.group(1))])
    return res


def ImportFromPlut(url):
    try:
        html = FetchUrlToString(url)
    except Exception as e:
        return {'error': 'Не открывается что-то этот URL.'}

    res = {'priority': 50}
    m = PLUT_TITLE.search(html)
    if not m:
        return {'error': 'Не найдена игра на странице'}
    res['title'] = unescape(m.group(1))

    m = PLUT_DESC.search(html)
    if m:
        tt = HTML2Text()
        tt.body_width = 0
        res['desc'] = (tt.handle(m.group(1)) +
                       '\n\n_(описание взято с сайта urq.plut.info)_')

    m = PLUT_RELEASE.search(html)
    if m:
        res['release_date'] = datetime.datetime.strptime(
            m.group(1), "%Y-%m-%d").date()

    res['urls'] = [CategorizeUrl(url, '')]

    for m in PLUT_DOWNLOAD_LINK.finditer(html):
        url = m.group(1)
        desc = unescape(m.group(2))
        res['urls'].append(CategorizeUrl(url, desc))

    tags = []
    authors = []

    for cat, tag in ParseFields(html):
        if cat == 'Статус':
            if tag == 'ббета':
                tags.append({'tag_slug': 'beta'})
            elif tag == 'готовая':
                tags.append({'tag_slug': 'released'})
            elif tag == 'демо':
                tags.append({'tag_slug': 'demo'})
            elif tag == 'в разработке':
                tags.append({'tag_slug': 'in_dev'})
        elif cat == 'Платформа':
            tags.append({'cat_slug': 'platform', 'tag': tag})
        elif cat == 'Страна':
            tags.append({'cat_slug': 'country', 'tag': tag.capitalize()})
        elif cat == 'Жанр':
            tags.append({'cat_slug': 'tag', 'tag': tag.lower()})
        elif cat == 'Авторы':
            authors.append({'role_slug': 'author', 'name': tag})

    res['tags'] = tags
    res['authors'] = authors

    # if 'desc' in res. Parse the rest of links
    if 'desc' in res:
        for m in MARKDOWN_LINK.finditer(res['desc']):
            if m.group(3):
                x = CategorizeUrl(m.group(3))
            else:
                x = CategorizeUrl(
                    MdUnescape(m.group(2)), MdUnescape(m.group(1)))
            if x:
                res['urls'].append(x)

    return res
