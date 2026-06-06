"""Phase 3 (reconcile): cluster fetched orphan sources into histories.

Each fetched orphan ``GameSource`` (``history IS NULL``) is matched against
the full corpus of existing/earlier-spawned histories and either linked
to one or used to spawn a fresh ``game=None`` history.  This is a faithful port
of the old ``GameSet``/``TryMerge`` matching logic in
``games/tasks/game_importer.py``, run over canonical ``GameInfo`` documents
instead of live fetches.  Reconcile only *links*; building the ``GameEdit`` and
applying changes is Phase 4.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from logging import getLogger

from django.utils.timezone import now

from games.importer.tools import ComputeSimilarity, GetBagOfWords, HashizeUrl

from .gameinfo import parse
from .models import (
    GameHistory,
    GameHistoryAuditLog,
    GameSource,
    GameSourceFetch,
)
from .providers import PROVIDER_BY_TYPE

logger = getLogger("worker")

URLCATS_TO_HASH = [
    "game_page",
    "download_direct",
    "download_landing",
    "play_online",
]
SIMILAR_TITLES_HIGHCONF = 0.9
SIMILAR_TITLES_LOWCONF = 0.67


@dataclass(frozen=True)
class ReconcileStats:
    source_type: str
    processed: int  # orphans with a fetch that we tried to match
    skipped_no_fetch: int  # orphan never fetched (or no usable signal)
    attached: int  # linked to an existing/earlier-spawned history
    spawned: int  # new game=None histories created this run
    ambiguous: int  # matched >=2 histories -> left orphan + flagged


@dataclass
class _ReconcileTotals:
    source_type: str
    processed: int = 0
    skipped_no_fetch: int = 0
    attached: int = 0
    spawned: int = 0
    ambiguous: int = 0

    def as_stats(self) -> ReconcileStats:
        return ReconcileStats(
            source_type=self.source_type,
            processed=self.processed,
            skipped_no_fetch=self.skipped_no_fetch,
            attached=self.attached,
            spawned=self.spawned,
            ambiguous=self.ambiguous,
        )


# outcome in {"attached", "spawned", "ambiguous", "skipped"}
SourceDone = Callable[[GameSource, str, GameHistory | None], None]


@dataclass(eq=False)  # identity-hashable: targets live in sets/dict values
class _Target:
    """A history plus the URL/title signals an orphan can match against."""

    history: GameHistory
    hash_urls: set[str]
    title_bow: set[str]
    is_new: bool = False  # spawned this run, so still growable


@dataclass
class _TargetIndex:
    targets: list[_Target] = field(default_factory=list)
    url_to_target: dict[str, _Target] = field(default_factory=dict)

    def add(self, target: _Target) -> None:
        """Register a target; first writer wins on a hash-url collision."""
        self.register_urls(target, target.hash_urls)
        self.targets.append(target)

    def register_urls(self, target: _Target, hash_urls: set[str]) -> None:
        for h in hash_urls:
            if h in self.url_to_target:
                logger.warning("Duplicate identity URL %s", h)
                continue
            self.url_to_target[h] = target

    def match(
        self, hash_urls: set[str], title_bow: set[str]
    ) -> tuple[_Target | None, set[_Target]]:
        """Faithful ``TryMerge`` port: URL identity first, then title floor."""
        candidates = {
            self.url_to_target[h] for h in hash_urls if h in self.url_to_target
        }
        if not candidates:
            candidates = {
                t
                for t in self.targets
                if ComputeSimilarity(t.title_bow, title_bow)
                > SIMILAR_TITLES_HIGHCONF
            }
        best, best_sim = None, 0.0
        for cand in candidates:
            sim = ComputeSimilarity(title_bow, cand.title_bow)
            if best is None or sim > best_sim:
                best, best_sim = cand, sim

        if best is None or best_sim <= SIMILAR_TITLES_LOWCONF:
            return None, candidates
        return best, candidates


def _latest_fetch(source: GameSource) -> GameSourceFetch | None:
    return source.gamesourcefetch_set.order_by("-last_fetch").first()


def _signals(
    source: GameSource, fetch: GameSourceFetch
) -> tuple[set[str], set[str]]:
    """Identity-url hashes + title bag-of-words from a canonical doc."""
    info = parse(fetch.canonical_text)
    hash_urls = {
        HashizeUrl(u.url)
        for u in info.urls
        if u.category in URLCATS_TO_HASH and u.url
    }
    # Fold in the page url so a source whose only signal is itself can match.
    if source.url:
        hash_urls.add(HashizeUrl(source.url))
    return hash_urls, GetBagOfWords(info.name or "")


def _record_source_attached(source: GameSource, history: GameHistory) -> None:
    GameHistoryAuditLog.objects.create(
        history=history,
        actor=None,
        created_at=now(),
        kind=GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED,
        new_id=source.pk,
        new_text=f"{source.type}: {source.url or '(no url)'}",
    )


def _mark_needs_attention(history: GameHistory, reason: str) -> None:
    old_state = history.state
    old_note = history.note
    history.state = GameHistory.State.NEEDS_ATTENTION
    if history.note:
        history.note += f"\n{reason}"
    else:
        history.note = reason
    history.save(update_fields=["state", "note"])
    if old_state != history.state:
        GameHistoryAuditLog.record_change(
            history,
            None,
            GameHistoryAuditLog.AuditField.STATE,
            old_state,
            history.state,
        )
    GameHistoryAuditLog.record_note_change(
        history, None, old_note, history.note
    )


def _build_index() -> _TargetIndex:
    """Load the full corpus into a matchable index, once per run."""
    index = _TargetIndex()

    existing = (
        GameHistory.objects
        .filter(game__isnull=False)
        .exclude(state=GameHistory.State.ABANDONED)
        .select_related("game")
        .prefetch_related(
            "game__gameurl_set__category", "game__gameurl_set__url"
        )
    )
    for history in existing:
        game = history.game
        hash_urls = {
            HashizeUrl(gu.url.original_url)
            for gu in game.gameurl_set.all()
            if gu.category.symbolic_id in URLCATS_TO_HASH
        }
        index.add(_Target(history, hash_urls, GetBagOfWords(game.title)))

    # Earlier-spawned histories: union the signals of their fetched sources so
    # a later-run orphan can still cluster onto a history spawned earlier.
    spawned = (
        GameHistory.objects
        .filter(game__isnull=True)
        .exclude(state=GameHistory.State.ABANDONED)
        .prefetch_related("gamesource_set")
    )
    for history in spawned:
        hash_urls: set[str] = set()
        title_bow: set[str] = set()
        fetched = False
        for source in history.gamesource_set.all():
            fetch = _latest_fetch(source)
            if fetch is None:
                continue
            fetched = True
            h, t = _signals(source, fetch)
            hash_urls |= h
            title_bow |= t
        if fetched:
            index.add(_Target(history, hash_urls, title_bow))

    return index


def _has_new_version(source: GameSource, fetch: GameSourceFetch) -> bool:
    history = source.history
    return bool(
        history and history.edit_time and fetch.first_fetch > history.edit_time
    )


def run_reconcile(
    types: list[str] | None = None,
    limit: int | None = None,
    source_id: int | None = None,
    on_source_done: SourceDone | None = None,
) -> list[ReconcileStats]:
    wanted = set(types or [])
    source_types = [
        source_type
        for source_type in PROVIDER_BY_TYPE
        if not wanted or source_type in wanted
    ]

    index = _build_index()

    sources = (
        GameSource.objects
        .filter(type__in=source_types)
        .select_related("history")
        .order_by("id")
    )
    if source_id is not None:
        sources = sources.filter(pk=source_id)
    if limit is not None:
        sources = sources[:limit]

    logger.info("Starting source reconcile")
    totals_by_type: dict[str, _ReconcileTotals] = {}
    for source in sources:
        totals = totals_by_type.setdefault(
            source.type, _ReconcileTotals(source.type)
        )

        fetch = _latest_fetch(source)
        if fetch is None:
            totals.skipped_no_fetch += 1
            if on_source_done is not None:
                on_source_done(source, "skipped", None)
            continue

        if source.history_id is not None:
            if source.history.state == GameHistory.State.ABANDONED:
                continue
            if _has_new_version(source, fetch):
                source.history.state = GameHistory.State.SCHEDULED_FOR_UPDATE
                source.history.save(update_fields=["state"])
                totals.processed += 1
                if on_source_done is not None:
                    on_source_done(source, "updated", source.history)
            continue

        hash_urls, title_bow = _signals(source, fetch)
        if not hash_urls and not title_bow:  # no signal -> don't spawn a ghost
            totals.skipped_no_fetch += 1
            if on_source_done is not None:
                on_source_done(source, "skipped", None)
            continue

        totals.processed += 1
        target, candidates = index.match(hash_urls, title_bow)
        ambiguous = len(candidates) > 1

        if ambiguous and target is not None:
            source.history = target.history
            source.save(update_fields=["history"])
            _record_source_attached(source, target.history)
            _mark_needs_attention(
                target.history,
                f"Источник #{source.pk} присоединён неоднозначно",
            )
            for candidate in candidates - {target}:
                _mark_needs_attention(
                    candidate.history,
                    f"Источник #{source.pk} похож на эту игру",
                )
            if target.is_new:  # grow so later same-run orphans cluster onto it
                index.register_urls(target, hash_urls)
                target.hash_urls |= hash_urls
                target.title_bow |= title_bow
            logger.warning(
                "Source #%s matched multiple histories; "
                "attached to best guess",
                source.pk,
            )
            totals.ambiguous += 1
            totals.attached += 1
            if on_source_done is not None:
                on_source_done(source, "ambiguous", target.history)
            continue

        if target is not None:
            source.history = target.history
            source.save(update_fields=["history"])
            _record_source_attached(source, target.history)
            if target.is_new:  # grow so later same-run orphans cluster onto it
                index.register_urls(target, hash_urls)
                target.hash_urls |= hash_urls
                target.title_bow |= title_bow
            totals.attached += 1
            if on_source_done is not None:
                on_source_done(source, "attached", target.history)
            continue

        history = GameHistory.objects.create(
            game=None,
            state=GameHistory.State.SCHEDULED_FOR_UPDATE,
            creation_time=now(),
        )
        source.history = history
        source.save(update_fields=["history"])
        _record_source_attached(source, history)
        index.add(
            _Target(history, set(hash_urls), set(title_bow), is_new=True)
        )
        totals.spawned += 1
        if on_source_done is not None:
            on_source_done(source, "spawned", history)

    stats = [totals.as_stats() for totals in totals_by_type.values()]
    summary = ", ".join(
        f"{item.source_type}={item.attached}+{item.spawned}/{item.processed}"
        for item in stats
    )
    logger.info("Source reconcile complete: %s", summary or "no sources")
    return stats
