from html import unescape
import re
import urllib
import datetime
from html2text import HTML2Text
from urllib.parse import urlparse


def FetchUrl(url):
    print('Fetching: %s' % url)
    with urllib.request.urlopen(url) as response:
        return response.read().decode('utf-8')


MARKDOWN_SPECIAL_ESCAPED = re.compile(r'\\([\\\]\[()])')


def MdUnescape(str):
    return MARKDOWN_SPECIAL_ESCAPED.sub(r'\1', str)


def Import(url):
    try:
        html = FetchUrl(url)
    except:
        return {'error': 'Не открывается что-то этот URL.'}

    if PLUT_URL.match(url):
        return ImportFromPlut(url, html)

    return {'error': 'Ссылка на неизвестный ресурс.'}


def CategorizeUrl(url, desc):
    purl = urlparse(url)
    cat_slug = 'unknown'
    if purl.hostname == 'ifwiki.ru':
        cat_slug = 'game_page'
        if not desc:
            desc = 'Страница на IfWiki'
        elif 'ifwiki' not in desc.lower():
            desc = desc + ' (IfWiki)'

    if purl.hostname == 'urq.plut.info':
        if '/files/' in purl.path:
            cat_slug = 'download_direct'
            if not desc:
                desc = 'Скачать с плута'
        else:
            cat_slug = 'game_page'
            if not desc:
                desc = 'Страница на плуте'
            elif 'plut' not in desc.lower() and 'плут' not in desc.lower():
                desc = desc + ' (плут)'

    if purl.hostname == 'yadi.sk':
        cat_slug = 'download_landing'

    return {'urlcat_slug': cat_slug, 'description': desc, 'url': url}

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

MARKDOWN_LINK = re.compile(r'\[([^\]]*)\]\((.*?[^\\])\)')


def ParseFields(html):
    res = []
    for m in PLUT_FIELD.finditer(html):
        for n in PLUT_FIELD_ITEM.finditer(m.group()):
            res.append([m.group(1), n.group(1)])
    return res


def ImportFromPlut(url, html):
    res = {}
    m = PLUT_TITLE.search(html)
    if not m:
        return {'error': 'Не найдена игра на странице'}
    res['title'] = unescape(m.group(1))

    m = PLUT_DESC.search(html)
    if m:
        tt = HTML2Text()
        tt.body_width = 0
        res['desc'] = tt.handle(m.group(1))

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
            tags.append({'cat_slug': 'country', 'tag': tag})
        elif cat == 'Жанр':
            tags.append({'cat_slug': 'genre', 'tag': tag})
        elif cat == 'Авторы':
            authors.append({'role_slug': 'author', 'name': tag})

    if tags:
        res['tags'] = tags
    if authors:
        res['authors'] = authors

    # if 'desc' in res. Parse the rest of links
    if 'desc' in res:
        for m in MARKDOWN_LINK.finditer(res['desc']):
            x = CategorizeUrl(MdUnescape(m.group(2)), MdUnescape(m.group(1)))
            if x:
                res['urls'].append(x)

    return res
