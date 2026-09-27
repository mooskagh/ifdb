from collections import Counter, defaultdict
from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Q

from games.models import URL, GameURL


class Command(BaseCommand):
    help = (
        "Report URLs that still require fallback to legacy local file fields."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--details",
            action="store_true",
            help="Print individual URLs requiring fallback.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help=(
                "Maximum details to display when --details is enabled "
                "(0 for unlimited)."
            ),
        )
        parser.add_argument(
            "--skip-disk-check",
            action="store_true",
            help=(
                "Skip verifying whether stored and legacy files exist on "
                "physical disk."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        show_details = options["details"]
        limit = options["limit"] or None
        skip_disk_check = options["skip_disk_check"]

        legacy_urls = list(
            URL.objects
            .filter(
                Q(local_filename__isnull=False) | Q(local_url__isnull=False)
            )
            .exclude(local_filename="", local_url="")
            .prefetch_related("fetches__stored_file")
            .order_by("id")
        )

        total_legacy = len(legacy_urls)
        migrated_count = 0
        fallback_urls: list[tuple[URL, str]] = []
        reason_counts: Counter[str] = Counter()
        kind_counts: Counter[str] = Counter()

        for url in legacy_urls:
            fetch = url.get_latest_fetch()
            if fetch is None:
                reason = "no_url_fetch"
            elif fetch.stored_file is None:
                reason = "no_stored_file"
            elif not skip_disk_check and not fetch.stored_file.exists():
                reason = "stored_file_missing_on_disk"
            else:
                migrated_count += 1
                continue

            fallback_urls.append((url, reason))
            reason_counts[reason] += 1
            kind = "upload" if url.is_uploaded else "backup"
            kind_counts[kind] += 1

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "=== Legacy Fallback Diagnostic Report ==="
            )
        )
        self.stdout.write(
            f"Total URLs with legacy local fields: {total_legacy}"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Fully migrated URLs (using StoredFile): {migrated_count}"
            )
        )
        if fallback_urls:
            count_str = str(len(fallback_urls))
            self.stdout.write(
                self.style.WARNING(
                    f"URLs requiring legacy fallback:      {count_str}"
                )
            )
            self.stdout.write("\nBreakdown by reason:")
            for reason, count in reason_counts.most_common():
                self.stdout.write(f"  - {reason}: {count}")
            self.stdout.write("\nBreakdown by kind:")
            for kind, count in kind_counts.most_common():
                self.stdout.write(f"  - {kind}: {count}")
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "URLs requiring legacy fallback:      0 (All clear!)"
                )
            )

        if show_details and fallback_urls:
            self.stdout.write(
                self.style.MIGRATE_HEADING("\n--- Fallback URL Details ---")
            )
            url_ids = [u.id for u, _ in fallback_urls]
            game_urls_by_url_id: dict[int, list[GameURL]] = defaultdict(list)
            for gu in GameURL.objects.filter(
                url_id__in=url_ids
            ).select_related("game", "category"):
                game_urls_by_url_id[gu.url_id].append(gu)

            display_list = fallback_urls[:limit] if limit else fallback_urls
            for u, reason in display_list:
                kind = "upload" if u.is_uploaded else "backup"
                self.stdout.write(f"URL #{u.id} [{kind}] (reason: {reason}):")
                self.stdout.write(f"  original_url:   {u.original_url}")
                self.stdout.write(f"  local_filename: {u.local_filename}")
                self.stdout.write(f"  local_url:      {u.local_url}")
                gus = game_urls_by_url_id.get(u.id, [])
                if gus:
                    games_str = ", ".join(
                        f"Game #{gu.game_id} '{gu.game.title}'" for gu in gus
                    )
                    self.stdout.write(f"  games:          {games_str}")
                else:
                    self.stdout.write("  games:          (none)")

            if limit and len(fallback_urls) > limit:
                remaining = len(fallback_urls) - limit
                self.stdout.write(
                    f"\n... and {remaining} more. Use --limit 0 to view all."
                )
