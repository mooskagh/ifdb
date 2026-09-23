"""Source drivers: the per-site half of the next-gen import pipeline.

A driver's defining job is **raw document -> canonical form**
(:meth:`GameSourceProvider.canonicalize`).  It also exposes a site-specific
``fetch`` primitive; scheduling, retries and deduplication stay in the runner.

In Phase A each provider is a thin bridge over the legacy ``games/importer``
parse logic: it reuses the old per-site ``ParseX`` (split out of
``ImportFromX`` so the live path is untouched) and runs the result through
:meth:`GameInfo.from_importer_dict`.  Native ``GameInfo`` construction is
deferred to later phases.

``canonicalize`` is meant to be pure over stored ``raw`` content, with one
accepted exception: **ifiction and ifwiki may fetch during canonicalization to
resolve redirects** (ifiction's ``ResolveRedirect``, ifwiki's
``#REDIRECT``-chase).  No nicer design exists; this is intended behavior.
"""

import datetime
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urljoin

from html2text import HTML2Text

from core.crawler import FetchUrlToString
from games.gameinfo import (
    LANGUAGE_NORMALIZATION,
    Attribution,
    GameInfo,
    GameUrl,
    Person,
    Tag,
)
from games.importer.apero import (
    APERO_URL,
    FetchApero,
    FetchCandidateUrls,
    ParseApero,
    ParseAuthorApero,
)
from games.importer.ifiction import (
    IFICTION_URL,
    FetchIfiction,
    ParseIfiction,
)
from games.importer.ifiction import GetGameList as GetIfictionGameList
from games.importer.ifwiki import (
    IFWIKI_URL,
    FetchCategoryUrls,
    FetchIfwikiRaw,
    ParseAuthorFromIfwiki,
    ParseIfwiki,
)
from games.importer.insteadgames import (
    INSTEAD_URL,
    FetchInstead,
    ParseInstead,
)
from games.importer.insteadgames import GetGameList as GetInsteadGameList
from games.importer.plut import (
    PLUT_URL,
    FetchPlut,
    ParsePlut,
)
from games.importer.plut import GetCandidates as GetPlutCandidates
from games.importer.questbook import (
    QUESTBOOK_GAMEDETAIL_URL,
    FetchQuestBook,
    ParseQuestBook,
)
from games.importer.questbook import GetCandidates as GetQuestBookCandidates
from games.importer.rilarhiv import (
    RILARHIV_LISTINGS,
    FetchRilarhivListing,
    FindRilarhivRow,
    MakeRilarhivSourceUrl,
    ParseRilarhivRows,
    RilarhivListingUrl,
    RilarhivListingUrlForTarget,
    RilarhivRowToImporterDict,
    RilarhivSourceTarget,
)
from games.importer.tools import QuoteUtf8

from .models import GameSource


def _base_source_key(url: str) -> str:
    """Scheme- and trailing-slash-insensitive identity for matching.

    Stored URLs are heterogeneous (legacy ``http://`` from seeding, clean
    ``https://`` from discover); strip the scheme and any trailing slash so the
    two paths collapse to the same key.  Not lowercased -- ifwiki titles are
    case-sensitive.
    """
    return re.sub(r"^https?://", "", url).rstrip("/")


@dataclass
class DiscoveredSource:
    """A URL found by a provider's listing crawl."""

    url: str


@dataclass
class CanonicalAuthor:
    """Canonical author info -- the author analogue of ``GameInfo``."""

    name: str
    bio: str | None = None
    urls: list[GameUrl] = field(default_factory=list)

    @classmethod
    def from_importer_dict(cls, d: dict) -> "CanonicalAuthor":
        return cls(
            name=d.get("name", ""),
            bio=d.get("bio"),
            urls=[
                GameUrl(u["urlcat_slug"], None, u.get("description"), u["url"])
                for u in d.get("urls", [])
                if u.get("urlcat_slug")
            ],
        )


