"""Phase 4 (edit): turn a history's gathered source canonicals into a GameEdit.

For each ``IN_PROGRESS`` history we build a mutable ``GameInfo`` draft seeded
from the currently served game, run it through the ordered list of
``GameEditPass`` mutators named in ``settings.CURATION_EDIT_PASSES``, then diff
the draft against what is already served. Unchanged drafts settle silently;
changed drafts become a ``GameEdit`` that is applied / proposed / rejected per
the history's ``auto_updates`` policy.

Concrete passes live in the ``passes`` package and register themselves into
``PASS_REGISTRY`` via ``@register_pass``; the runner resolves them by name at
run time. The first real pass, ``merge_sources``, reproduces the old
``games/tasks/game_importer.py`` reimport: fold the history's source canonicals
by priority into a fresh ``GameInfo`` (``MergeImport`` reborn). Later
enrichment / LLM passes slot into the same registry.
"""

import copy
import enum
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from logging import getLogger
from typing import Any, ClassVar

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.timezone import now

from .gameinfo import GameInfo, parse
from .models import (
    GameEdit,
    GameHistory,
    GameHistoryAuditLog,
    GameSource,
    GameSourceFetch,
)

logger = getLogger("worker")


class SourceStatus(enum.Enum):
    NEW = enum.auto()
    CHANGED = enum.auto()
    UNCHANGED = enum.auto()
    DISAPPEARED = enum.auto()


class Approval(enum.Enum):
    PROPOSED = enum.auto()
    APPLIED = enum.auto()
    REJECTED = enum.auto()
    CANCELLED = enum.auto()


_APPROVAL_BY_AUTO_UPDATE = {
    GameHistory.AutoUpdate.ACCEPT: Approval.APPLIED,
    GameHistory.AutoUpdate.PROPOSE: Approval.PROPOSED,
    GameHistory.AutoUpdate.REJECT: Approval.REJECTED,
}
_EDIT_STATUS_BY_APPROVAL = {
    Approval.PROPOSED: GameEdit.EditStatus.PROPOSED,
    Approval.APPLIED: GameEdit.EditStatus.APPLIED,
    Approval.REJECTED: GameEdit.EditStatus.REJECTED,
}


@dataclass
class SourceFetchInfo:
    url: str | None
    type: str
    raw_content: str | None
    canonical_text: str | None
    previous_raw_content: str | None
    previous_canonical_text: str | None
    status: SourceStatus
    # current fetch row, for used_sources; None if DISAPPEARED
    fetch: GameSourceFetch | None


@dataclass
class GameEditState:
    history: GameHistory
    current: GameInfo  # mutable draft; seeded from served (or empty)
    approval: Approval  # seeded from auto_updates
    served: GameInfo  # pristine from_game(game) / empty
    last_applied: GameInfo  # parse(last applied edit canonical) / empty
    sources: list[SourceFetchInfo]
    # passes may also mutate these:
    attention_reason: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EditPassSpec:
    name: str
    params: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, **self.params}


class GameEditPass(ABC):
    name: ClassVar[str]  # registry key, also recorded into GameEdit.passes

    @abstractmethod
    def apply(self, state: GameEditState, params: dict[str, Any]) -> None:
        """Mutate the state in place."""


PASS_REGISTRY: dict[str, GameEditPass] = {}


def register_pass(cls):
    PASS_REGISTRY[cls.name] = cls()
    return cls


def normalize_pass_specs(items) -> list[EditPassSpec]:
    specs = []
    for item in items:
        if isinstance(item, str):
            specs.append(EditPassSpec(item, {}))
            continue
        if not isinstance(item, dict):
            raise TypeError(f"Invalid curation edit pass spec: {item!r}")
        try:
            name = item["name"]
        except KeyError as e:
            raise ValueError(
                f"Curation edit pass spec has no name: {item!r}"
            ) from e
        if not isinstance(name, str):
            raise TypeError(
                f"Curation edit pass name must be a string: {item!r}"
            )
        specs.append(
            EditPassSpec(name, {k: v for k, v in item.items() if k != "name"})
        )
    return specs


