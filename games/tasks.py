from logging import getLogger
from typing import Any
from urllib.parse import unquote

from celery import Task, shared_task

from games.fetcher import (
    FILENAME_RE,
    FetchOutcome,
    FetchResult,
    fetch_url,
    run_fetch_urls,
)
from games.models import URL

logger = getLogger("crawler")


def come_up_with_filename(metadata: dict[str, Any]) -> str:
    if metadata.get("filename"):
        return str(metadata["filename"])
    if m := FILENAME_RE.match(str(metadata.get("url", ""))):
        return unquote(m.group(1))
    return "unknown"


@shared_task(bind=True, max_retries=3, retry_backoff=True)  # type: ignore[untyped-decorator]
def clone_file(self: Task, url_id: int) -> FetchResult | None:
    try:
        url = URL.objects.get(id=url_id)
    except URL.DoesNotExist:
        logger.warning("URL id %s does not exist", url_id)
        return None

    if url.is_uploaded:
        return None

    logger.info("Url is id %d, URL %s", url.pk, url.original_url)
    res = fetch_url(url)
    if res.outcome == FetchOutcome.FAILED:
        logger.warning(
            "Found broken link or fetch failed at url %s (id %s): %s",
            url.original_url,
            url.pk,
            res.error,
        )
        if (
            hasattr(self, "request")
            and self.request.retries < self.max_retries
        ):
            raise self.retry(exc=RuntimeError(res.error or "Fetch failed"))
        raise RuntimeError(res.error or "Fetch failed")

    return res


@shared_task  # type: ignore[untyped-decorator]
def fetch_urls(
    limit: int = 10,
    url_id: int | None = None,
    game_id: int | None = None,
    force: bool = False,
    timeout: int = 300,
) -> dict[str, int]:
    logger.info(
        "Starting fetch_urls task: limit=%s, url_id=%s, game_id=%s, force=%s",
        limit,
        url_id,
        game_id,
        force,
    )
    stats = run_fetch_urls(
        limit=limit,
        url_id=url_id,
        game_id=game_id,
        force=force,
        timeout=timeout,
    )
    logger.info(
        "Finished fetch_urls task: examined=%d, created=%d, reused=%d, "
        "unchanged=%d, failed=%d",
        stats.urls_examined,
        stats.files_created,
        stats.files_reused,
        stats.fetches_unchanged,
        stats.fetches_failed,
    )
    return {
        "urls_examined": stats.urls_examined,
        "files_created": stats.files_created,
        "files_reused": stats.files_reused,
        "fetches_unchanged": stats.fetches_unchanged,
        "fetches_failed": stats.fetches_failed,
        "urls_skipped": stats.urls_skipped,
        "bytes_total": stats.bytes_total,
    }
