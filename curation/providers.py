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

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field

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
]

PROVIDER_BY_TYPE: dict[str, GameSourceProvider] = {
    provider.source_type: provider for provider in REGISTERED_PROVIDERS
}
