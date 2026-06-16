from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from logging import getLogger
from threading import Lock
from time import monotonic, sleep

from django.db import close_old_connections
from django.db.models import Count, F
from django.utils.timezone import now

from .models import GameHistory, GameSource, GameSourceFetch
from .providers import PROVIDER_BY_TYPE

logger = getLogger("worker")


@dataclass(frozen=True)
class FetchStats:
    source_type: str
    processed: int
    ok: int
    failed: int
    created: int
    unchanged: int


@dataclass
class _FetchTotals:
    source_type: str
    processed: int = 0
    ok: int = 0
    failed: int = 0
    created: int = 0
    unchanged: int = 0

    def as_stats(self) -> FetchStats:
        return FetchStats(
            source_type=self.source_type,
            processed=self.processed,
            ok=self.ok,
            failed=self.failed,
            created=self.created,
            unchanged=self.unchanged,
        )


SourceDone = Callable[[GameSource, str, str | None], None]


@dataclass(frozen=True)
class _FetchResult:
    source: GameSource
    fetched_at: object
    outcome: str
    raw: str | None = None
    canonical: str | None = None
    canonical_hash: str | None = None
    error: str | None = None


class _RateLimiter:
    def __init__(self, delay: float):
        self.delay = max(delay, 0)
        self.next_fetch_by_type: dict[str, float] = {}
        self.lock = Lock()

    def wait(self, source_type: str):
        if not self.delay:
            return
        with self.lock:
            current = monotonic()
            next_fetch = self.next_fetch_by_type.get(source_type, current)
            wait_for = max(next_fetch - current, 0)
            self.next_fetch_by_type[source_type] = (
                max(current, next_fetch) + self.delay
            )
        if wait_for:
            sleep(wait_for)


def _fetch_remote(
    source: GameSource, rate_limiter: _RateLimiter
) -> _FetchResult:
    source_type = source.type
    provider = PROVIDER_BY_TYPE[source_type]
    fetched_at = now()

    try:
        rate_limiter.wait(source_type)
        raw = provider.fetch(source.url or "")
        info = provider.canonicalize(raw, source.url or "")
        canonical = info.to_canonical()
        canonical_hash = sha256(canonical.encode()).hexdigest()
        return _FetchResult(
            source,
            fetched_at,
            "fetched",
            raw=raw,
            canonical=canonical,
            canonical_hash=canonical_hash,
        )
    except Exception as exc:
        logger.exception("Source fetch failed for #%s", source.pk)
        return _FetchResult(source, fetched_at, "failed", error=str(exc))


def _save_fetch_result(result: _FetchResult) -> _FetchResult:
    source = result.source
    source.last_attempt = result.fetched_at

    if result.outcome == "failed":
        if source.failing_since is None:
            source.failing_since = result.fetched_at
        source.last_error = result.error
        source.save(
            update_fields=[
                "last_attempt",
                "failing_since",
                "last_error",
            ]
        )
        return result

    source.failing_since = None
    source.last_error = None
    source.save(
        update_fields=[
            "last_attempt",
            "failing_since",
            "last_error",
        ]
    )

    latest = source.gamesourcefetch_set.order_by("-last_fetch").first()
    if latest and latest.canonical_text_hash == result.canonical_hash:
        latest.last_fetch = result.fetched_at
        latest.save(update_fields=["last_fetch"])
        return _FetchResult(source, result.fetched_at, "unchanged")

    GameSourceFetch.objects.create(
        source=source,
        raw_content=result.raw or "",
        canonical_text=result.canonical or "",
        canonical_text_hash=result.canonical_hash or "",
        first_fetch=result.fetched_at,
        last_fetch=result.fetched_at,
    )
    return _FetchResult(source, result.fetched_at, "created")


def _thread_fetch_remote(
    source: GameSource, rate_limiter: _RateLimiter
) -> _FetchResult:
    close_old_connections()
    try:
        return _fetch_remote(source, rate_limiter)
    finally:
        close_old_connections()


def run_fetch(
    types: list[str] | None = None,
    limit: int | None = None,
    source_id: int | None = None,
    url: str | None = None,
    on_source_done: SourceDone | None = None,
    threads: int = 1,
    rate_limit: float = 0,
) -> list[FetchStats]:
    wanted = set(types or [])
    source_types = [
        source_type
        for source_type in PROVIDER_BY_TYPE
        if not wanted or source_type in wanted
    ]
    sources = (
        GameSource.objects
        .filter(type__in=source_types)
        .exclude(history__state=GameHistory.State.ABANDONED)
        .exclude(url__isnull=True)
        .exclude(url="")
        .annotate(fetch_count=Count("gamesourcefetch"))
        .order_by(
            F("last_attempt").asc(nulls_first=True),
            "fetch_count",
            F("history").asc(nulls_first=True),
        )
    )
    if source_id is not None:
        sources = sources.filter(pk=source_id)
    if url is not None:
        sources = sources.filter(url=url)
    if limit is not None:
        sources = sources[:limit]

    logger.info("Starting source fetch")
    totals_by_type: dict[str, _FetchTotals] = {}

    rate_limiter = _RateLimiter(rate_limit)
    if threads <= 1:
        results = (_fetch_remote(source, rate_limiter) for source in sources)
    else:
        source_list = list(sources)
        with ThreadPoolExecutor(max_workers=threads) as executor:
            results = list(
                executor.map(
                    lambda s: _thread_fetch_remote(s, rate_limiter),
                    source_list,
                )
            )

    for remote_result in results:
        result = _save_fetch_result(remote_result)
        source = result.source
        source_type = source.type
        totals = totals_by_type.setdefault(
            source_type, _FetchTotals(source_type)
        )
        totals.processed += 1
        if result.outcome == "failed":
            totals.failed += 1
            if on_source_done is not None:
                on_source_done(source, "failed", result.error)
            continue

        totals.ok += 1
        if result.outcome == "unchanged":
            totals.unchanged += 1
        else:
            totals.created += 1
        if on_source_done is not None:
            on_source_done(source, result.outcome, None)

    stats = [totals.as_stats() for totals in totals_by_type.values()]
    summary = ", ".join(
        f"{item.source_type}={item.ok}/{item.processed}" for item in stats
    )
    logger.info("Source fetch complete: %s", summary or "no sources")
    return stats
