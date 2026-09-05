"""Phase 4 (edit): turn a history's gathered source canonicals into a
GameRevision.

For each scheduled history we build a mutable ``GameInfo`` draft seeded from
the currently served game, run it through the ordered list of
``GameEditPass`` mutators from the selected ``EditPipeline``, then diff
the draft against what is already served. Unchanged drafts settle silently;
changed drafts become a ``GameRevision`` that is applied / proposed /
rejected per the history's ``auto_updates`` policy.

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
from datetime import timedelta
from logging import getLogger
from typing import Any, ClassVar

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils.timezone import now

from games.gameinfo import GameInfo, parse
from games.importer.discord import PostNewGameToDiscord
from games.models import Game, GameRevision

from .models import (
    EditPipeline,
    GameCuration,
    GameHistoryAuditLog,
    GameSource,
    GameSourceFetch,
    LlmTrajectory,
)

logger = getLogger("worker")
EDIT_LEASE_TIMEOUT = timedelta(minutes=15)


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
    GameCuration.AutoUpdate.ACCEPT: Approval.APPLIED,
    GameCuration.AutoUpdate.PROPOSE: Approval.PROPOSED,
    GameCuration.AutoUpdate.REJECT: Approval.REJECTED,
}
_EDIT_STATUS_BY_APPROVAL = {
    Approval.PROPOSED: GameRevision.Status.PROPOSED,
    Approval.APPLIED: GameRevision.Status.ACCEPTED,
    Approval.REJECTED: GameRevision.Status.REJECTED,
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
    curation: GameCuration | None
    current: GameInfo  # mutable draft; seeded from served (or empty)
    approval: Approval  # seeded from auto_updates
    served: GameInfo  # pristine from_game(game) / empty
    last_applied: GameInfo  # parse(last applied edit canonical) / empty
    sources: list[SourceFetchInfo]
    # passes may also mutate these:
    notes: list[str] = field(default_factory=list)
    needs_attention: bool = False
    last_applied_canonical: str = ""

    @property
    def history(self) -> GameCuration | None:
        return self.curation

    @property
    def game(self) -> Game | None:
        return self.curation.game if self.curation else None

    def add_note(self, note: str | None) -> None:
        if note and note not in self.notes:
            self.notes.append(note)


@dataclass(frozen=True)
class EditPassSpec:
    name: str
    params: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, **self.params}


class GameEditPass(ABC):
    name: ClassVar[str]  # registry key, also recorded into GameRevision.passes

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
HistoryDone = Callable[[GameCuration, str], None]
EditDone = HistoryDone


def _latest_fetch(source: GameSource) -> GameSourceFetch | None:
    return source.gamesourcefetch_set.order_by("-last_fetch").first()


def _last_applied_edit(curation: GameCuration) -> GameRevision | None:
    if curation.game.published_revision_id:
        return curation.game.published_revision
    return (
        curation.game.gamerevision_set
        .filter(status=GameRevision.Status.ACCEPTED)
        .order_by("-published_at", "-created_at", "-id")
        .first()
    )


def _build_sources(
    curation: GameCuration, last_edit: GameRevision | None
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
    for source in curation.game.gamesource_set.all():
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
    curation: GameCuration,
) -> GameEditState:
    last_edit = _last_applied_edit(curation)
    last_applied = parse(last_edit.canonical_text) if last_edit else GameInfo()
    served = copy.deepcopy(last_applied)
    notes = curation.note.splitlines() if curation.note else []
    if curation.auto_updates is GameCuration.AutoUpdate.PROPOSE:
        note = "Автообновление отключено"
        if note not in notes:
            notes.append(note)

    state = GameEditState(
        curation=curation,
        current=copy.deepcopy(served),
        approval=_APPROVAL_BY_AUTO_UPDATE[curation.auto_updates],
        served=served,
        last_applied=last_applied,
        sources=_build_sources(curation, last_edit),
        notes=notes,
        last_applied_canonical=last_edit.canonical_text if last_edit else "",
    )
    return state


def _flush(curation: GameCuration, state: GameEditState, actor) -> None:
    """Persist pass-mutable curation fields (audited) and settle ``state``."""
    old_note = curation.note
    curation.note = "\n".join(state.notes) or None
    GameHistoryAuditLog.record_note_change(
        curation.game, actor, old_note, curation.note
    )
    curation.processing_started_at = None
    curation.processing_task_id = None
    curation.save()


def is_noop_edit(current: GameInfo, served: GameInfo) -> bool:
    return current.to_canonical().rstrip("\n") == served.to_canonical().rstrip(
        "\n"
    )


def _process_history(curation: GameCuration, pipeline: EditPipeline) -> str:
    state = _build_state(curation)
    maintenance_user, _ = get_user_model().objects.get_or_create(
        username=settings.MAINTENANCE_USER,
        defaults={"email": "robot@db.crem.xyz"},
    )
    last_trajectory_id = (
        LlmTrajectory.objects
        .filter(game=curation.game)
        .order_by("-pk")
        .values_list("pk", flat=True)
        .first()
        or 0
    )
    pass_specs = normalize_pass_specs(pipeline.passes)
    for spec in pass_specs:
        PASS_REGISTRY[spec.name].apply(state, spec.params)
        state.current.canonicalize()

    final = state.current.to_canonical()
    base = state.last_applied_canonical
    done_state = (
        GameCuration.State.NEEDS_ATTENTION
        if state.needs_attention
        else GameCuration.State.SETTLED
    )
    created_game_id = None

    if is_noop_edit(state.current, state.served):
        curation.state = done_state
        outcome = "unchanged"
    elif state.approval is Approval.CANCELLED:
        curation.state = done_state
        outcome = "cancelled"
    else:
        edit = GameRevision.objects.create(
            game=curation.game,
            created_at=now(),
            created_by=maintenance_user,
            origin=GameRevision.Origin.AUTO_IMPORT,
            status=_EDIT_STATUS_BY_APPROVAL[state.approval],
            passes=[spec.as_json() for spec in pass_specs],
            previous_canonical_text=(
                None if state.approval is Approval.PROPOSED else base
            ),
            canonical_text=final,
        )
        edit.used_sources.set([s.fetch for s in state.sources if s.fetch])
        LlmTrajectory.objects.filter(
            game=curation.game,
            edit__isnull=True,
            pk__gt=last_trajectory_id,
        ).update(edit=edit)

        if state.approval is Approval.APPLIED:
            created_game = curation.game.state == Game.State.DRAFT
            curation.game.publish_revision(edit, actor=maintenance_user)
            if created_game:
                created_game_id = curation.game.id
            curation.state = done_state
            outcome = "applied"
        elif state.approval is Approval.PROPOSED:
            curation.state = GameCuration.State.NEEDS_ATTENTION
            outcome = "proposed"
        else:  # REJECTED
            curation.state = done_state
            outcome = "rejected"

    _flush(curation, state, maintenance_user)
    if curation.game.state == Game.State.DRAFT and state.approval in {
        Approval.REJECTED,
        Approval.CANCELLED,
    }:
        curation.game.abandon(maintenance_user)
    if created_game_id is not None:
        PostNewGameToDiscord(created_game_id)
    return outcome


def _claim_curation(
    *,
    game_id: int | None = None,
    history_id: int | None = None,
    task_id: str | None,
    attempted_ids: set[int],
    force: bool,
) -> tuple[GameCuration, str] | None:
    target_id = game_id if game_id is not None else history_id
    stale_before = now() - EDIT_LEASE_TIMEOUT
    stale_processing = Q(
        state=GameCuration.State.PROCESSING,
        processing_started_at__lt=stale_before,
    )
    eligible = (
        Q(state=GameCuration.State.SCHEDULED_FOR_UPDATE) | stale_processing
    )
    if force and target_id is not None:
        eligible |= ~Q(state=GameCuration.State.PROCESSING)
    curations = (
        GameCuration.objects
        .filter(eligible)
        .exclude(state=GameCuration.State.ABANDONED)
        .alias(
            orphan_order=Case(
                When(game__state=Game.State.DRAFT, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("orphan_order", "pk")
    )
    if target_id is not None:
        curations = curations.filter(pk=target_id)
    if attempted_ids:
        curations = curations.exclude(pk__in=attempted_ids)

    with transaction.atomic():
        curation = curations.select_for_update(skip_locked=True).first()
        if curation is None:
            return None
        restore_state = (
            curation.state
            if force and curation.state != GameCuration.State.PROCESSING
            else GameCuration.State.SCHEDULED_FOR_UPDATE
        )
        ts = now()
        curation.state = GameCuration.State.PROCESSING
        curation.processing_started_at = ts
        curation.processing_task_id = task_id
        curation.save(
            update_fields=[
                "state",
                "processing_started_at",
                "processing_task_id",
            ]
        )
    return curation, restore_state


_claim_history = _claim_curation


def _release_failed_claim(curation: GameCuration, restore_state: str) -> None:
    GameCuration.objects.filter(
        pk=curation.pk, state=GameCuration.State.PROCESSING
    ).update(
        state=restore_state,
        processing_started_at=None,
        processing_task_id=None,
    )


def run_edit(
    game_id: int | None = None,
    history_id: int | None = None,
    limit: int | None = None,
    pipeline_id: int | None = None,
    task_id: str | None = None,
    force: bool = False,
    on_history_done: HistoryDone | None = None,
) -> EditStats:
    target_id = game_id if game_id is not None else history_id
    pipeline = _resolve_pipeline(pipeline_id)

    logger.info("Starting source edit")
    totals = _EditTotals()
    attempted_ids: set[int] = set()
    while limit is None or len(attempted_ids) < limit:
        claim = _claim_curation(
            game_id=target_id,
            task_id=task_id,
            attempted_ids=attempted_ids,
            force=force,
        )
        if claim is None:
            break
        curation, restore_state = claim
        attempted_ids.add(curation.pk)
        try:
            outcome = _process_history(curation, pipeline)
        except Exception:
            logger.exception("Edit failed for curation #%s", curation.pk)
            _release_failed_claim(curation, restore_state)
            totals.errors += 1
            if on_history_done is not None:
                on_history_done(curation, "error")
            continue
        totals.record(outcome)
        if on_history_done is not None:
            on_history_done(curation, outcome)

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


def _resolve_pipeline(pipeline_id: int | None) -> EditPipeline:
    pipelines = EditPipeline.objects.order_by("id")
    pipeline = (
        pipelines.filter(pk=pipeline_id).first()
        if pipeline_id
        else pipelines.first()
    )
    if pipeline is None:
        raise ValueError("No curation edit pipeline configured.")
    return pipeline


# Imported for its registration side effects: each pass populates PASS_REGISTRY
# via @register_pass on import.
from . import passes  # noqa: E402,F401
