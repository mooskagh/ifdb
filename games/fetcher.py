import mimetypes
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils.text import get_valid_filename
from django.utils.timezone import now

from core.crawler import FetchUrlToFileLike
from games.models import URL, StoredFile, URLFetch

FILENAME_RE = re.compile(
    r"^.*?\b((?:%[0-9a-f]{2}|[$:+()_\w\d\.])+\.[\w\d]{2,4})\b[^/]*$"
)


class FetchOutcome(Enum):
    CREATED = "created"
    REUSED = "reused"
    UNCHANGED = "unchanged"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class FetchResult:
    outcome: FetchOutcome
    url: URL
    stored_file: StoredFile | None = None
    url_fetch: URLFetch | None = None
    error: str | None = None
    bytes_fetched: int = 0


def sanitize_filename(
    candidate: str | None,
    content_type: str | None = None,
) -> str:
    name = ""
    if candidate:
        name = Path(candidate.strip().replace("\\", "/")).name
    try:
        clean = get_valid_filename(name).lstrip(".")
    except Exception:
        clean = ""

    if not clean:
        clean = "download"

    if "." not in clean and content_type:
        ext = mimetypes.guess_extension(content_type)
        if ext:
            clean = f"{clean}{ext}"

    if len(clean) > 120:
        p = Path(clean)
        ext = p.suffix[:20]
        stem = p.stem[: 120 - len(ext)]
        clean = f"{stem}{ext}"

    return clean


def is_path_occupied_by_other_content(
    storage_path: str,
    content_hash: str,
) -> bool:
    stored = StoredFile.objects.filter(storage_path=storage_path).first()
    if stored is not None:
        return bool(stored.content_hash != content_hash)

    fs = settings.FILES_FS
    if fs.exists(storage_path):
        try:
            with fs.open(storage_path, "rb") as f:
                digest = sha256()
                while chunk := f.read(64 * 1024):
                    digest.update(chunk)
                return bool(digest.hexdigest() != content_hash)
        except OSError:
            return True

    return False


def determine_storage_path(
    url: URL | None = None,
    candidate_filename: str | None = None,
    content_hash: str = "",
    content_type: str | None = None,
    game_id: int | None = None,
) -> str:
    target_game_id: int | None = game_id
    if target_game_id is None and url is not None and url.pk:
        target_game_id = (
            url.gameurl_set
            .order_by("game_id")
            .values_list("game_id", flat=True)
            .first()
        )

    if target_game_id is not None:
        namespace = f"g/{target_game_id}"
    else:
        namespace = "backups"

    clean_filename = sanitize_filename(
        candidate_filename, content_type=content_type
    )
    candidate_path = f"{namespace}/{clean_filename}"

    if not is_path_occupied_by_other_content(candidate_path, content_hash):
        return candidate_path

    p = Path(clean_filename)
    stem, ext = p.stem, p.suffix
    for hash_len in (8, 12, 16, 24, 32, 64):
        short_hash = content_hash[:hash_len]
        collision_path = f"{namespace}/{stem}-{short_hash}{ext}"
        if not is_path_occupied_by_other_content(collision_path, content_hash):
            return collision_path

    return f"{namespace}/{stem}-{content_hash[:8]}-{uuid4().hex[:6]}{ext}"


def persist_file_to_storage(
    tmp_path: Path,
    storage_path: str,
    content_hash: str,
) -> None:
    fs = settings.FILES_FS
    try:
        dest_path = Path(fs.path(storage_path))
    except (NotImplementedError, AttributeError, ValueError):
        if not fs.exists(storage_path):
            with tmp_path.open("rb") as f:
                fs.save(storage_path, f)
        return

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        return

    dest_tmp = dest_path.parent / f".tmp_{dest_path.name}_{uuid4().hex}"
    try:
        shutil.copyfile(tmp_path, dest_tmp)
        os.replace(dest_tmp, dest_path)
    finally:
        if dest_tmp.exists():
            dest_tmp.unlink(missing_ok=True)


