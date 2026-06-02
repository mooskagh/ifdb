from django.core.management.base import BaseCommand

from curation.discovery import run_discover
from curation.edit import run_edit
from curation.fetch import run_fetch
from curation.models import GameSource
from curation.reconcile import run_reconcile


class Command(BaseCommand):
    help = "Run curation source-pipeline phases."

    def add_arguments(self, parser):
        parser.add_argument(
            "phase", choices=["discover", "fetch", "reconcile", "edit"]
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print extra per-phase progress.",
        )
        parser.add_argument(
            "--type",
            action="append",
            choices=GameSource.SourceType.values,
            help="Limit to one source type. Can be used repeatedly.",
        )
        parser.add_argument("--limit", type=int, help="Limit fetched sources.")
        parser.add_argument("--source", type=int, help="Fetch one source pk.")
        parser.add_argument("--url", help="Fetch one source URL.")
        parser.add_argument(
            "--threads",
            type=int,
            default=1,
            help="Fetch sources with this many worker threads.",
        )
        parser.add_argument(
            "--rate-limit",
            type=float,
            default=0,
            help="Minimum seconds between fetch starts per source type.",
        )
        parser.add_argument("--history", type=int, help="Edit one history pk.")

    def handle(self, *args, **options):
        verbose = options["verbose"] or options["verbosity"] > 1

        if options["phase"] == "discover":
            provider_stats = []
            counts = run_discover(
                types=options["type"],
                on_provider_done=provider_stats.append,
            )
            for stats in provider_stats:
                candidate_suffix = (
                    f" ({stats.candidates} candidates)"
                    if verbose or stats.candidates != stats.discovered
                    else ""
                )
                self.stdout.write(
                    f"sources [{stats.source_type}]: "
                    f"{stats.discovered} discovered{candidate_suffix}, "
                    f"{len(stats.existing_ids)} existing, "
                    f"{len(stats.new_ids)} new, "
                    f"{len(stats.newly_missing_ids)} newly missing, "
                    f"{len(stats.absent_ids)} absent, "
                    f"{len(stats.unused_ids)} unused, "
                    f"{len(stats.duplicate_id_clusters)} duplicate clusters"
                )
            if not counts:
                self.stdout.write("No new sources.")
            return

        if options["phase"] == "reconcile":

            def reconcile_done(source, outcome, history):
                target = f" -> history #{history.pk}" if history else ""
                self.stdout.write(
                    f"source #{source.pk} [{source.type}] "
                    f"{source.url or '(no url)'}: {outcome}{target}"
                )

            stats = run_reconcile(
                types=options["type"],
                limit=options["limit"],
                source_id=options["source"],
                on_source_done=reconcile_done if verbose else None,
            )
            for item in stats:
                self.stdout.write(
                    f"sources [{item.source_type}]: "
                    f"{item.processed} processed, {item.attached} attached, "
                    f"{item.spawned} spawned, {item.ambiguous} ambiguous, "
                    f"{item.skipped_no_fetch} skipped (no fetch)"
                )
            if not stats:
                self.stdout.write("No orphan sources to reconcile.")
            return

        if options["phase"] == "edit":

            def edit_done(history, outcome):
                self.stdout.write(f"history #{history.pk}: {outcome}")

            stats = run_edit(
                history_id=options["history"],
                limit=options["limit"],
                on_history_done=edit_done if verbose else None,
            )
            if stats.processed == 0 and stats.errors == 0:
                self.stdout.write("No in-progress histories.")
            else:
                self.stdout.write(
                    f"histories: {stats.processed} processed, "
                    f"{stats.applied} applied, {stats.proposed} proposed, "
                    f"{stats.rejected} rejected, "
                    f"{stats.unchanged} unchanged, "
                    f"{stats.cancelled} cancelled, {stats.errors} errors"
                )
            return

        def source_done(source, outcome, error):
            suffix = f": {error}" if error else ""
            self.stdout.write(
                f"source #{source.pk} [{source.type}] "
                f"{source.url or '(no url)'}: {outcome}{suffix}"
            )

        stats = run_fetch(
            types=options["type"],
            limit=options["limit"],
            source_id=options["source"],
            url=options["url"],
            on_source_done=source_done if verbose else None,
            threads=options["threads"],
            rate_limit=options["rate_limit"],
        )
        for item in stats:
            self.stdout.write(
                f"sources [{item.source_type}]: "
                f"{item.processed} processed, {item.ok} ok, "
                f"{item.failed} failed, {item.created} new, "
                f"{item.unchanged} unchanged"
            )
        if not stats:
            self.stdout.write("No sources to fetch.")
