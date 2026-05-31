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

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field

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
from games.importer.qspsu import (
    QSP_RE,
    FetchQsp,
    ParseQsp,
)
from games.importer.qspsu import GetCandidates as GetQspSuCandidates
from games.importer.questbook import (
    QUESTBOOK_GAMEDETAIL_URL,
    FetchQuestBook,
    ParseQuestBook,
)
from games.importer.questbook import GetCandidates as GetQuestBookCandidates
from games.importer.tools import QuoteUtf8

from .gameinfo import GameInfo, GameUrl
from .models import GameSource


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


class QspSuProvider(GameSourceProvider):
    source_type = GameSource.SourceType.QSP

    def owns(self, url: str) -> bool:
        return bool(QSP_RE.match(url))

    def fetch(self, url: str) -> str:
        return FetchQsp(url, use_cache=False)

    def canonicalize(self, raw: str, url: str) -> GameInfo:
        return GameInfo.from_importer_dict(ParseQsp(raw, url))

    def discover(self) -> Iterable[DiscoveredSource]:
        return (DiscoveredSource(url) for url in GetQspSuCandidates())


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


# Mirrors the legacy ``REGISTERED_IMPORTERS``.  rilarhiv is intentionally
# absent: it has no per-game page (data lives in listing rows), so it stays on
# the old path until discover-coupled sources get bespoke handling.
REGISTERED_PROVIDERS: list[GameSourceProvider] = [
    AperoProvider(),
    IfwikiProvider(),
    InsteadGamesProvider(),
    QuestBookProvider(),
    IfictionProvider(),
    QspSuProvider(),
    PlutProvider(),
]

PROVIDER_BY_TYPE: dict[str, GameSourceProvider] = {
    provider.source_type: provider for provider in REGISTERED_PROVIDERS
}
