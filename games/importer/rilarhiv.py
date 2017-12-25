from .tools import CategorizeUrl
from core.crawler import FetchUrlToString
from logging import getLogger
import re
from html import unescape

logger = getLogger('crawler')


class RilarhivImporter:
    def __init__(self):
        self.games = None

    def MatchWithCat(self, url, cat):
        return cat == 'download_direct' and self.Match(url)

    def Match(self, url):
        return self.games and url in self.games

    def MatchAuthor(self, url):
        return False

    def Import(self, url):
        if self.games is None:
            return {'error': 'Не проинициализирован импортер рилархива'}
        if url in self.games:
            return self.games[url]
        return {'error': 'Неизвестный URL.'}

    def GetUrlCandidates(self):
        self.games = {}
        candidates = []

        PLATFORMS = [
            ('Rinform', 'rinform'),
            ('RTADS', 'rtads'),
            ('URQ', 'urq'),
            ('QSP', 'qsp'),
            ('AeroQSP', 'aeroqsp'),
            ('INSTEAD', 'instead'),
            ('ADRIFT', 'adrift'),
            ('Милена', 'milena'),
            ('6 days', '6days'),
            ('ЯРИЛ', 'yaril'),
            ('Twine', 'tweebox'),
            ('TGE', 'tge2'),
            ('ТКР-2', 'tkr'),
            ('ZX Spectrum', 'spectrum'),
            (None, 'vneplatform'),
        ]

        for (platform, link) in PLATFORMS:
            r = FetchUrlToString(
                'http://rilarhiv.ru/%s.htm' % link,
                use_cache=False,
                encoding='cp1251')

            for m in ROOT_RE.finditer(r):
                (url, title, info, platforms) = m.groups()
                fullurl = CategorizeUrl(url, base='http://rilarhiv.ru/')

                info = PARENTH_RE.sub(' ', info)
                authors = AUTHOR_SEP.split(info)
                plats = platforms.split(', ') if platforms else []

                res = {
                    'title': unescape(title).strip(),
                    'authors': [],
                    'tags': [],
                    'urls': [fullurl]
                }

                for a in authors:
                    name = unescape(a).strip()
                    if not name:
                        continue
                    res['authors'].append({
                        'role_slug': 'author',
                        'name': name,
                    })

                if platform:
                    res['tags'].append({
                        'cat_slug': 'platform',
                        'tag': platform,
                    })

                for p in plats:
                    plat = unescape(p).strip()
                    if not plat:
                        continue
                    res['tags'].append({
                        'cat_slug': 'platform',
                        'tag': plat,
                    })

                self.games[fullurl['url']] = res
                candidates.append(fullurl['url'])

        return candidates

    def GetDirtyUrls(self):
        return []


ROOT_RE = re.compile(r'<P><b><a href="([^"]+)">"([^<"]+)"([^<]*)'
                     r'</a></b>(?:[^<]*(?:<b>\[([^\]]+)]</b>))?')
PARENTH_RE = re.compile(r'\s*(?:\([^)]+\)|/\S+/)\s*')
AUTHOR_SEP = re.compile(r', | и ')
