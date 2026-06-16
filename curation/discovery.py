from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from logging import getLogger

from django.utils.timezone import now

from .models import GameSource, SourceDiscoveryStatus
from .providers import REGISTERED_PROVIDERS

logger = getLogger("worker")


@dataclass(frozen=True)
class DiscoveryStats:
    source_type: str
    candidates: int
    discovered: int
    new_ids: list[int]
    existing_ids: list[int]
    absent_ids: list[int]
    newly_missing_ids: list[int]
    unused_ids: list[int]
    duplicate_id_clusters: list[list[int]]


ProviderDone = Callable[[DiscoveryStats], None]


def run_discover(
    types: list[str] | None = None,
    on_provider_done: ProviderDone | None = None,
) -> Counter[str]:
    wanted = set(types or [])
    providers = [
        provider
        for provider in REGISTERED_PROVIDERS
        if not wanted or provider.source_type in wanted
    ]

    logger.info("Starting source discovery for %d providers", len(providers))
    created_by_type: Counter[str] = Counter()

    for provider in providers:
        source_type = provider.source_type
        candidates = 0
        new_ids: list[int] = []
        ts = now()
        logger.info("Discovering %s", source_type)

        # Snapshot rows (id + identity key + missing flag) before the
        # loop: legacy seeded rows and earlier-created orphans both count as
        # ``existing``, while same-run duplicates are caught by
        # ``discovered_keys``.
        existing_rows = list(
            GameSource.objects
            .filter(type=source_type)
            .exclude(url="")
            .exclude(url__isnull=True)
            .values("id", "url", "missing_since")
        )
        existing_keys = {provider.source_key(r["url"]) for r in existing_rows}
        discovered_keys: set[str] = set()

        try:
            for discovered in provider.discover():
                candidates += 1
                key = provider.source_key(discovered.url)
                if key in discovered_keys:
                    continue
                discovered_keys.add(key)
                if key not in existing_keys:
                    source = GameSource.objects.create(
                        type=source_type, url=discovered.url, created_at=ts
                    )
                    new_ids.append(source.id)
                    created_by_type[source_type] += 1
        except Exception as exc:
            logger.exception("%s discovery failed", source_type)
            SourceDiscoveryStatus.record(
                source_type,
                ts=ts,
                is_error=True,
                error_message=str(exc),
                new_ids=[],
                existing_ids=[],
                absent_ids=[],
                newly_missing_ids=[],
                unused_ids=[],
                duplicate_id_clusters=[],
            )
            continue

        existing_ids, absent_ids, newly_missing_ids = [], [], []
        for r in existing_rows:
            if provider.source_key(r["url"]) in discovered_keys:
                existing_ids.append(r["id"])
            elif r["missing_since"] is None:
                newly_missing_ids.append(r["id"])
            else:
                absent_ids.append(r["id"])

        GameSource.objects.filter(id__in=newly_missing_ids).update(
            missing_since=ts
        )
        GameSource.objects.filter(
            id__in=existing_ids, missing_since__isnull=False
        ).update(missing_since=None)  # rediscovered -> clear flag

        current_rows = list(
            GameSource.objects
            .filter(type=source_type)
            .exclude(url="")
            .exclude(url__isnull=True)
            .values("id", "url", "history_id")
        )
        unused_ids = [r["id"] for r in current_rows if r["history_id"] is None]
        duplicate_groups = defaultdict(list)
        for r in current_rows:
            duplicate_groups[provider.source_key(r["url"])].append(r["id"])
        duplicate_id_clusters = [
            ids for ids in duplicate_groups.values() if len(ids) > 1
        ]

        stats = DiscoveryStats(
            source_type=source_type,
            candidates=candidates,
            discovered=len(discovered_keys),
            new_ids=new_ids,
            existing_ids=existing_ids,
            absent_ids=absent_ids,
            newly_missing_ids=newly_missing_ids,
            unused_ids=unused_ids,
            duplicate_id_clusters=duplicate_id_clusters,
        )
        SourceDiscoveryStatus.record(
            source_type,
            ts=ts,
            is_error=False,
            error_message=None,
            new_ids=new_ids,
            existing_ids=existing_ids,
            absent_ids=absent_ids,
            newly_missing_ids=newly_missing_ids,
            unused_ids=unused_ids,
            duplicate_id_clusters=duplicate_id_clusters,
        )
        logger.info(
            "%s: %d candidates, %d discovered, %d existing, %d new, "
            "%d absent, %d newly missing, %d unused, %d duplicate clusters",
            source_type,
            candidates,
            stats.discovered,
            len(existing_ids),
            len(new_ids),
            len(absent_ids),
            len(newly_missing_ids),
            len(unused_ids),
            len(duplicate_id_clusters),
        )
        if on_provider_done is not None:
            on_provider_done(stats)

    summary = ", ".join(
        f"{source_type}={count}"
        for source_type, count in sorted(created_by_type.items())
    )
    logger.info("Source discovery complete: %s", summary or "no new sources")
    return created_by_type