@dataclass(frozen=True)
class EditStats:
    processed: int
    unchanged: int
    cancelled: int
    applied: int
    proposed: int
    rejected: int
    errors: int


@dataclass
class _EditTotals:
    processed: int = 0
    unchanged: int = 0
    cancelled: int = 0
    applied: int = 0
    proposed: int = 0
    rejected: int = 0
    errors: int = 0

    def record(self, outcome: str) -> None:
        self.processed += 1
        setattr(self, outcome, getattr(self, outcome) + 1)

    def as_stats(self) -> EditStats:
        return EditStats(
            processed=self.processed,
            unchanged=self.unchanged,
            cancelled=self.cancelled,
            applied=self.applied,
            proposed=self.proposed,
            rejected=self.rejected,
            errors=self.errors,
        )


# outcome in {"unchanged", "cancelled", "applied", "proposed", "rejected"}
HistoryDone = Callable[[GameHistory, str], None]


def _latest_fetch(source: GameSource) -> GameSourceFetch | None:
    return source.gamesourcefetch_set.order_by("-last_fetch").first()


def _last_applied_edit(history: GameHistory) -> GameEdit | None:
    return (
        history.gameedit_set
        .filter(status=GameEdit.EditStatus.APPLIED)
        .order_by("-approved_at", "-proposed_at", "-id")
        .first()
    )


def _build_sources(
    history: GameHistory, last_edit: GameEdit | None
) -> list[SourceFetchInfo]:
    """Pair each current source fetch with the last-applied one it supersedes.

    ``NEW`` when the source had no prior fetch in the last applied edit,
    ``UNCHANGED`` / ``CHANGED`` by canonical-hash comparison otherwise, and
    ``DISAPPEARED`` for previously-used sources with no current fetch.
    """
    previous: dict[int, GameSourceFetch] = {}
    if last_edit is not None:
        for fetch in last_edit.used_sources.select_related("source").all():
            kept = previous.get(fetch.source_id)
            if kept is None or fetch.last_fetch > kept.last_fetch:
                previous[fetch.source_id] = fetch

    sources: list[SourceFetchInfo] = []
    covered: set[int] = set()
    for source in history.gamesource_set.all():
        fetch = _latest_fetch(source)
        if fetch is None:
            continue
        covered.add(source.id)
        prev = previous.get(source.id)
        if prev is None:
            status = SourceStatus.NEW
        elif prev.canonical_text_hash == fetch.canonical_text_hash:
            status = SourceStatus.UNCHANGED
        else:
            status = SourceStatus.CHANGED
        sources.append(
            SourceFetchInfo(
                url=source.url,
                type=source.type,
                raw_content=fetch.raw_content,
                canonical_text=fetch.canonical_text,
                previous_raw_content=prev.raw_content if prev else None,
                previous_canonical_text=(
                    prev.canonical_text if prev else None
                ),
                status=status,
                fetch=fetch,
            )
        )

    for source_id, prev in previous.items():
        if source_id in covered:
            continue
        sources.append(
            SourceFetchInfo(
                url=prev.source.url,
                type=prev.source.type,
                raw_content=None,
                canonical_text=None,
                previous_raw_content=prev.raw_content,
                previous_canonical_text=prev.canonical_text,
                status=SourceStatus.DISAPPEARED,
                fetch=None,
            )
        )
    return sources


def _build_state(
    history: GameHistory,
) -> GameEditState:
    served = (
        GameInfo.from_game(history.game)
        if history.game is not None
        else GameInfo()
    )
    last_edit = _last_applied_edit(history)
    last_applied = parse(last_edit.canonical_text) if last_edit else GameInfo()
    attention_reason = []
    if history.auto_updates is GameHistory.AutoUpdate.PROPOSE:
        attention_reason.append("Автообновление отключено")

    state = GameEditState(
        history=history,
        current=copy.deepcopy(served),
        approval=_APPROVAL_BY_AUTO_UPDATE[history.auto_updates],
        served=served,
        last_applied=last_applied,
        sources=_build_sources(history, last_edit),
        attention_reason=attention_reason,
    )
    return state


