"""Turning URLs (typed in by moderators or found in game links) to sources."""

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from django.db import transaction
from django.utils.timezone import now

from games.gameinfo import GameUrl
from games.models import Game

from .models import GameCuration, GameHistoryAuditLog, GameSource
from .providers import SOURCE_LINK_CATEGORIES, provider_for_url


class Outcome(StrEnum):
    UNKNOWN = "unknown"  # no provider owns the URL
    EXISTS = "exists"  # already a source (of this game, or orphan in bulk add)
    TAKEN = "taken"  # already a source of another game
    ATTACHED = "attached"  # an orphan got attached
    CREATED = "created"  # a new source was created


def matching_sources(url: str) -> list[GameSource] | None:
    """Sources with the same identity key as ``url``; None if not a source."""
    provider = provider_for_url(url)
    if provider is None:
        return None
    key = provider.source_key(url)
    return [
        source
        for source in GameSource.objects.filter(
            type=provider.source_type, url__isnull=False
        ).order_by("pk")
        if provider.source_key(source.url) == key
    ]


def add_orphan_source(url: str) -> tuple[Outcome, GameSource | None]:
    matches = matching_sources(url)
    if matches is None:
        return Outcome.UNKNOWN, None
    if matches:
        return Outcome.EXISTS, matches[0]
    provider = provider_for_url(url)
    assert provider is not None
    return Outcome.CREATED, GameSource.objects.create(
        type=provider.source_type, url=url, created_at=now()
    )


def attach_url_source(
    game: Game, url: str, actor: Any
) -> tuple[Outcome, GameSource | None]:
    matches = matching_sources(url)
    if matches is None:
        return Outcome.UNKNOWN, None
    if own := next((s for s in matches if s.game_id == game.pk), None):
        return Outcome.EXISTS, own
    if orphan := next((s for s in matches if s.game_id is None), None):
        attach_source(game, orphan, actor)
        return Outcome.ATTACHED, orphan
    if matches:
        return Outcome.TAKEN, matches[0]
    provider = provider_for_url(url)
    assert provider is not None
    source = GameSource.objects.create(
        type=provider.source_type, url=url, created_at=now()
    )
    attach_source(game, source, actor)
    return Outcome.CREATED, source


def attach_source(game: Game, source: GameSource, actor: Any) -> None:
    from .tasks import fetch_sources

    source.game = game
    source.save(update_fields=["game"])
    GameHistoryAuditLog.record_source(
        game, actor, GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED, source
    )
    transaction.on_commit(
        lambda: fetch_sources.delay(limit=None, source_id=source.pk)
    )


def is_source_link(category: str, url: str | None) -> bool:
    return bool(
        url and category in SOURCE_LINK_CATEGORIES and provider_for_url(url)
    )


def adopt_link_sources(
    game: Game, urls: Iterable[GameUrl], actor: Any
) -> None:
    """Make source-like game links sources of ``game``.

    Links that are already sources of another game are left alone; the game
    is flagged for a moderator instead.
    """
    taken = []
    for link in urls:
        if not (url := link.url) or not is_source_link(link.category, url):
            continue
        outcome, source = attach_url_source(game, url, actor)
        if outcome == Outcome.TAKEN and source is not None:
            taken.append(f"ссылка {url} — источник игры #{source.game_id}")
    if not taken:
        return
    curation, _ = GameCuration.objects.get_or_create(game=game)
    old_note = curation.note
    curation.state = GameCuration.State.NEEDS_ATTENTION
    curation.note = "\n".join(filter(None, [old_note, *taken]))
    curation.save(update_fields=["state", "note"])
    GameHistoryAuditLog.record_note_change(
        game, actor, old_note, curation.note
    )