class GameSourceProvider(ABC):
    """One driver per ``GameSource.SourceType``, routed by URL (registry)."""

    source_type: GameSource.SourceType

    @abstractmethod
    def owns(self, url: str) -> bool:
        """Claim a URL (the old ``Match``)."""

    @abstractmethod
    def fetch(self, url: str) -> str:
        """Fetch and decode the raw source document."""

    @abstractmethod
    def canonicalize(self, raw: str, url: str) -> GameInfo:
        """Raw document -> canonical ``GameInfo`` (Phase 2.5)."""

    def discover(self) -> Iterable[DiscoveredSource]:
        """Listing crawl -> candidate source URLs (Phase 1)."""
        return ()

    def source_key(self, url: str) -> str:
        """Scheme- and trailing-slash-insensitive identity for matching.

        Used to dedup discovered URLs against stored ones; *never* persisted.
        """
        return _base_source_key(url)

    def canonicalize_author(
        self, raw: str, url: str
    ) -> CanonicalAuthor | None:
        """Raw document -> ``CanonicalAuthor``; default ``None``.

        Only apero + ifwiki have real author parsing; the rest inherit this.
        """
        return None


class AperoProvider(GameSourceProvider):
    source_type = GameSource.SourceType.APERO

    def owns(self, url: str) -> bool:
        return bool(APERO_URL.match(QuoteUtf8(url)))

    def fetch(self, url: str) -> str:
        return FetchApero(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        return GameInfo.from_importer_dict(ParseApero(raw, url))

    def discover(self) -> Iterable[DiscoveredSource]:
        return (DiscoveredSource(url) for url in FetchCandidateUrls())

    def canonicalize_author(
        self, raw: str, url: str
    ) -> CanonicalAuthor | None:
        return CanonicalAuthor.from_importer_dict(ParseAuthorApero(raw, url))


class IfwikiProvider(GameSourceProvider):
    source_type = GameSource.SourceType.IFWIKI

    def owns(self, url: str) -> bool:
        return bool(IFWIKI_URL.match(url))

    def fetch(self, url: str) -> str:
        return FetchIfwikiRaw(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        return GameInfo.from_importer_dict(ParseIfwiki(raw, url))

    def discover(self) -> Iterable[DiscoveredSource]:
        return (DiscoveredSource(url) for url in FetchCategoryUrls("Игры"))

    def canonicalize_author(
        self, raw: str, url: str
    ) -> CanonicalAuthor | None:
        return CanonicalAuthor.from_importer_dict(
            ParseAuthorFromIfwiki(raw, url)
        )


class InsteadGamesProvider(GameSourceProvider):
    source_type = GameSource.SourceType.INSTEAD

    def owns(self, url: str) -> bool:
        return bool(INSTEAD_URL.match(url))

    def fetch(self, url: str) -> str:
        return FetchInstead(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        return GameInfo.from_importer_dict(ParseInstead(raw, url))

    def discover(self) -> Iterable[DiscoveredSource]:
        return (DiscoveredSource(url) for url in GetInsteadGameList())


class QuestBookProvider(GameSourceProvider):
    source_type = GameSource.SourceType.QUESTBOOK

    def owns(self, url: str) -> bool:
        return bool(QUESTBOOK_GAMEDETAIL_URL.match(url))

    def fetch(self, url: str) -> str:
        return FetchQuestBook(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        return GameInfo.from_importer_dict(ParseQuestBook(raw, url))

    def discover(self) -> Iterable[DiscoveredSource]:
        return (DiscoveredSource(url) for url in GetQuestBookCandidates())


class IfictionProvider(GameSourceProvider):
    source_type = GameSource.SourceType.IFICTION

    def owns(self, url: str) -> bool:
        return bool(IFICTION_URL.match(url))

    def fetch(self, url: str) -> str:
        return FetchIfiction(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        return GameInfo.from_importer_dict(ParseIfiction(raw, url))

    def discover(self) -> Iterable[DiscoveredSource]:
        return (DiscoveredSource(url) for url in GetIfictionGameList())

    def source_key(self, url: str) -> str:
        # Identity is the game ``id``; drop the ``&lid=NN`` tracking param.
        return re.sub(r"&lid=\d+", "", _base_source_key(url))


QSP_API_BASE = "https://qsp.org/api/v1"
QSP_PUBLIC_GAME_RE = re.compile(
    r"https?://qsp\.org/games/([^/?#]+)/?(?:[?#].*)?$"
)
QSP_API_GAME_RE = re.compile(
    r"https?://qsp\.org/api/v1/games/([^/?#]+)/?(?:[?#].*)?$"
)


def _qsp_game_ref(url: str) -> str:
    if m := QSP_PUBLIC_GAME_RE.match(url):
        return m.group(1)
    if m := QSP_API_GAME_RE.match(url):
        return m.group(1)
    raise ValueError(f"Unsupported QSP source URL: {url}")


def _qsp_game_id(ref: str) -> str | None:
    m = re.match(r"(\d+)(?:-|$)", ref)
    return m.group(1) if m else None


def _qsp_public_url(slug: str) -> str:
    return f"https://qsp.org/games/{slug}"


def FetchQspApi(url: str, use_cache=True) -> str:
    return FetchUrlToString(
        f"{QSP_API_BASE}/games/{_qsp_game_ref(url)}", use_cache=use_cache
    )


def FetchQspApiGameList(page: int, use_cache=True) -> str:
    return FetchUrlToString(
        f"{QSP_API_BASE}/games?per-page=100&page={page}",
        use_cache=use_cache,
    )


def _qsp_names(value: str | None) -> list[str]:
    return [name.strip() for name in (value or "").split(",") if name.strip()]


def _qsp_description(html: str) -> str | None:
    if not html:
        return None
    tt = HTML2Text()
    tt.body_width = 0
    return tt.handle(html)


def _qsp_language(lang: str | None) -> str | None:
    if not lang:
        return None
    cleaned = lang.strip().lower()
    return LANGUAGE_NORMALIZATION.get(cleaned, cleaned)


def _qsp_game_info(game: dict) -> GameInfo:
    slug = game["slug"]
    info = GameInfo(
        name=game.get("name"),
        date=(game.get("created_at") or "").split("T", 1)[0] or None,
        description=_qsp_description(game.get("description_html") or ""),
        attributions=[Attribution(None, "qsp.org")],
    )
    info.personalities["author"] = [
        Person(None, name) for name in _qsp_names(game.get("authors"))
    ]
    translators = _qsp_names(game.get("translators"))
    if translators:
        info.personalities["translator"] = [
            Person(None, name) for name in translators
        ]
    info.tags.append(Tag("platform", None, None, "QSP"))
    if version := game.get("ver"):
        info.tags.append(Tag("version", None, None, version))
    if language := _qsp_language(game.get("lang")):
        info.tags.append(Tag("language", None, None, language))
    info.urls.append(GameUrl("game_page", None, None, _qsp_public_url(slug)))
    if file_url := game.get("file_url"):
        info.urls.append(GameUrl("download_direct", None, None, file_url))
    if poster_url := game.get("cover_url") or game.get("icon_url"):
        info.urls.append(GameUrl("poster", None, None, poster_url))
    return info


class QspSuProvider(GameSourceProvider):
    source_type = GameSource.SourceType.QSP

    def owns(self, url: str) -> bool:
        return bool(
            QSP_PUBLIC_GAME_RE.match(url) or QSP_API_GAME_RE.match(url)
        )

    def fetch(self, url: str) -> str:
        return FetchQspApi(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        parsed = json.loads(raw)
        return _qsp_game_info(parsed.get("data", parsed))

    def discover(self) -> Iterable[DiscoveredSource]:
        page = 1
        while True:
            parsed = json.loads(FetchQspApiGameList(page, use_cache=False))
            for game in parsed["data"]:
                yield DiscoveredSource(_qsp_public_url(game["slug"]))
            if page >= parsed["meta"]["last_page"]:
                break
            page += 1

    def source_key(self, url: str) -> str:
        try:
            ref = _qsp_game_ref(url)
        except ValueError:
            return _base_source_key(url)
        game_id = _qsp_game_id(ref)
        return f"qsp:game={game_id}" if game_id else _base_source_key(url)


class PlutProvider(GameSourceProvider):
    source_type = GameSource.SourceType.PLUT

    def owns(self, url: str) -> bool:
        return bool(PLUT_URL.match(url))

    def fetch(self, url: str) -> str:
        return FetchPlut(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        return GameInfo.from_importer_dict(ParsePlut(raw, url))

    def discover(self) -> Iterable[DiscoveredSource]:
        return (DiscoveredSource(url) for url in GetPlutCandidates())


class RilarhivProvider(GameSourceProvider):
    source_type = GameSource.SourceType.RILARHIV

    def owns(self, url: str) -> bool:
        return self._listing_url(url) is not None

    def fetch(self, url: str) -> str:
        listing_url = self._listing_url(url)
        if listing_url is None:
            raise ValueError(f"Unsupported Rilarhiv source URL: {url}")
        return FetchRilarhivListing(listing_url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        listing_url = self._listing_url(url)
        if listing_url is None:
            raise ValueError(f"Unsupported Rilarhiv source URL: {url}")
        target = RilarhivSourceTarget(url)
        row = FindRilarhivRow(raw, listing_url, target)
        if row is None:
            raise ValueError(f"Rilarhiv row not found: {target}")
        return GameInfo.from_importer_dict(RilarhivRowToImporterDict(row))

    def discover(self) -> Iterable[DiscoveredSource]:
        for link in RILARHIV_LISTINGS:
            listing_url = RilarhivListingUrl(link)
            raw = FetchRilarhivListing(listing_url, use_cache=False)
            for row in ParseRilarhivRows(raw, listing_url):
                yield DiscoveredSource(
                    MakeRilarhivSourceUrl(listing_url, row.target)
                )

    def source_key(self, url: str) -> str:
        listing_url = self._listing_url(url)
        if listing_url is None:
            return _base_source_key(url)
        return (
            f"rilarhiv:{_base_source_key(listing_url)}"
            f"#{RilarhivSourceTarget(url)}"
        )

    def _listing_url(self, url: str) -> str | None:
        base_url = url.split("#", 1)[0]
        if re.match(r"https?://rilarhiv\.ru/[^/?#]+\.htm$", base_url):
            link = base_url.rsplit("/", 1)[1][:-4]
            if link in RILARHIV_LISTINGS:
                return base_url
        return RilarhivListingUrlForTarget(url)


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


def _axma_candidates() -> Iterable[str]:
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
                yield game_url
        offset += len(ids)


def _axma_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        return datetime.datetime.strptime(date_str, "%d.%m.%y").strftime(
            "%Y-%m-%d"
        )
    except ValueError:
        return None


def _axma_game_info(html: str, url: str) -> GameInfo:
    content = html.split("<h3>Последние комментарии")[0]

    h5_match = AXMA_H5_RE.search(content)
    if not h5_match:
        raise ValueError(f"Game not found on AXMA page: {url}")

    h5_content = h5_match.group(1)
    name = unescape(h5_content.split("<span")[0].strip())

    date = None
    date_match = AXMA_DATE_RE.search(content)
    if date_match:
        date = _axma_date(date_match.group(1))

    description = None
    desc_match = AXMA_SUBTITLE_RE.search(content)
    if desc_match:
        tt = HTML2Text()
        tt.body_width = 0
        desc_text = tt.handle(desc_match.group(1)).strip()
        if desc_text:
            description = desc_text

    info = GameInfo(
        name=name,
        date=date,
        description=description,
        attributions=[Attribution(None, "axmajs.ru")],
    )

    author_match = AXMA_AUTHOR_RE.search(h5_content)
    if author_match:
        raw_author = unescape(author_match.group(1).strip())
        author = re.sub(
            r"^Автор:\s*", "", raw_author, flags=re.IGNORECASE
        ).strip()
        if author:
            info.personalities["author"] = [Person(None, author)]

    info.tags.append(Tag("platform", None, None, "AXMA Story Maker JS"))
    info.tags.append(Tag("language", None, None, "русский"))

    version_match = AXMA_VERSION_RE.search(h5_content)
    if version_match:
        version_text = unescape(version_match.group(1).strip())
        if version_text:
            info.tags.append(Tag("version", None, None, version_text))

    for tag in AXMA_TAG_RE.findall(content):
        tag_name = unescape(tag.strip()).lower()
        if tag_name:
            info.tags.append(Tag("tag", None, None, tag_name))

    info.urls.append(GameUrl("game_page", None, "Страница на axmajs.ru", url))

    cover_match = AXMA_COVER_RE.search(content)
    if cover_match:
        cover_url = urljoin(url, cover_match.group(1))
        info.urls.append(GameUrl("poster", None, "Обложка", cover_url))

    play_match = AXMA_PLAY_RE.search(content)
    if play_match:
        play_url = play_match.group(0)
        if not play_url.endswith("/"):
            play_url += "/"
        info.urls.append(
            GameUrl("play_online", None, "Играть онлайн", play_url)
        )

    dl_match = AXMA_DOWNLOAD_RE.search(content)
    if dl_match:
        dl_url = urljoin(url, dl_match.group(1))
        info.urls.append(
            GameUrl("download_direct", None, "Скачать с axmajs.ru", dl_url)
        )

    return info


class AxmaProvider(GameSourceProvider):
    source_type = GameSource.SourceType.AXMA

    def owns(self, url: str) -> bool:
        return bool(AXMA_GAME_URL.match(url))

    def fetch(self, url: str) -> str:
        return FetchUrlToString(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        return _axma_game_info(raw, url)

    def discover(self) -> Iterable[DiscoveredSource]:
        return (DiscoveredSource(url) for url in _axma_candidates())


HYPERBOOK_GAME_URL = re.compile(
    r"https?://(?:www\.)?hyperbook\.ru/comments\.php\?id=\d+"
)
HYPERBOOK_LIBRARY_URL = "https://hyperbook.ru/lib.php"
HYPERBOOK_H1_RE = re.compile(
    r"<h1[^>]*title=['\"]запустить['\"][^>]*>(.*?)</h1>", re.DOTALL
)
HYPERBOOK_AUTHOR_DIV_RE = re.compile(
    r"<div[^>]*margin-bottom:\s*14px[^>]*>(.*?)</div>", re.DOTALL
)
HYPERBOOK_DATE_RE = re.compile(
    r"Параграфов:.*?</div>\s*<div[^>]*>(\d{2}\.\d{2}\.\d{2})</div>", re.DOTALL
)
HYPERBOOK_GENRE_RE = re.compile(
    r"<a[^>]+href=['\"]lib\.php\?sort=genre\d+['\"][^>]*>([^<]+)</a>"
)


def _hyperbook_game_id(url: str) -> str | None:
    if m := re.search(r"[?&]id=(\d+)", url):
        return m.group(1)
    if m := re.search(r"/file(\d+)", url):
        return m.group(1)
    return None


def _hyperbook_candidates() -> Iterable[str]:
    seen: set[str] = set()
    offset = 0
    item_re = re.compile(
        r"<h3[^>]*><a[^>]+href=['\"]file(\d+)['\"][^>]*>(.*?)</h3>"
        r"(.*?)"
        r"(?=<h3|<div style=['\"]margin-top:28px;['\"]|$)",
        re.DOTALL,
    )
    para_re = re.compile(r"Параграфов:\s*(\d+)")
    com_re = re.compile(r"комментарии \((\d+)\)")
    star_re = re.compile(r"<span style=['\"]color:#999999['\"]>(\*+)</span>")

    while True:
        catalog_url = f"{HYPERBOOK_LIBRARY_URL}?sort=time&from={offset}"
        html = FetchUrlToString(catalog_url, use_cache=False)
        items = item_re.findall(html)
        if not items:
            break
        for gid, _title, body in items:
            para_m = para_re.search(body)
            paras = int(para_m.group(1)) if para_m else 0
            com_m = com_re.search(body)
            coms = int(com_m.group(1)) if com_m else 0
            star_m = star_re.search(body)
            rating = len(star_m.group(1)) if star_m else 0
            has_award = "medal" in body

            if has_award or rating > 0 or (paras >= 20 and coms >= 2):
                game_url = f"https://hyperbook.ru/comments.php?id={gid}"
                if game_url not in seen:
                    seen.add(game_url)
                    yield game_url
        offset += len(items)


def _parse_hyperbook_personalities(raw_text: str) -> dict[str, list[str]]:
    text = unescape(raw_text).strip()
    role_pattern = (
        r"(Автор|Художник|Редактор|Переводчик|Программист|Композитор)"
        r"\s*[:–-]\s*"
    )
    parts = re.split(role_pattern, text)
    personalities: dict[str, list[str]] = {}
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            role_label = parts[i]
            names_str = parts[i + 1].strip()
            if role_label == "Автор":
                role = "author"
            elif role_label == "Художник":
                role = "artist"
            elif role_label == "Переводчик":
                role = "translator"
            elif role_label == "Программист":
                role = "programmer"
            elif role_label == "Композитор":
                role = "composer"
            else:
                role = "member"
            for name in re.split(r"[,;]|\s+и\s+|\s+&\s+", names_str):
                name = name.strip()
                if name:
                    personalities.setdefault(role, []).append(name)
    else:
        for name in re.split(r"[,;]|\s+&\s+", text):
            name = name.strip()
            if name:
                personalities.setdefault("author", []).append(name)
    return personalities


def _hyperbook_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        return datetime.datetime.strptime(date_str, "%d.%m.%y").strftime(
            "%Y-%m-%d"
        )
    except ValueError:
        return None


def _hyperbook_game_info(html: str, url: str) -> GameInfo:
    gid = _hyperbook_game_id(url)
    if not gid:
        raise ValueError(f"Game ID not found in Hyperbook URL: {url}")

    content = re.split(r"<h3[^>]*>\s*Комментари", html)[0]

    h1_match = HYPERBOOK_H1_RE.search(content)
    if not h1_match:
        raise ValueError(f"Game not found on Hyperbook page: {url}")

    h1_raw = h1_match.group(1)
    name = (
        unescape(re.sub(r"<[^>]+>", "", h1_raw.split("<span")[0]))
        .replace("\xa0", " ")
        .strip()
    )

    version_text = None
    if vm := re.search(r">v([^<]+)<", h1_raw):
        version_text = f"v{vm.group(1).strip()}"

    date = None
    date_match = HYPERBOOK_DATE_RE.search(content)
    if date_match:
        date = _hyperbook_date(date_match.group(1))

    idx_dl = content.find(f"download.php?id={gid}")
    if idx_dl == -1:
        idx_dl = content.find("download.php")
    desc_section = content[idx_dl:] if idx_dl != -1 else content
    desc_match = re.search(
        r"<div class=['\"]small['\"]>(.*?)</div>", desc_section, re.DOTALL
    )
    description = None
    if desc_match:
        tt = HTML2Text()
        tt.body_width = 0
        desc_text = tt.handle(desc_match.group(1)).strip()
        awards_match = re.search(
            r"<span class=['\"]accentsmall['\"]>Награды</span><br>(.*?)</p>",
            desc_section,
            re.DOTALL,
        )
        if awards_match:
            awards_raw = re.sub(r"<img[^>]*>", "", awards_match.group(1))
            award_lines = [
                unescape(line.strip())
                for line in re.split(r"<br\s*/?>", awards_raw)
                if line.strip()
            ]
            if award_lines:
                desc_text += "\n\n**Награды:**\n" + "\n".join(
                    f"- {line}" for line in award_lines
                )
        if desc_text:
            description = desc_text

    info = GameInfo(
        name=name,
        date=date,
        description=description,
        attributions=[Attribution(None, "hyperbook.ru")],
    )

    author_match = HYPERBOOK_AUTHOR_DIV_RE.search(content)
    if author_match:
        for role, names in _parse_hyperbook_personalities(
            author_match.group(1)
        ).items():
            info.personalities[role] = [Person(None, n) for n in names]

    info.tags.append(Tag("platform", None, None, "AXMA Story Maker"))
    info.tags.append(Tag("language", None, None, "русский"))

    if version_text:
        info.tags.append(Tag("version", None, None, version_text))

    for genre in HYPERBOOK_GENRE_RE.findall(desc_section):
        tag_name = unescape(genre.strip()).lower()
        if tag_name:
            info.tags.append(Tag("tag", None, None, tag_name))

    info.urls.append(
        GameUrl(
            "game_page",
            None,
            "Страница на hyperbook.ru",
            f"https://hyperbook.ru/comments.php?id={gid}",
        )
    )
    info.urls.append(
        GameUrl(
            "play_online",
            None,
            "Играть онлайн",
            f"https://hyperbook.ru/file{gid}",
        )
    )
    info.urls.append(
        GameUrl(
            "download_direct",
            None,
            "Скачать с hyperbook.ru",
            f"https://hyperbook.ru/download.php?id={gid}",
        )
    )

    return info


class HyperbookProvider(GameSourceProvider):
    source_type = GameSource.SourceType.HYPERBOOK

    def owns(self, url: str) -> bool:
        return bool(HYPERBOOK_GAME_URL.match(url))

    def fetch(self, url: str) -> str:
        return FetchUrlToString(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        return _hyperbook_game_info(raw, url)

    def discover(self) -> Iterable[DiscoveredSource]:
        return (DiscoveredSource(url) for url in _hyperbook_candidates())

    def source_key(self, url: str) -> str:
        gid = _hyperbook_game_id(url)
        return f"hyperbook:id={gid}" if gid else _base_source_key(url)


# Mirrors the legacy ``REGISTERED_IMPORTERS``.
REGISTERED_PROVIDERS: list[GameSourceProvider] = [
    AperoProvider(),
    IfwikiProvider(),
    InsteadGamesProvider(),
    QuestBookProvider(),
    IfictionProvider(),
    QspSuProvider(),
    PlutProvider(),
    RilarhivProvider(),
    AxmaProvider(),
    HyperbookProvider(),
]

PROVIDER_BY_TYPE: dict[str, GameSourceProvider] = {
    provider.source_type: provider for provider in REGISTERED_PROVIDERS
}
