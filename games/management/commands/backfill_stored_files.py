import mimetypes
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePath
from typing import Any

from django.core.files.storage import Storage
from django.core.management.base import BaseCommand, CommandParser
from django.db import IntegrityError, transaction
from django.utils.timezone import now

from games.models import URL, StoredFile, URLFetch

CHUNK_SIZE = 1024 * 1024


@dataclass
class BackfillStats:
    urls_checked: int = 0
    stored_files_created: int = 0
    stored_files_reused: int = 0
    url_fetches_created: int = 0
    already_backfilled: int = 0
    missing_files: int = 0
    errors: int = 0


def hash_file(storage: Storage, filename: str) -> tuple[str, int]:
    digest = sha256()
    size = 0
    with storage.open(filename, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def get_storage_path(url: URL) -> str:
    prefix = "uploads" if url.is_uploaded else "backups"
    clean_name = url.local_filename.strip().replace("\\", "/").lstrip("/")
    return PurePath(prefix, clean_name).as_posix()


class Command(BaseCommand):
    help = "Backfill StoredFile and URLFetch rows from legacy local files."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of URLs per progress batch (default: 500).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of URLs to process.",
        )
        parser.add_argument(
            "--url-id",
            type=int,
            default=None,
            help="Process a specific URL by ID.",
        )
        parser.add_argument(
            "--game-id",
            type=int,
            default=None,
            help="Process URLs referenced by a specific game ID.",
        )
        parser.add_argument(
            "--unprocessed-only",
            action="store_true",
            help="Only process URLs that do not have any URLFetch rows.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate backfill without writing to the database.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size: int = options["batch_size"]
        limit: int | None = options["limit"]
        url_id: int | None = options["url_id"]
        game_id: int | None = options["game_id"]
        unprocessed_only: bool = options["unprocessed_only"]
        dry_run: bool = options["dry_run"]
        verbosity: int = options["verbosity"]

        urls_qs = (
            URL.objects
            .exclude(local_filename__isnull=True)
            .exclude(local_filename="")
            .order_by("id")
        )

        if url_id is not None:
            urls_qs = urls_qs.filter(id=url_id)
        if game_id is not None:
            urls_qs = urls_qs.filter(gameurl__game_id=game_id).distinct()
        if unprocessed_only:
            urls_qs = urls_qs.filter(fetches__isnull=True)
        if limit is not None:
            urls_qs = urls_qs[:limit]

        stats = BackfillStats()
        file_cache: dict[tuple[bool, str], tuple[str, int]] = {}

        if verbosity >= 1:
            total_target = urls_qs.count()
            self.stdout.write(
                f"Starting backfill for up to {total_target} URLs "
                f"(dry_run={dry_run})..."
            )

        for url in urls_qs.iterator(chunk_size=batch_size):
            stats.urls_checked += 1
            self._process_url(url, stats, file_cache, dry_run, verbosity)

            if verbosity >= 1 and stats.urls_checked % batch_size == 0:
                self.stdout.write(
                    f"Processed {stats.urls_checked} URLs... "
                    f"({stats.stored_files_created} files created, "
                    f"{stats.stored_files_reused} reused, "
                    f"{stats.already_backfilled} already backfilled, "
                    f"{stats.missing_files} missing)"
                )

        self._print_summary(stats, dry_run, verbosity)

    def _process_url(
        self,
        url: URL,
        stats: BackfillStats,
        file_cache: dict[tuple[bool, str], tuple[str, int]],
        dry_run: bool,
        verbosity: int,
    ) -> None:
        if not url.local_filename or not url.local_filename.strip():
            return

        storage = url.GetFs()
        cache_key = (bool(url.is_uploaded), url.local_filename)

        if cache_key in file_cache:
            digest, file_size = file_cache[cache_key]
        else:
            try:
                if not storage.exists(url.local_filename):
                    stats.missing_files += 1
                    if verbosity >= 2:
                        self.stderr.write(
                            f"Missing file for URL #{url.id}: "
                            f"{url.local_filename}"
                        )
                    return
                digest, file_size = hash_file(storage, url.local_filename)
                file_cache[cache_key] = (digest, file_size)
            except OSError as err:
                stats.errors += 1
                if verbosity >= 1:
                    self.stderr.write(
                        f"Error reading file for URL #{url.id} "
                        f"({url.local_filename}): {err}"
                    )
                return

        storage_path = get_storage_path(url)
        fetch_time = (
            url.creation_date
            if url.is_uploaded and url.creation_date
            else now()
        )

        orig_filename = (
            url.original_filename
            or PurePath(url.local_filename.replace("\\", "/")).name
        )[:255]

        content_type = url.content_type
        if not content_type and orig_filename:
            content_type, _ = mimetypes.guess_type(orig_filename)
        if content_type:
            content_type = content_type[:255]

        stored_file = StoredFile.objects.filter(content_hash=digest).first()

        if stored_file is not None:
            if URLFetch.objects.filter(
                url=url, stored_file=stored_file
            ).exists():
                stats.already_backfilled += 1
                return

        if dry_run:
            if stored_file is None:
                stats.stored_files_created += 1
            else:
                stats.stored_files_reused += 1
            stats.url_fetches_created += 1
            return

        try:
            with transaction.atomic():
                if stored_file is None:
                    stored_file, created = StoredFile.objects.get_or_create(
                        content_hash=digest,
                        defaults={
                            "storage_path": storage_path,
                            "file_size": file_size,
                            "created_at": fetch_time,
                        },
                    )
                    if created:
                        stats.stored_files_created += 1
                    else:
                        stats.stored_files_reused += 1
                else:
                    stats.stored_files_reused += 1

                URLFetch.objects.create(
                    url=url,
                    stored_file=stored_file,
                    original_filename=orig_filename,
                    content_type=content_type,
                    first_fetch=fetch_time,
                    last_fetch=fetch_time,
                )
                stats.url_fetches_created += 1
        except IntegrityError as err:
            stats.errors += 1
            if verbosity >= 1:
                self.stderr.write(
                    f"Database integrity error for URL #{url.id}: {err}"
                )

    def _print_summary(
        self, stats: BackfillStats, dry_run: bool, verbosity: int
    ) -> None:
        if verbosity < 1:
            return

        mode = " (DRY RUN)" if dry_run else ""
        self.stdout.write(f"\nBackfill summary{mode}:")
        self.stdout.write(f"  URLs examined:         {stats.urls_checked}")
        self.stdout.write(
            f"  Stored files created:  {stats.stored_files_created}"
        )
        self.stdout.write(
            f"  Stored files reused:   {stats.stored_files_reused}"
        )
        self.stdout.write(
            f"  URL fetches created:   {stats.url_fetches_created}"
        )
        self.stdout.write(
            f"  Already backfilled:    {stats.already_backfilled}"
        )
        self.stdout.write(f"  Missing files:         {stats.missing_files}")
        self.stdout.write(f"  Errors:                {stats.errors}")