def fetch_url(
    url: URL,
    *,
    timeout: int = 300,
    downloader: Callable[..., Any] | None = None,
) -> FetchResult:
    if url.is_uploaded:
        return FetchResult(
            outcome=FetchOutcome.SKIPPED,
            url=url,
            error=(
                "URL represents an uploaded file and is not eligible for"
                " refetching"
            ),
        )
    if not url.original_url or not url.original_url.strip():
        return FetchResult(
            outcome=FetchOutcome.SKIPPED,
            url=url,
            error="URL has no original_url",
        )
    if not url.pk or not url.gameurl_set.exists():
        return FetchResult(
            outcome=FetchOutcome.SKIPPED,
            url=url,
            error="URL is not referenced by any game",
        )

    attempt_time = now()
    url.last_attempt = attempt_time

    tmp_file = tempfile.NamedTemporaryFile(delete=False)
    tmp_path = Path(tmp_file.name)

    try:
        digest = sha256()
        bytes_fetched = 0
        orig_filename: str | None = None
        content_type: str | None = None

        if downloader is not None:
            resp = downloader(url.original_url, timeout=timeout)
        else:
            resp = FetchUrlToFileLike(url.original_url, use_cache=False)

        try:
            metadata = getattr(resp, "metadata", {}) or {}
            orig_filename = metadata.get("filename")
            content_type = metadata.get("content-type")

            if not orig_filename:
                if m := FILENAME_RE.match(url.original_url):
                    orig_filename = unquote(m.group(1))

            while chunk := resp.read(64 * 1024):
                digest.update(chunk)
                bytes_fetched += len(chunk)
                tmp_file.write(chunk)
            tmp_file.flush()
        finally:
            tmp_file.close()
            if hasattr(resp, "close"):
                resp.close()

        content_hash = digest.hexdigest()

    except Exception as exc:
        error_msg = str(exc)
        url.failing_since = url.failing_since or attempt_time
        url.last_error = error_msg
        url.is_broken = True
        URL.objects.filter(pk=url.pk).filter(
            Q(last_attempt__isnull=True) | Q(last_attempt__lte=attempt_time)
        ).update(
            last_attempt=attempt_time,
            failing_since=url.failing_since,
            last_error=error_msg,
            is_broken=True,
        )
        tmp_path.unlink(missing_ok=True)
        return FetchResult(
            outcome=FetchOutcome.FAILED,
            url=url,
            error=error_msg,
        )

    try:
        stored_file = StoredFile.objects.filter(
            content_hash=content_hash
        ).first()
        latest_fetch = url.get_latest_fetch()

        if (
            stored_file is not None
            and latest_fetch is not None
            and latest_fetch.stored_file_id == stored_file.id
        ):
            outcome = FetchOutcome.UNCHANGED
            URLFetch.objects.filter(
                pk=latest_fetch.pk,
                first_fetch__lte=attempt_time,
                last_fetch__lt=attempt_time,
            ).update(last_fetch=attempt_time)
            fetch_row = latest_fetch
        elif stored_file is not None:
            outcome = FetchOutcome.REUSED
            fetch_row = URLFetch.objects.create(
                url=url,
                stored_file=stored_file,
                original_filename=(orig_filename or "")[:255] or None,
                content_type=(content_type or "")[:255] or None,
                first_fetch=attempt_time,
                last_fetch=attempt_time,
            )
        else:
            outcome = FetchOutcome.CREATED
            storage_path = determine_storage_path(
                url=url,
                candidate_filename=orig_filename,
                content_hash=content_hash,
                content_type=content_type,
            )
            persist_file_to_storage(tmp_path, storage_path, content_hash)
            with transaction.atomic():
                stored_file, _ = StoredFile.objects.get_or_create(
                    content_hash=content_hash,
                    defaults={
                        "storage_path": storage_path,
                        "file_size": bytes_fetched,
                        "created_at": attempt_time,
                    },
                )
                fetch_row = URLFetch.objects.create(
                    url=url,
                    stored_file=stored_file,
                    original_filename=(orig_filename or "")[:255] or None,
                    content_type=(content_type or "")[:255] or None,
                    first_fetch=attempt_time,
                    last_fetch=attempt_time,
                )

        url.failing_since = None
        url.last_error = None
        url.is_broken = False
        url.local_url = stored_file.public_url
        url.file_size = stored_file.file_size

        update_fields = [
            "last_attempt",
            "failing_since",
            "last_error",
            "is_broken",
            "local_url",
            "file_size",
        ]
        if orig_filename:
            url.original_filename = orig_filename[:255]
            update_fields.append("original_filename")
        if content_type:
            url.content_type = content_type[:255]
            update_fields.append("content_type")

        URL.objects.filter(pk=url.pk).filter(
            Q(last_attempt__isnull=True) | Q(last_attempt__lte=attempt_time)
        ).update(**{field: getattr(url, field) for field in update_fields})

        return FetchResult(
            outcome=outcome,
            url=url,
            stored_file=stored_file,
            url_fetch=fetch_row,
            bytes_fetched=bytes_fetched,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


@dataclass
class FetchStats:
    urls_examined: int = 0
    files_created: int = 0
    files_reused: int = 0
    fetches_unchanged: int = 0
    fetches_failed: int = 0
    urls_skipped: int = 0
    bytes_total: int = 0


def get_eligible_urls(
    url_id: int | None = None,
    game_id: int | None = None,
    force: bool = False,
    limit: int | None = None,
) -> Iterator[URL]:
    base_qs = (
        URL.objects
        .exclude(original_url__isnull=True)
        .exclude(original_url="")
        .filter(is_uploaded=False)
        .filter(gameurl__isnull=False)
        .distinct()
    )
    if not force:
        base_qs = base_qs.filter(ok_to_clone=True)

    if url_id is not None:
        base_qs = base_qs.filter(id=url_id)
    if game_id is not None:
        base_qs = base_qs.filter(gameurl__game_id=game_id)

    never_attempted_qs = base_qs.filter(last_attempt__isnull=True).order_by(
        "-creation_date", "-id"
    )
    if limit is not None:
        never_attempted_qs = never_attempted_qs[:limit]
    never_attempted_ids = list(never_attempted_qs.values_list("id", flat=True))

    for pk in never_attempted_ids:
        try:
            yield URL.objects.get(id=pk)
        except URL.DoesNotExist:
            continue

    count = len(never_attempted_ids)
    if limit is not None and count >= limit:
        return

    remaining_limit = (limit - count) if limit is not None else None
    attempted_qs = (
        base_qs
        .filter(last_attempt__isnull=False)
        .exclude(id__in=never_attempted_ids)
        .order_by("last_attempt", "id")
    )
    if remaining_limit is not None:
        attempted_qs = attempted_qs[:remaining_limit]

    attempted_ids = list(attempted_qs.values_list("id", flat=True))
    for pk in attempted_ids:
        try:
            yield URL.objects.get(id=pk)
        except URL.DoesNotExist:
            continue


def run_fetch_urls(
    *,
    limit: int | None = None,
    url_id: int | None = None,
    game_id: int | None = None,
    force: bool = False,
    timeout: int = 300,
    downloader: Callable[..., Any] | None = None,
    on_progress: Callable[[FetchResult, FetchStats], None] | None = None,
) -> FetchStats:
    stats = FetchStats()
    for url in get_eligible_urls(
        url_id=url_id,
        game_id=game_id,
        force=force,
        limit=limit,
    ):
        stats.urls_examined += 1
        result = fetch_url(url, timeout=timeout, downloader=downloader)
        stats.bytes_total += result.bytes_fetched
        if result.outcome == FetchOutcome.CREATED:
            stats.files_created += 1
        elif result.outcome == FetchOutcome.REUSED:
            stats.files_reused += 1
        elif result.outcome == FetchOutcome.UNCHANGED:
            stats.fetches_unchanged += 1
        elif result.outcome == FetchOutcome.FAILED:
            stats.fetches_failed += 1
        elif result.outcome == FetchOutcome.SKIPPED:
            stats.urls_skipped += 1

        if on_progress:
            on_progress(result, stats)

    return stats
