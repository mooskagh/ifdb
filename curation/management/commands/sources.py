from django.core.management.base import BaseCommand

from curation.discovery import run_discover
from curation.models import GameSource


class Command(BaseCommand):
    help = "Run curation source-pipeline phases."

    def add_arguments(self, parser):
        parser.add_argument("phase", choices=["discover"])
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Also print raw candidate counts, including duplicates.",
        )
        parser.add_argument(
            "--type",
            action="append",
            choices=GameSource.SourceType.values,
            help="Limit discovery to one source type. Can be used repeatedly.",
        )

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
                    f"{stats.existing} existing, {stats.new} new, "
                    f"{stats.missing} missing"
                )
            if not counts:
                self.stdout.write("No new sources.")