def _flush(history: GameHistory, state: GameEditState) -> None:
    """Persist pass-mutable history fields (audited) and settle ``state``."""
    history.attention_reason = "\n".join(state.attention_reason) or None
    history.edit_time = now()
    history.save()


def _process_history(history: GameHistory) -> str:
    state = _build_state(history)
    maintenance_user, _ = get_user_model().objects.get_or_create(
        username=settings.MAINTENANCE_USER,
        defaults={"email": "robot@db.crem.xyz"},
    )
    pass_specs = normalize_pass_specs(settings.CURATION_EDIT_PASSES)
    for spec in pass_specs:
        PASS_REGISTRY[spec.name].apply(state, spec.params)
        state.current.canonicalize()

    final = state.current.to_canonical()
    base = state.served.to_canonical()

    if final == base:
        history.state = GameHistory.State.SETTLED
        outcome = "unchanged"
    elif state.approval is Approval.CANCELLED:
        history.state = GameHistory.State.SETTLED
        outcome = "cancelled"
    else:
        edit = GameEdit.objects.create(
            history=history,
            proposed_at=now(),
            proposed_by=maintenance_user,
            origin=GameEdit.Origin.AUTO_IMPORT,
            status=_EDIT_STATUS_BY_APPROVAL[state.approval],
            passes=[spec.as_json() for spec in pass_specs],
            previous_canonical_text=(
                None if state.approval is Approval.PROPOSED else base
            ),
            canonical_text=final,
        )
        edit.used_sources.set([s.fetch for s in state.sources if s.fetch])

        if state.approval is Approval.APPLIED:
            before = base
            game, after = state.current.save(history.game)
            if after != final:
                edit.canonical_text = after
            edit.approved_at = now()
            edit.approver = maintenance_user
            edit.save(
                update_fields=["canonical_text", "approved_at", "approver"]
            )
            if history.game is None:
                history.game = game
            GameHistoryAuditLog.record_change(
                history,
                None,
                GameHistoryAuditLog.AuditField.CANONICAL_TEXT,
                before,
                after,
            )
            history.state = GameHistory.State.SETTLED
            outcome = "applied"
        elif state.approval is Approval.PROPOSED:
            history.state = GameHistory.State.NEEDS_ATTENTION
            outcome = "proposed"
        else:  # REJECTED
            history.state = GameHistory.State.SETTLED
            outcome = "rejected"

    _flush(history, state)
    return outcome


def run_edit(
    history_id: int | None = None,
    limit: int | None = None,
    on_history_done: HistoryDone | None = None,
) -> EditStats:
    histories = GameHistory.objects.filter(
        state=GameHistory.State.IN_PROGRESS
    ).order_by("id")
    if history_id is not None:
        histories = histories.filter(pk=history_id)
    if limit is not None:
        histories = histories[:limit]

    logger.info("Starting source edit")
    totals = _EditTotals()
    for history in histories:
        try:
            with transaction.atomic():
                outcome = _process_history(history)
        except Exception:
            logger.exception("Edit failed for history #%s", history.pk)
            totals.errors += 1
            if on_history_done is not None:
                on_history_done(history, "error")
            continue
        totals.record(outcome)
        if on_history_done is not None:
            on_history_done(history, outcome)

    stats = totals.as_stats()
    logger.info(
        "Source edit complete: %s processed, %s applied, %s proposed, "
        "%s rejected, %s unchanged, %s cancelled, %s errors",
        stats.processed,
        stats.applied,
        stats.proposed,
        stats.rejected,
        stats.unchanged,
        stats.cancelled,
        stats.errors,
    )
    return stats


# Imported for its registration side effects: each pass populates PASS_REGISTRY
# via @register_pass on import.
from . import passes  # noqa: E402,F401
