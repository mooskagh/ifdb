from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from curation.models import GameSource


def legacy_qsp_source_query() -> Q:
    old_qsp_org = Q(url__icontains="qsp.org/index.php") | Q(
        url__icontains="qsp.org/index2.php"
    )
    return (
        Q(url__icontains="qsp.su")
        | Q(url__icontains="old.qsp.org")
        | (old_qsp_org & Q(url__icontains="option=com_sobi2"))
    )


class Command(BaseCommand):
    help = "Drop legacy qsp.su GameSources after switching QSP to qsp.org API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete matching GameSources. Default is dry-run.",
        )

    def handle(self, *args, **options):
        sources = GameSource.objects.filter(
            legacy_qsp_source_query(), type=GameSource.SourceType.QSP
        )
        total = sources.count()
        attached = sources.exclude(game__isnull=True).count()
        orphan = total - attached

        self.stdout.write(
            f"Legacy QSP GameSources: {total} "
            f"({attached} attached, {orphan} orphan)."
        )
        if total == 0:
            return

        for source in sources.order_by("id")[:20]:
            target = f"game #{source.game_id}" if source.game_id else "orphan"
            self.stdout.write(f"  #{source.id} {target}: {source.url}")
        if total > 20:
            self.stdout.write(f"  ... and {total - 20} more")

        if not options["apply"]:
            self.stdout.write("Dry run only; pass --apply to delete them.")
            return

        with transaction.atomic():
            deleted, _ = sources.delete()
        self.stdout.write(f"Deleted {deleted} rows including cascades.")
