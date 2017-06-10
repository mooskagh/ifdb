from .tools import FetchUrl, CategorizeUrl
from html import unescape
from html2text import HTML2Text
import datetime
import logging
import re


class QspsuImporter:
    def Match(self, url):
        return QSP_RE.match(url)

    def Import(self, url):
        return ImportFromQsp(url)


QSP_RE = re.compile(
    r'http://qsp\.su/index\.php\?option=com_sobi2&.*&sobi2Id=\d+.*')

QSP_DETAILS = re.compile(r'<table class="sobi2Details"[^>]*>(.*?)</table>',
                         re.DOTALL)
QSP_TR = re.compile(r'<tr>(.*?)</tr>', re.DOTALL)
QSP_TITLE = re.compile(r'<h1>(.*?)</h1>')
QSP_IMG = re.compile(r'<img src="([^"]+)"[^>]*class="sobi2DetailsImage"')
QSP_FIELD = re.compile(r'<span\s+id="sobi2Details_field_([^"]+)"\s*>'
                       '(?:<span .*?</span> )?(.*?)</span>', re.DOTALL)
QSP_DOWNLOAD_LINK = re.compile(r'<h2><a href="([^"]+)" title="download">'
                               '(?:Скачать|Играть онлайн)</a></h2>')
QSP_LINK = re.compile(r'>Файл: <a href="([^"]+)"[^>]*>([^<]+)</a>')

QSP_DETAILS_FOOTER = re.compile(
    r'<table class="sobi2DetailsFooter"[^>]*>(.*?)</table>', re.DOTALL)
QSP_ADD_DATE = re.compile(r'Добавлено: (\d+)\.(\d+)\.(\d+)&nbsp;&nbsp;')


def ImportFromQsp(url):
    try:
        html = FetchUrl(url)
    except:
        return {'error': 'Не открывается что-то этот URL.'}

    res = {'priority': 40}
    m = QSP_DETAILS.search(html)
    if not m:
        return {'error': 'Не найдена игра на странице'}

    res['urls'] = [CategorizeUrl(url, '', base=url)]
    authors = []
    tags = []

    for m in QSP_TR.finditer(m.group(1)):
        tr = m.group(1)
        n = QSP_TITLE.search(tr)
        if n:
            res['title'] = unescape(n.group(1))
        n = QSP_IMG.search(tr)
        if n:
            res['urls'].append(
                CategorizeUrl(
                    n.group(1), 'Обложка', 'poster', base=url))
        for n in QSP_FIELD.finditer(tr):
            key = n.group(1)
            val = n.group(2)
            if key == 'author':
                authors.append({'role_slug': 'author', 'name': unescape(val)})
            elif key == 'translator':
                authors.append({'role_slug': 'porter', 'name': unescape(val)})
            elif key == 'version':
                tags.append({'cat_slug': 'version', 'tag': unescape(val)})
            elif key == 'description':
                tt = HTML2Text()
                tt.body_width = 0
                res['desc'] = tt.handle(val)
            else:
                logging.error('Unknown field in QSP: [%s] [%s]' % (key, val))
        for n in QSP_LINK.finditer(tr):
            res['urls'].append(CategorizeUrl(n.group(1), n.group(2)))
        for n in QSP_DOWNLOAD_LINK.finditer(tr):
            res['urls'].append(CategorizeUrl(n.group(1), base=url))

    if 'title' not in res:
        return {'error': 'Не найдена игра на странице'}

    if authors:
        res['authors'] = authors
    if tags:
        res['tags'] = tags

    m = QSP_DETAILS_FOOTER.search(html)
    if m:
        n = QSP_ADD_DATE.search(m.group(1))
        if n:
            res['release_date'] = datetime.datetime(
                int(n.group(3)), int(n.group(2)), int(n.group(1))).date()

    return res
