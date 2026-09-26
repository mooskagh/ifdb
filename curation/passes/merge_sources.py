"""Merge fetched source canonicals into a draft ``GameInfo``."""

import copy
from dataclasses import dataclass
from difflib import unified_diff
from typing import Iterable

from curation.edit import (
    GameEditPass,
    GameEditState,
    SourceFetchInfo,
    register_pass,
)
from curation.models import GameSource, GameSourceFetch
from games.gameinfo import (
    GameInfo,
    GameUrl,
    _attribution_key,
    _dedup,
    _url_key,
    merge,
    parse,
)
from games.models import URL

# Source priority mirrors the old importers' ``priority`` values
# (games/importer/*.py); higher wins first. Sources without an explicit
# priority (current text, rilarhiv) fall back to ``_DEFAULT_PRIORITY``.
_DEFAULT_PRIORITY = -1000
_SOURCE_PRIORITY = {
    GameSource.SourceType.STICKY_NOTE: 1000,
    GameSource.SourceType.IFWIKI: 100,
    GameSource.SourceType.INSTEAD: 80,
    GameSource.SourceType.AXMA: 70,
    GameSource.SourceType.HYPERBOOK: 70,
    GameSource.SourceType.QUESTBOOK: 51,
    GameSource.SourceType.PLUT: 50,
    GameSource.SourceType.APERO: 49,
    GameSource.SourceType.IFICTION: 45,
    GameSource.SourceType.QSP: 40,
}


def ordered_sources(
    sources: Iterable[SourceFetchInfo],
) -> list[SourceFetchInfo]:
    return sorted(
        sources,
        key=lambda s: _SOURCE_PRIORITY.get(s.type, _DEFAULT_PRIORITY),
        reverse=True,
    )


def description_diff(old: str, new: str) -> str:
    return "\n".join(
        unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile="sources_old",
            tofile="sources_new",
            lineterm="",
        )
    )


def merge_descriptions(fetches: Iterable[GameSourceFetch]) -> str:
    return _merge_descriptions(fetch.canonical_text for fetch in fetches)


def _description(text: str | None) -> str:
    return (parse(text).description or "") if text else ""


def _merge_descriptions(texts: Iterable[str | None]) -> str:
    return "\n\n---\n\n".join(
        description for text in texts if (description := _description(text))
    )


@dataclass(frozen=True)
class SourceDescriptionDelta:
    pairs: list[tuple[GameSourceFetch | None, GameSourceFetch | None]]
    old_ids: list[int]
    new_ids: list[int]
    old: str
    new: str
    diff: str


def build_description_delta(
    sources: Iterable[SourceFetchInfo],
) -> SourceDescriptionDelta:
    pairs = [
        (s.previous_fetch, s.fetch)
        for s in ordered_sources(sources)
        if _description(s.previous_canonical_text)
        != _description(s.canonical_text)
    ]
    old_fetches = [old for old, _ in pairs if old is not None]
    new_fetches = [new for _, new in pairs if new is not None]
    old = merge_descriptions(old_fetches)
    new = merge_descriptions(new_fetches)
    return SourceDescriptionDelta(
        pairs,
        [fetch.pk for fetch in old_fetches],
        [fetch.pk for fetch in new_fetches],
        old,
        new,
        description_diff(old, new),
    )


def _correlate_source_urls_with_current(
    source_urls: list[GameUrl], current_urls: list[GameUrl]
) -> list[GameUrl]:
    if not current_urls or not source_urls:
        return source_urls
    url_ids = {
        u.url_id for u in (*source_urls, *current_urls) if u.url_id is not None
    }
    url_by_id = (
        dict(
            URL.objects.filter(id__in=url_ids).values_list(
                "id", "original_url"
            )
        )
        if url_ids
        else {}
    )
    current_by_key: dict[tuple[str, str], GameUrl] = {}
    current_by_url: dict[str, GameUrl] = {}
    for cu in current_urls:
        k = _url_key(cu, url_by_id)
        current_by_key[k] = cu
        current_by_url[k[1]] = cu

    result: list[GameUrl] = []
    for su in source_urls:
        k = _url_key(su, url_by_id)
        cu = current_by_key.get(k)
        if cu is None:
            same_url_cu = current_by_url.get(k[1])
            if (
                same_url_cu is not None
                and same_url_cu.category != su.category
                and "unknown" in {same_url_cu.category, su.category}
            ):
                cu = same_url_cu
        if cu is not None:
            u = copy.copy(su)
            u.url_id = cu.url_id
            if cu.description:
                u.description = cu.description
                if su.description and su.description != cu.description:
                    u.proposed_description = su.description
            elif su.description:
                u.description = su.description
            result.append(u)
        else:
            result.append(su)
    return result


@register_pass
class MergeSourcesPass(GameEditPass):
    name = "merge_sources"

    def apply(self, state: GameEditState, params: dict) -> None:
        keep_existing = params.get("keep_existing", True)
        usable = [
            s for s in ordered_sources(state.sources) if s.canonical_text
        ]
        if not usable:  # nothing to merge -> keep served draft
            return
        merged = GameInfo()
        for s in usable:  # highest priority first -> first-wins
            merged = merge(merged, parse(s.canonical_text))
        if keep_existing:
            source_name = merged.name
            source_date = merged.date
            if state.current:
                merged.urls = _correlate_source_urls_with_current(
                    merged.urls, state.current.urls
                )
                # Attributions remain append-only
                merged.attributions = _dedup(
                    state.current.attributions + merged.attributions,
                    _attribution_key,
                )
            merged.name = source_name or state.current.name
            merged.date = source_date or state.current.date
            merged.description = state.current.description

        state.current = merged
