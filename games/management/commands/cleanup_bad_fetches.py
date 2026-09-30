from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import Q

from games.fetcher import (
    ERROR_RESPONSE_LIMIT,
    ERROR_RESPONSE_RULES,
    error_response_reason,
)
from games.models import URL, URLFetch


def find_bad_fetches() -> list[tuple[URLFetch, str]]:
    domain_q = Q()
    for domain, _, _ in ERROR_RESPONSE_RULES:
        domain_q |= Q(url__original_url__icontains=domain)

    candidates = (
        URLFetch.objects
        .filter(domain_q)
        .filter(stored_file__file_size__lte=ERROR_RESPONSE_LIMIT)
        .select_related("url", "stored_file")
    )

    bad_fetches: list[tuple[URLFetch, str]] = []
    for fetch in candidates:
        if (
            not fetch.url
            or not fetch.url.original_url
            or not fetch.stored_file
        ):
            continue
        try:
            with fetch.stored_file.open("rb") as f:
                body = f.read(ERROR_RESPONSE_LIMIT)
        except (OSError, FileNotFoundError):
            continue

        reason = error_response_reason(
            url=fetch.url.original_url,
            content_type=fetch.content_type,
            body=body,
            size=fetch.stored_file.file_size,
        )
        if reason:
            bad_fetches.append((fetch, reason))

    return bad_fetches


class Command(BaseCommand):
    help = "Find and delete URLFetches that are actually error responses."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete bad URLFetch records and update parent URLs.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        should_delete: bool = options["delete"]
        bad_fetches = find_bad_fetches()

        if not bad_fetches:
            self.stdout.write(self.style.SUCCESS("No bad fetches found."))
            return

        self.stdout.write(f"Found {len(bad_fetches)} bad fetch(es):")
        for fetch, reason in bad_fetches:
            self.stdout.write(
                f"- Fetch #{fetch.pk} | URL #{fetch.url_id}: "
                f"{fetch.url.original_url}\n"
                f"    Reason: {reason}\n"
                f"    File: {fetch.stored_file.storage_path} "
                f"({fetch.stored_file.file_size} bytes)\n"
                f"    Date: {fetch.last_fetch}"
            )

        if not should_delete:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry run only. Run with --delete to delete."
                )
            )
            return

        by_url: dict[URL, list[tuple[URLFetch, str]]] = {}
        for fetch, reason in bad_fetches:
            by_url.setdefault(fetch.url, []).append((fetch, reason))

        with transaction.atomic():
            deleted_count = 0
            for url, items in by_url.items():
                latest = url.get_latest_fetch()
                was_latest = any(
                    f.pk == (latest.pk if latest else None) for f, _ in items
                )

                for fetch, _ in items:
                    fetch.delete()
                    deleted_count += 1

                if was_latest:
                    latest_bad = max(
                        items,
                        key=lambda pair: (pair[0].last_fetch, pair[0].pk),
                    )
                    url.last_error = latest_bad[1]
                    if not url.failing_since:
                        url.failing_since = latest_bad[0].last_fetch
                    url.save(update_fields=["last_error", "failing_since"])

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSuccessfully deleted {deleted_count} fetch(es) "
                f"across {len(by_url)} URL(s)."
            )
        )
