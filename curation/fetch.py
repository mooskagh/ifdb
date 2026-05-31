from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from logging import getLogger

from django.db.models import F
from django.utils.timezone import now

from .models import GameSource, GameSourceFetch
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


def run_fetch(
    types: list[str] | None = None,
    limit: int | None = None,
    source_id: int | None = None,
    url: str | None = None,
    on_source_done: SourceDone | None = None,
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
        .exclude(url__isnull=True)
        .exclude(url="")
        .order_by(F("last_attempt").asc(nulls_first=True))
    )
    if source_id is not None:
        sources = sources.filter(pk=source_id)
    if url is not None:
        sources = sources.filter(url=url)
    if limit is not None:
        sources = sources[:limit]

    logger.info("Starting source fetch")
    totals_by_type: dict[str, _FetchTotals] = {}
    for source in sources:
        source_type = source.type
        totals = totals_by_type.setdefault(
            source_type, _FetchTotals(source_type)
        )
        totals.processed += 1
        provider = PROVIDER_BY_TYPE[source_type]
        fetched_at = now()
        source.last_attempt = fetched_at

        try:
            raw = provider.fetch(source.url or "")
            info = provider.canonicalize(raw, source.url or "")
            canonical = info.to_canonical()
            canonical_hash = sha256(canonical.encode()).hexdigest()

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
            if latest and latest.canonical_text_hash == canonical_hash:
                latest.last_fetch = fetched_at
                latest.save(update_fields=["last_fetch"])
                totals.unchanged += 1
                outcome = "unchanged"
            else:
                GameSourceFetch.objects.create(
                    source=source,
                    raw_content=raw,
                    canonical_text=canonical,
                    canonical_text_hash=canonical_hash,
                    first_fetch=fetched_at,
                    last_fetch=fetched_at,
                )
                totals.created += 1
                outcome = "created"
        except Exception as exc:
            logger.exception("Source fetch failed for #%s", source.pk)
            if source.failing_since is None:
                source.failing_since = fetched_at
            source.last_error = str(exc)
            source.save(
                update_fields=[
                    "last_attempt",
                    "failing_since",
                    "last_error",
                ]
            )
            totals.failed += 1
            if on_source_done is not None:
                on_source_done(source, "failed", str(exc))
            continue

        totals.ok += 1
        if on_source_done is not None:
            on_source_done(source, outcome, None)

    stats = [totals.as_stats() for totals in totals_by_type.values()]
    summary = ", ".join(
        f"{item.source_type}={item.ok}/{item.processed}" for item in stats
    )
    logger.info("Source fetch complete: %s", summary or "no sources")
    return stats
