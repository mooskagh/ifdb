from logging import getLogger

from celery import shared_task

from games.fetcher import run_fetch_urls

logger = getLogger("crawler")


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
