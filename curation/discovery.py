from collections import Counter
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
    existing: int
    new: int
    missing: int


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
        existing = 0
        created = 0
        ts = now()
        logger.info("Discovering %s", source_type)

        # Snapshot existing URLs as identity keys *before* the loop: legacy
        # seeded rows and earlier-created orphans both count as ``existing``,
        # while same-run duplicates are caught by ``discovered_keys``.
        existing_urls = (
            GameSource.objects.filter(type=source_type)
            .exclude(url="")
            .exclude(url__isnull=True)
            .values_list("url", flat=True)
        )
        existing_keys = {provider.source_key(u) for u in existing_urls}
        discovered_keys: set[str] = set()

        try:
            for discovered in provider.discover():
                candidates += 1
                key = provider.source_key(discovered.url)
                if key in discovered_keys:
                    continue
                discovered_keys.add(key)
                if key in existing_keys:
                    existing += 1
                else:
                    GameSource.objects.create(
                        type=source_type, url=discovered.url, created_at=ts
                    )
                    created += 1
                    created_by_type[source_type] += 1
        except Exception as exc:
            logger.exception("%s discovery failed", source_type)
            SourceDiscoveryStatus.record(
                source_type,
                ts=ts,
                is_error=True,
                error_message=str(exc),
                new=0,
                existing=0,
                missing=0,
            )
            continue

        missing = len(existing_keys - discovered_keys)
        stats = DiscoveryStats(
            source_type=source_type,
            candidates=candidates,
            discovered=len(discovered_keys),
            existing=existing,
            new=created,
            missing=missing,
        )
        SourceDiscoveryStatus.record(
            source_type,
            ts=ts,
            is_error=False,
            error_message=None,
            new=created,
            existing=existing,
            missing=missing,
        )
        logger.info(
            "%s: %d candidates, %d discovered, %d existing, %d new, "
            "%d missing",
            source_type,
            candidates,
            stats.discovered,
            existing,
            created,
            missing,
        )
        if on_provider_done is not None:
            on_provider_done(stats)

    summary = ", ".join(
        f"{source_type}={count}"
        for source_type, count in sorted(created_by_type.items())
    )
    logger.info("Source discovery complete: %s", summary or "no new sources")
    return created_by_type
