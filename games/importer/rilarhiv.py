import re
from html import unescape
from logging import getLogger
from urllib.parse import quote, unquote, urldefrag, urljoin, urlparse, urlsplit

from core.crawler import FetchUrlToString

from .tools import CategorizeUrl

logger = getLogger("crawler")

RILARHIV_BASE = "http://rilarhiv.ru/"
RILARHIV_PLATFORMS = [
    ("Rinform", "rinform"),
    ("RTADS", "rtads"),
    ("URQ", "urq"),
    ("QSP", "qsp"),
    ("AeroQSP", "aeroqsp"),
    ("INSTEAD", "instead"),
    ("ADRIFT", "adrift"),
    ("Милена", "milena"),
    ("6 days", "6days"),
    ("ЯРИЛ", "yaril"),
    ("Twine", "tweebox"),
    ("TGE", "tge2"),
    ("ТКР-2", "tkr"),
    ("ZX Spectrum", "spectrum"),
    (None, "vneplatform"),
]
RILARHIV_LISTINGS = {link: platform for platform, link in RILARHIV_PLATFORMS}


def RilarhivListingUrl(link):
    return f"{RILARHIV_BASE}{link}.htm"


def FetchRilarhivListing(url, use_cache=True):
    return FetchUrlToString(url, use_cache=use_cache, encoding="cp1251")


def MakeRilarhivSourceUrl(listing_url, row_target):
    return f"{urldefrag(listing_url).url}#{quote(row_target, safe='')}"


class RilarhivRow:
    def __init__(self, listing_link, target, title, info, platforms, urls):
        self.listing_link = listing_link
        self.target = target
        self.title = title
        self.info = info
        self.platforms = platforms
        self.urls = urls


def _strip_tags(s):
    return re.sub(r"<[^>]*>", "", s)


def _rilarhiv_link_from_listing_url(url):
    parsed = urlparse(urldefrag(url).url)
    path = parsed.path.strip("/")
    if not path.endswith(".htm"):
        return None
    link = path[:-4]
    return link if link in RILARHIV_LISTINGS else None


def RilarhivListingUrlForTarget(url):
    parsed = urlparse(urldefrag(url).url)
    if parsed.hostname != "rilarhiv.ru":
        return None
    path = parsed.path.strip("/")
    if "/" not in path:
        return None
    link = path.split("/", 1)[0]
    if link not in RILARHIV_LISTINGS:
        return None
    return RilarhivListingUrl(link)


def _normalize_target_for_compare(target, listing_url):
    target = unescape(target).strip()
    target = re.sub(r"[\r\n\t]+", "", target)
    absolute = urljoin(RILARHIV_BASE, target)
    if listing_url:
        absolute = urljoin(listing_url, target)
    parsed = urlparse(absolute)
    if parsed.hostname == "rilarhiv.ru":
        return parsed.path.lstrip("/")
    return absolute


def RilarhivSourceTarget(url):
    split = urlsplit(url)
    if split.fragment:
        return unquote(split.fragment)
    return _normalize_target_for_compare(url, "")


def _categorize_row_anchor(href, text):
    text = text.strip()
    if "играть онлайн" in text.lower():
        return CategorizeUrl(
            href, desc="Играть онлайн", category="play_online",
            base=RILARHIV_BASE
        )
    parsed = urlparse(urljoin(RILARHIV_BASE, href))
    if parsed.hostname == "rilarhiv.ru" and re.search(
        r"(?i)\.(zip|rar|z5|exe)$", parsed.path
    ):
        return CategorizeUrl(href, base=RILARHIV_BASE)
    return CategorizeUrl(href, desc=text, base=RILARHIV_BASE)


def _is_rilarhiv_navigation_href(href):
    parsed = urlparse(urljoin(RILARHIV_BASE, href.strip()))
    if parsed.hostname != "rilarhiv.ru":
        return False
    path = parsed.path.strip("/")
    if "/" in path:
        return False
    return path.endswith(".htm")


def _find_platforms(block):
    platforms = []
    for m in BRACKET_PLATFORM_RE.finditer(block):
        platforms += [p.strip() for p in unescape(m.group(1)).split(",")]
    return [p for p in platforms if p]


