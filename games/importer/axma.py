import datetime
import re
from html import unescape
from logging import getLogger
from typing import Any
from urllib.parse import urljoin

from html2text import HTML2Text

from core.crawler import FetchUrlToString

from .tools import AddDescriptionAttribution, CategorizeUrl

logger = getLogger("crawler")

AXMA_GAME_URL = re.compile(r"https?://axmajs\.ru/library/\?id=\d+")
AXMA_LIBRARY_URL = "https://axmajs.ru/library/"

AXMA_H5_RE = re.compile(r"<h5>(.*?)</h5>", re.DOTALL)
AXMA_VERSION_RE = re.compile(r"<span class=['\"]version['\"]>([^<]+)</span>")
AXMA_AUTHOR_RE = re.compile(r"<span class=['\"]author['\"]>([^<]+)</span>")
AXMA_DATE_RE = re.compile(
    r"<div class=['\"]small['\"] style=['\"]float:right;['\"]>"
    r"(\d{2}\.\d{2}\.\d{2})</div>"
)
AXMA_SUBTITLE_RE = re.compile(
    r"<div class=['\"]subtitle['\"]>(.*?)</div>", re.DOTALL
)
AXMA_COVER_RE = re.compile(
    r"<img class=['\"]coverlib['\"][^>]*src=['\"]([^'\"]+)['\"]"
)
AXMA_PLAY_RE = re.compile(r"https?://lib\.axmajs\.ru/[^'\"/\s]+/?")
AXMA_DOWNLOAD_RE = re.compile(
    r"(?:nohr|href)=['\"]([^'\"]*download_zip\.php\?id=\d+)"
)
AXMA_TAG_RE = re.compile(r"<a href=['\"]\?tag=\d+['\"][^>]*>([^<]+)</a>")


class AxmaImporter:
    def MatchWithCat(self, url: str, cat: str) -> bool:
        return cat == "game_page" and self.Match(url)

    def Match(self, url: str) -> bool:
        return bool(AXMA_GAME_URL.match(url))

    def MatchAuthor(self, url: str) -> bool:
        return False

    def GetUrlCandidates(self) -> list[str]:
        return FetchCandidateUrls()

    def GetDirtyUrls(self) -> list[str]:
        return []

    def Import(self, url: str) -> dict[str, Any]:
        return ImportFromAxma(url)


def FetchCandidateUrls() -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    offset = 0
    while True:
        catalog_url = f"{AXMA_LIBRARY_URL}?from={offset}&sort=last"
        html = FetchUrlToString(catalog_url, use_cache=False)
        content = html.split("<h3>Последние комментарии")[0]
        ids = re.findall(r"download_zip\.php\?id=(\d+)", content)
        if not ids:
            break
        for gid in ids:
            game_url = f"{AXMA_LIBRARY_URL}?id={gid}"
            if game_url not in seen:
                seen.add(game_url)
                urls.append(game_url)
        offset += len(ids)
    return urls


def ImportFromAxma(url: str) -> dict[str, Any]:
    try:
        html = FetchUrlToString(url)
    except Exception:
        return {"error": "Не открывается что-то этот URL."}
    return ParseAxma(html, url)


def ParseAxma(html: str, url: str) -> dict[str, Any]:
    content = html.split("<h3>Последние комментарии")[0]

    h5_match = AXMA_H5_RE.search(content)
    if not h5_match:
        return {"error": "Не найдена игра на странице"}

    res: dict[str, Any] = {
        "priority": 70,
        "authors": [],
        "tags": [
            {"cat_slug": "platform", "tag": "AXMA Story Maker JS"},
            {"cat_slug": "language", "tag": "Русский"},
        ],
        "urls": [
            CategorizeUrl(url, "Страница на axmajs.ru", "game_page", base=url)
        ],
    }

    h5_content = h5_match.group(1)
    raw_title = h5_content.split("<span")[0].strip()
    res["title"] = unescape(raw_title)

    version_match = AXMA_VERSION_RE.search(h5_content)
    if version_match:
        version_text = unescape(version_match.group(1).strip())
        if version_text:
            res["tags"].append({"cat_slug": "version", "tag": version_text})

    author_match = AXMA_AUTHOR_RE.search(h5_content)
    if author_match:
        raw_author = unescape(author_match.group(1).strip())
        author = re.sub(
            r"^Автор:\s*", "", raw_author, flags=re.IGNORECASE
        ).strip()
        if author:
            res["authors"].append({"role_slug": "author", "name": author})

    date_match = AXMA_DATE_RE.search(content)
    if date_match:
        try:
            res["release_date"] = datetime.datetime.strptime(
                date_match.group(1), "%d.%m.%y"
            ).date()
        except ValueError:
            pass

    desc_match = AXMA_SUBTITLE_RE.search(content)
    if desc_match:
        tt = HTML2Text()
        tt.body_width = 0
        desc_text = tt.handle(desc_match.group(1)).strip()
        if desc_text:
            res["desc"] = desc_text
            AddDescriptionAttribution(res, "axmajs.ru")

    cover_match = AXMA_COVER_RE.search(content)
    if cover_match:
        cover_url = urljoin(url, cover_match.group(1))
        res["urls"].append(
            CategorizeUrl(cover_url, "Обложка", "poster", base=url)
        )

    play_match = AXMA_PLAY_RE.search(content)
    if play_match:
        play_url = play_match.group(0)
        if not play_url.endswith("/"):
            play_url += "/"
        res["urls"].append(
            CategorizeUrl(play_url, "Играть онлайн", "play_online", base=url)
        )

    dl_match = AXMA_DOWNLOAD_RE.search(content)
    if dl_match:
        dl_url = urljoin(url, dl_match.group(1))
        res["urls"].append(
            CategorizeUrl(
                dl_url, "Скачать с axmajs.ru", "download_direct", base=url
            )
        )

    for tag in AXMA_TAG_RE.findall(content):
        tag_name = unescape(tag.strip())
        if tag_name:
            res["tags"].append({"cat_slug": "tag", "tag": tag_name})

    return res
