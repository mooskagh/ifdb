import re
from logging import getLogger
from urllib.parse import unquote

from celery import shared_task
from django.conf import settings

from core.crawler import FetchUrlToFileLike
from games.models import URL

logger = getLogger("crawler")

FILENAME_RE = re.compile(
    r"^.*?\b((?:%[0-9a-f]{2}|[$:+()_\w\d\.])+\.[\w\d]{2,4})\b[^/]*$"
)


def come_up_with_filename(metadata):
    if metadata["filename"]:
        return metadata["filename"]
    if m := FILENAME_RE.match(metadata["url"]):
        return unquote(m.group(1))
    return "unknown"


@shared_task(bind=True, max_retries=3, retry_backoff=True)
def clone_file(self, url_id):
    url = URL.objects.get(id=url_id)
    try:
        logger.info("Url is id %d, URL %s", url.id, url.original_url)
        f = FetchUrlToFileLike(url.original_url)
        fs = settings.BACKUPS_FS
        filename = fs.save(come_up_with_filename(f.metadata), f, max_length=64)
        logger.info("Stored as %s", filename)

        url.local_url = fs.url(filename)
        url.local_filename = filename
        url.original_filename = f.metadata["filename"]
        url.content_type = f.metadata["content-type"]
        url.file_size = fs.size(filename)
        url.save()
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.warning("Found broken link at url: %s", url.original_url)
            url.is_broken = True
            url.save(update_fields=["is_broken"])
            raise
        raise self.retry(exc=exc)
