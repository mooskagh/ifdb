from urllib.parse import quote, urlunsplit, urlsplit, urlparse, urljoin
from .enrichment import enricher
from core.crawler import FetchUrlToString
import re
import os.path

RE_WORD = re.compile('\w+')
MIN_SIMILARITY = 0.67
REGISTERED_IMPORTERS = []

URL_CATEGORIZER_RULES = [  # hostname, path, query, slug, desc
    ('', r'.*screenshot.*\.(png|jpg|gif|bmp|jpeg)', '', 'screenshot',
     'Скриншот'),
    ('', r'.*\.(png|jpg|gif|bmp|jpeg)', '', 'poster', 'Обложка'),
    ('ifwiki.ru', '', '', 'game_page', 'Страница на IfWiki'),
    ('urq.plut.info', '.*/files/.*', '', 'download_direct', 'Скачать с плута'),
    ('urq.plut.info', '', '', 'game_page', 'Страница на плуте'),
    ('yadi.sk', '', '', 'download_landing', 'Скачать с Яндекс.диска'),
    ('rilarhiv.ru', '', '', 'download_direct', 'Скачать с РилАрхива'),
    ('instead-games.ru', '.*/download/.*', '', 'download_direct',
     'Скачать с инстеда'),
    ('instead-games.ru', '', '', 'game_page', 'Страница на инстеде'),
    ('instead.syscall.ru', '.*/forum/.*', '', 'forum', 'Форум на инстеде'),
    ('youtube.com', '', '', 'video', 'Видео игры'),
    ('www.youtube.com', '', '', 'video', 'Видео игры'),
    ('forum.ifiction.ru', '', '', 'forum', 'Обсуждение на форуме'),
    ('qsp.su', '', '.*=dd_download.*', 'download_direct', 'Скачать с qsp.ru'),
    ('qsp.su', '/tools/aero/.*', '', 'play_online', 'Играть онлайн на qsp.ru'),
    ('qsp.su', '', '', 'game_page', 'Игра на qsp.ru'),
    (r'@.*\.github\.io', '', '', 'play_online', 'Играть онлайн'),
    ('iplayif.com', '', '', 'play_online', 'Играть онлайн'),
    ('', r'.*\.(zip|rar|z5)', '', 'download_direct', 'Ссылка для скачивания'),
]


def CategorizeUrl(url, desc='', category=None, base=None):
    if base:
        url = urljoin(base, url)
    purl = urlparse(url)
    cat_slug = 'unknown'

    for (host, path, query, slug, ddesc) in URL_CATEGORIZER_RULES:
        if host:
            if host.startswith('@'):
                if not re.match(host[1:], purl.hostname):
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

    if category:
        cat_slug = category

    return {'urlcat_slug': cat_slug, 'description': desc, 'url': url}


def SimilarEnough(w1, w2):
    s1 = set(RE_WORD.findall(w1.lower()))
    s2 = set(RE_WORD.findall(w2.lower()))
    if not s1:
        return False

    similarity = len(s1 & s2) / len(s1 | s2)
    return similarity > MIN_SIMILARITY


def DispatchImport(url):
    for x in REGISTERED_IMPORTERS:
        if x.Match(url):
            return x.Import(url)

    return {'error': 'Ссылка на неизвестный ресурс.'}


def HashizeUrl(url):
    url = quote(url.encode('utf-8'), safe='/+=&?%:;@!#$*()_-')
    purl = urlsplit(url, allow_fragments=False)
    return urlunsplit(('', purl[1], purl[2], purl[3], ''))


def Import(seed_url):
    urls_checked = set()
    urls_to_check = set([seed_url])
    res = []
    title = None

    s_urls = set()
    s_tags = set()
    s_auth = set()

    def MergeImport(y, x):
        for z in ['title', 'release_date', 'error']:
            if z not in y and z in x:
                y[z] = x[z]

        if 'desc' in x:
            if 'desc' in y:
                if 'header' in x:
                    y['desc'] += x['header']
                else:
                    y['desc'] += '\n\n---\n\n'
            else:
                y['desc'] = ''
            y['desc'] += x['desc']

        for setz, field, extractor in [
            (s_urls, 'urls',
             lambda xx: (HashizeUrl(xx['url']), xx['urlcat_slug'])),
            (s_tags, 'tags',
             lambda xx: (xx.get('tag_slug'), xx.get('tag'), xx.get('cat_slug'))
             ),
            (s_auth, 'authors',
             lambda v: (v.get('role_slug'), v.get('role_slug'), v.get('name'))
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

        r = DispatchImport(url)
        enricher.Enrich(r)

        if 'priority' not in r:
            r['priority'] = -1000

        append = False
        if 'title' in r:
            if title:
                if SimilarEnough(title, r['title']):
                    append = True
            else:
                title = r['title']
                append = True
        elif not title:
            append = True

        if append:
            res.append(r)
            if 'urls' in r:
                for x in r['urls']:
                    if x['urlcat_slug'] == 'game_page':
                        urls_to_check.add(x['url'])

    res.sort(key=lambda x: x['priority'], reverse=True)

    r = {}
    for x in res:
        MergeImport(r, x)
    if 'title' in r and 'error' in r:
        del r['error']
    return r


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