def ParseRilarhivRows(raw, listing_url):
    listing_link = _rilarhiv_link_from_listing_url(listing_url)
    if listing_link is None:
        return []

    rows = []
    for p_match in P_RE.finditer(raw):
        block = p_match.group(0)
        anchors = list(ANCHOR_RE.finditer(block))
        if not anchors:
            continue
        first = anchors[0]
        if _is_rilarhiv_navigation_href(first.group("href")):
            continue
        first_text = unescape(_strip_tags(first.group("text"))).strip()
        if not first_text:
            continue

        title_match = TITLE_RE.match(first_text)
        title = title_match.group("title") if title_match else first_text
        info = title_match.group("info") if title_match else ""
        if not title.strip():
            continue

        urls = []
        for anchor in anchors:
            href = unescape(anchor.group("href")).strip()
            text = unescape(_strip_tags(anchor.group("text"))).strip()
            urls.append(_categorize_row_anchor(href, text))

        rows.append(
            RilarhivRow(
                listing_link,
                first.group("href").strip(),
                title.strip(),
                info,
                _find_platforms(block),
                urls,
            )
        )
    return rows


def FindRilarhivRow(raw, listing_url, target):
    wanted = _normalize_target_for_compare(target, listing_url)
    for row in ParseRilarhivRows(raw, listing_url):
        if _normalize_target_for_compare(row.target, listing_url) == wanted:
            return row
    return None


def RilarhivRowToImporterDict(row, include_all_urls=True):
    platform = RILARHIV_LISTINGS[row.listing_link]
    info = PARENTH_RE.sub(" ", row.info)
    authors = AUTHOR_SEP.split(info)
    res = {
        "title": row.title,
        "authors": [],
        "tags": [],
        "urls": row.urls if include_all_urls else row.urls[:1],
    }

    for a in authors:
        name = unescape(a).strip()
        if not name:
            continue
        res["authors"].append({
            "role_slug": "author",
            "name": name,
        })

    if platform:
        res["tags"].append({
            "cat_slug": "platform",
            "tag": platform,
        })

    for p in row.platforms:
        res["tags"].append({
            "cat_slug": "platform",
            "tag": p,
        })

    return res


class RilarhivImporter:
    def __init__(self):
        self.games = None

    def MatchWithCat(self, url, cat):
        return cat == "download_direct" and self.Match(url)

    def Match(self, url):
        return self.games and url in self.games

    def MatchAuthor(self, url):
        return False

    def Import(self, url):
        if self.games is None:
            return {"error": "Не проинициализирован импортер рилархива"}
        if url in self.games:
            return self.games[url]
        return {"error": "Неизвестный URL."}

    def GetUrlCandidates(self):
        self.games = {}
        candidates = []

        for _, link in RILARHIV_PLATFORMS:
            listing_url = RilarhivListingUrl(link)
            r = FetchRilarhivListing(listing_url, use_cache=False)

            for row in ParseRilarhivRows(r, listing_url):
                url = row.urls[0]["url"]
                self.games[url] = RilarhivRowToImporterDict(
                    row, include_all_urls=False
                )
                candidates.append(url)

        return candidates

    def GetDirtyUrls(self):
        return []


P_RE = re.compile(r"<P\b[^>]*>.*?</P>", re.I | re.S)
ANCHOR_RE = re.compile(
    r'<a\b[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<text>.*?)</a>',
    re.I | re.S,
)
TITLE_RE = re.compile(r'"?(?P<title>[^"]+)"?\s*(?P<info>.*)$', re.S)
ROOT_RE = re.compile(
    r'<P><b><a href="([^"]+)">"([^<"]+)"([^<]*)'
    r"</a></b>(?:[^<]*(?:<b>\[([^\]]+)]</b>))?"
)
BRACKET_PLATFORM_RE = re.compile(r"<b>\[([^\]]+)]</b>", re.I)
PARENTH_RE = re.compile(r"\s*(?:\([^)]+\)|/\S+/)\s*")
AUTHOR_SEP = re.compile(r", | и ")
