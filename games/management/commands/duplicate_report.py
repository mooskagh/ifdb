from typing import Any

from django.core.management.base import BaseCommand
from django.template.defaultfilters import filesizeformat

from games.duplicates import get_duplicate_url_groups


class Command(BaseCommand):
    help = (
        "Report current URLs sharing the same StoredFile (duplicate content)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum duplicate groups to display (0 for unlimited).",
        )
        parser.add_argument(
            "--game-id",
            type=int,
            default=None,
            help="Filter to duplicate groups involving this game ID.",
        )
        parser.add_argument(
            "--min-size",
            type=int,
            default=0,
            help="Filter to groups with file_size >= min_size bytes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        limit = options["limit"] or None
        game_id = options["game_id"]
        min_size = options["min_size"]

        groups = get_duplicate_url_groups()

        if game_id is not None:
            groups = [
                g
                for g in groups
                if any(gu.game_id == game_id for gu in g.game_urls)
            ]

        if min_size > 0:
            groups = [g for g in groups if g.stored_file.file_size >= min_size]

        total_groups = len(groups)
        total_urls = sum(g.duplicate_count for g in groups)
        total_savings = sum(g.potential_savings for g in groups)

        self.stdout.write(
            self.style.MIGRATE_HEADING("=== Duplicate Content Report ===")
        )
        self.stdout.write(f"Total duplicate groups: {total_groups}")
        self.stdout.write(f"Total URLs involved:    {total_urls}")
        self.stdout.write(
            f"Potential savings:      {filesizeformat(total_savings)} "
            f"({total_savings:,} bytes)\n"
        )

        display_groups = groups[:limit] if limit else groups
        for idx, group in enumerate(display_groups, start=1):
            sf = group.stored_file
            size_str = filesizeformat(sf.file_size)
            header = (
                f"[{idx}] StoredFile #{sf.pk}: {sf.storage_path} "
                f"({size_str}, {group.duplicate_count} URLs)"
            )
            self.stdout.write(self.style.SUCCESS(header))
            self.stdout.write(f"    Hash: {sf.content_hash}")

            self.stdout.write("    URLs:")
            for u in group.urls:
                kind = "upload" if u.is_uploaded else "remote"
                self.stdout.write(
                    f"      - URL #{u.pk} [{kind}]: {u.original_url}"
                )

            if group.game_urls:
                self.stdout.write("    Games:")
                for gu in group.game_urls:
                    cat = gu.category.title if gu.category else "no category"
                    desc = f" ({gu.description})" if gu.description else ""
                    self.stdout.write(
                        f"      - Game #{gu.game_id} '{gu.game.title}' "
                        f"[{cat}]{desc}"
                    )
            else:
                self.stdout.write("    Games: (none attached)")
            self.stdout.write("")

        if limit and total_groups > limit:
            remaining = total_groups - limit
            self.stdout.write(
                f"... and {remaining} more duplicate group(s). "
                "Use --limit 0 to view all."
            )
