import tempfile
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.db import models, transaction
from django.utils.timezone import now

from games.fetcher import determine_storage_path, persist_file_to_storage
from games.models import URL, Game, StoredFile, URLFetch


def handle_existing_game_upload(
    game: Game,
    uploaded_file: Any,
    user: Any = None,
    build_absolute_uri: Callable[[str], str] | None = None,
) -> tuple[URL, StoredFile, URLFetch]:
    """Store an uploaded file associated with an existing game.

    Deduplicates globally using SHA-256 against StoredFile. If unique, saves
    under /f/g/<game_id>/<filename> in FILES_FS. Returns (url, stored_file,
    fetch).
    """
    tmp_file = tempfile.NamedTemporaryFile(delete=False)
    tmp_path = Path(tmp_file.name)
    digest = sha256()
    file_size = 0
    try:
        for chunk in uploaded_file.chunks():
            digest.update(chunk)
            file_size += len(chunk)
            tmp_file.write(chunk)
        tmp_file.flush()
    finally:
        tmp_file.close()

    content_hash = digest.hexdigest()
    try:
        stored_file = StoredFile.objects.filter(
            content_hash=content_hash
        ).first()
        if stored_file is None:
            storage_path = determine_storage_path(
                candidate_filename=uploaded_file.name,
                content_hash=content_hash,
                content_type=getattr(uploaded_file, "content_type", None),
                game_id=game.id,
            )
            persist_file_to_storage(tmp_path, storage_path, content_hash)
            stored_file, _ = StoredFile.objects.get_or_create(
                content_hash=content_hash,
                defaults={
                    "storage_path": storage_path,
                    "file_size": file_size,
                    "created_at": now(),
                },
            )

        file_url = stored_file.public_url
        url_full = (
            build_absolute_uri(file_url) if build_absolute_uri else file_url
        )
        url = URL.objects.filter(original_url=url_full).first()
        orig_filename = (uploaded_file.name or "")[:255]
        content_type = (getattr(uploaded_file, "content_type", "") or "")[:255]

        if url is None:
            creator = (
                user
                if user and getattr(user, "is_authenticated", False)
                else None
            )
            url = URL.objects.create(
                local_url=file_url,
                original_url=url_full,
                original_filename=orig_filename,
                content_type=content_type,
                is_uploaded=True,
                creation_date=now(),
                file_size=stored_file.file_size,
                creator=creator,
            )
        else:
            url.local_url = file_url
            url.file_size = stored_file.file_size
            url.is_uploaded = True
            url.save(
                update_fields=[
                    "local_url",
                    "file_size",
                    "is_uploaded",
                ]
            )

        fetch, _ = URLFetch.objects.get_or_create(
            url=url,
            stored_file=stored_file,
            defaults={
                "original_filename": orig_filename or None,
                "content_type": content_type or None,
                "first_fetch": now(),
                "last_fetch": now(),
            },
        )
        return url, stored_file, fetch
    finally:
        tmp_path.unlink(missing_ok=True)


def is_provisional_upload(
    url_str: str | None,
    url_id: int | None = None,
) -> tuple[bool, str | None]:
    """Check if a URL is an uncommitted provisional upload in UPLOADS_FS.

    Returns (True, rel_path) if it is provisional, or (False, None) if it is
    either external, already committed to a game, or an already-persisted
    legacy upload.
    """
    if url_id is not None:
        url_obj = URL.objects.filter(id=url_id).first()
        if url_obj is None or url_obj.gameurl_set.exists():
            return False, None
        if not url_str and url_obj.original_url:
            url_str = url_obj.original_url

    if not url_str:
        return False, None

    parsed = urlparse(url_str)
    if "/f/uploads/" not in parsed.path:
        return False, None

    rel = unquote(parsed.path.split("/f/uploads/", 1)[1]).lstrip("/")
    if not rel or not settings.UPLOADS_FS.exists(rel):
        return False, None

    # Never promote already-persisted legacy uploads
    if StoredFile.objects.filter(storage_path=f"uploads/{rel}").exists():
        return False, None

    existing_urls = URL.objects.filter(
        models.Q(original_url=url_str)
        | models.Q(local_filename=rel)
        | models.Q(original_url__endswith=f"/f/uploads/{rel}")
    )
    if existing_urls.filter(gameurl__isnull=False).exists():
        return False, None

    return True, rel


