from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from games.fetcher import FetchOutcome, fetch_url
from games.models import URL


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
    base_qs = URL.objects.exclude(original_url__isnull=True).exclude(
        original_url=""
    )
    if not force:
        base_qs = base_qs.filter(is_uploaded=False, ok_to_clone=True)

    if url_id is not None:
        base_qs = base_qs.filter(id=url_id)
    if game_id is not None:
        base_qs = base_qs.filter(gameurl__game_id=game_id).distinct()

    count = 0
    processed_ids: set[int] = set()
    never_attempted = base_qs.filter(last_attempt__isnull=True).order_by(
        "-creation_date", "-id"
    )
    for url in never_attempted.iterator():
        processed_ids.add(url.id)
        yield url
        count += 1
        if limit is not None and count >= limit:
            return

    attempted = (
        base_qs
        .filter(last_attempt__isnull=False)
        .exclude(id__in=processed_ids)
        .order_by("last_attempt", "id")
    )
    for url in attempted.iterator():
        yield url
        count += 1
        if limit is not None and count >= limit:
            return


class Command(BaseCommand):
    help = (
        "Fetch external backupable URLs using hash-based deduplicated storage."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--url-id",
            type=int,
            default=None,
            help="Fetch a specific URL by ID.",
        )
        parser.add_argument(
            "--game-id",
            type=int,
            default=None,
            help="Fetch URLs referenced by a specific game ID.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of URLs to process.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Progress reporting interval (default: 100).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Fetch URLs even if ok_to_clone is False or already uploaded."
            ),
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=300,
            help="HTTP fetch timeout in seconds (default: 300).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        url_id: int | None = options["url_id"]
        game_id: int | None = options["game_id"]
        limit: int | None = options["limit"]
        batch_size: int = options["batch_size"]
        force: bool = options["force"]
        timeout: int = options["timeout"]
        verbosity: int = options["verbosity"]

        stats = FetchStats()

        if verbosity >= 1:
            self.stdout.write("Starting URL fetch...")

        for url in get_eligible_urls(
            url_id=url_id,
            game_id=game_id,
            force=force,
            limit=limit,
        ):
            stats.urls_examined += 1
            result = fetch_url(url, timeout=timeout)

            stats.bytes_total += result.bytes_fetched
            if result.outcome == FetchOutcome.CREATED:
                stats.files_created += 1
                if verbosity >= 2:
                    self.stdout.write(
                        f"URL #{url.id}: created {result.stored_file}"
                    )
            elif result.outcome == FetchOutcome.REUSED:
                stats.files_reused += 1
                if verbosity >= 2:
                    self.stdout.write(
                        f"URL #{url.id}: reused {result.stored_file}"
                    )
            elif result.outcome == FetchOutcome.UNCHANGED:
                stats.fetches_unchanged += 1
                if verbosity >= 2:
                    self.stdout.write(f"URL #{url.id}: unchanged")
            elif result.outcome == FetchOutcome.FAILED:
                stats.fetches_failed += 1
                if verbosity >= 1:
                    self.stderr.write(
                        f"URL #{url.id} ({url.original_url}) failed:"
                        f" {result.error}"
                    )
            elif result.outcome == FetchOutcome.SKIPPED:
                stats.urls_skipped += 1
                if verbosity >= 2:
                    self.stdout.write(
                        f"URL #{url.id}: skipped ({result.error})"
                    )

            if verbosity >= 1 and stats.urls_examined % batch_size == 0:
                self.stdout.write(
                    f"Processed {stats.urls_examined} URLs... "
                    f"({stats.files_created} created, "
                    f"{stats.files_reused} reused, "
                    f"{stats.fetches_unchanged} unchanged, "
                    f"{stats.fetches_failed} failed)"
                )

        self._print_summary(stats, verbosity)

    def _print_summary(self, stats: FetchStats, verbosity: int) -> None:
        if verbosity < 1:
            return

        self.stdout.write("\nFetch summary:")
        self.stdout.write(f"  URLs examined:      {stats.urls_examined}")
        self.stdout.write(f"  Stored files created: {stats.files_created}")
        self.stdout.write(f"  Stored files reused:  {stats.files_reused}")
        self.stdout.write(f"  Fetches unchanged:    {stats.fetches_unchanged}")
        self.stdout.write(f"  Fetches failed:       {stats.fetches_failed}")
        self.stdout.write(f"  URLs skipped:         {stats.urls_skipped}")
        self.stdout.write(f"  Total bytes fetched:  {stats.bytes_total}")
