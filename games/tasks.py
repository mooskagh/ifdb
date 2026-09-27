from logging import getLogger
from typing import Any
from urllib.parse import unquote

from celery import Task, shared_task

from games.fetcher import (
    FILENAME_RE,
    FetchOutcome,
    FetchResult,
    fetch_url,
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
