from django.core.management.base import BaseCommand

from curation.discovery import run_discover
from curation.fetch import run_fetch
from curation.models import GameSource


class Command(BaseCommand):
    help = "Run curation source-pipeline phases."

    def add_arguments(self, parser):
        parser.add_argument("phase", choices=["discover", "fetch"])
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

    def handle(self, *args, **options):
        if options["phase"] == "discover":
            provider_stats = []
            verbose = options["verbose"] or options["verbosity"] > 1
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
                    f"{len(stats.missing_ids)} missing, "
                    f"{len(stats.newly_missing_ids)} newly missing"
                )
            if not counts:
                self.stdout.write("No new sources.")
            return

        verbose = options["verbose"] or options["verbosity"] > 1

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