def finalize_provisional_uploads(game: Game, info: Any) -> None:
    """Finalize provisional uploads in gameinfo.urls into /f/g/<game_id>/...

    Rewrites entry.url and sets entry.url_id before persistence.
    """
    for entry in getattr(info, "urls", []):
        is_prov, rel = is_provisional_upload(entry.url, entry.url_id)
        if not is_prov or not rel:
            continue

        prov_orig_url = entry.url
        try:
            staging_full_path = Path(settings.UPLOADS_FS.path(rel))
        except (NotImplementedError, AttributeError, ValueError):
            staging_full_path = None

        digest = sha256()
        file_size = 0
        with settings.UPLOADS_FS.open(rel, "rb") as f:
            while chunk := f.read(64 * 1024):
                digest.update(chunk)
                file_size += len(chunk)

        content_hash = digest.hexdigest()
        stored_file = StoredFile.objects.filter(
            content_hash=content_hash
        ).first()

        prov_url = (
            URL.objects.filter(
                models.Q(original_url=prov_orig_url)
                | models.Q(local_filename=rel)
            ).first()
            if prov_orig_url
            else URL.objects.filter(local_filename=rel).first()
        )

        orig_filename = (
            prov_url.original_filename
            if prov_url and prov_url.original_filename
            else Path(rel).name
        )
        content_type = prov_url.content_type if prov_url else None

        if stored_file is None:
            storage_path = determine_storage_path(
                candidate_filename=orig_filename,
                content_hash=content_hash,
                content_type=content_type,
                game_id=game.id,
            )
            if staging_full_path and staging_full_path.exists():
                persist_file_to_storage(
                    staging_full_path, storage_path, content_hash
                )
            else:
                tmp_file = tempfile.NamedTemporaryFile(delete=False)
                tmp_path = Path(tmp_file.name)
                try:
                    with settings.UPLOADS_FS.open(rel, "rb") as sf:
                        while chunk := sf.read(64 * 1024):
                            tmp_file.write(chunk)
                    tmp_file.flush()
                    tmp_file.close()
                    persist_file_to_storage(
                        tmp_path, storage_path, content_hash
                    )
                finally:
                    tmp_path.unlink(missing_ok=True)

            stored_file, _ = StoredFile.objects.get_or_create(
                content_hash=content_hash,
                defaults={
                    "storage_path": storage_path,
                    "file_size": file_size,
                    "created_at": now(),
                },
            )

        if prov_orig_url:
            parsed = urlparse(prov_orig_url)
            if parsed.scheme and parsed.netloc:
                final_url = parsed._replace(
                    path=stored_file.public_url
                ).geturl()
            else:
                final_url = stored_file.public_url
        else:
            final_url = stored_file.public_url

        final_url_obj = URL.objects.filter(original_url=final_url).first()
        if final_url_obj is None:
            final_url_obj = URL.objects.create(
                local_url=stored_file.public_url,
                original_url=final_url,
                original_filename=orig_filename[:255],
                content_type=(content_type or "")[:255],
                is_uploaded=True,
                creation_date=now(),
                file_size=stored_file.file_size,
                creator=game.added_by,
            )
        else:
            final_url_obj.local_url = stored_file.public_url
            final_url_obj.file_size = stored_file.file_size
            final_url_obj.is_uploaded = True
            final_url_obj.save(
                update_fields=[
                    "local_url",
                    "file_size",
                    "is_uploaded",
                ]
            )

        URLFetch.objects.get_or_create(
            url=final_url_obj,
            stored_file=stored_file,
            defaults={
                "original_filename": orig_filename[:255] or None,
                "content_type": (content_type or "")[:255] or None,
                "first_fetch": now(),
                "last_fetch": now(),
            },
        )

        entry.url = final_url
        entry.url_id = final_url_obj.id

        # Clean up provisional URL record and staging file
        prov_qs = URL.objects.filter(
            models.Q(original_url=prov_orig_url) | models.Q(local_filename=rel)
        ).filter(gameurl__isnull=True)
        if final_url_obj.id:
            prov_qs = prov_qs.exclude(id=final_url_obj.id)
        prov_qs.delete()

        def _cleanup_staging(staging_rel: str = rel) -> None:
            if settings.UPLOADS_FS.exists(staging_rel):
                settings.UPLOADS_FS.delete(staging_rel)

        transaction.on_commit(_cleanup_staging)
