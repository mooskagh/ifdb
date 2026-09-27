from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from games.fetcher import (
    FetchOutcome,
    FetchResult,
    FetchStats,
    run_fetch_urls,
)


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
            help="Fetch URLs even if ok_to_clone is False.",
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

        if verbosity >= 1:
            self.stdout.write("Starting URL fetch...")

        def on_progress(result: FetchResult, stats: FetchStats) -> None:
            url = result.url
            if result.outcome == FetchOutcome.CREATED:
                if verbosity >= 2:
                    self.stdout.write(
                        f"URL #{url.id}: created {result.stored_file}"
                    )
            elif result.outcome == FetchOutcome.REUSED:
                if verbosity >= 2:
                    self.stdout.write(
                        f"URL #{url.id}: reused {result.stored_file}"
                    )
            elif result.outcome == FetchOutcome.UNCHANGED:
                if verbosity >= 2:
                    self.stdout.write(f"URL #{url.id}: unchanged")
            elif result.outcome == FetchOutcome.FAILED:
                if verbosity >= 1:
                    self.stderr.write(
                        f"URL #{url.id} ({url.original_url}) failed:"
                        f" {result.error}"
                    )
            elif result.outcome == FetchOutcome.SKIPPED:
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

        stats = run_fetch_urls(
            limit=limit,
            url_id=url_id,
            game_id=game_id,
            force=force,
            timeout=timeout,
            on_progress=on_progress,
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
