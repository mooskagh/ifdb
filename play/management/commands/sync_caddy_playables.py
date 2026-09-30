import re
from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from play.caddy import REQUEST_TIMEOUT_SECONDS, caddy_route_payload
from play.models import Playable


class Command(BaseCommand):
    help = (
        "Reconcile Caddy playable routes with READY playables in the database."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        admin_url = getattr(settings, "CADDY_ADMIN_URL", None)
        if not admin_url:
            raise CommandError("CADDY_ADMIN_URL is not configured.")
        server = getattr(settings, "CADDY_SERVER_NAME", "srv0")
        routes_url = (
            f"{str(admin_url).rstrip('/')}/config/apps/http/servers/"
            f"{server}/routes/"
        )

        try:
            response = requests.get(
                routes_url, timeout=REQUEST_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            routes = response.json()
            if not isinstance(routes, list) or any(
                not isinstance(route, dict) for route in routes
            ):
                raise CommandError("Expected a Caddy route array.")

            playables = (
                Playable.objects
                .filter(state=Playable.State.READY, slug__isnull=False)
                .exclude(slug="")
                .order_by("pk")
            )
            desired = [caddy_route_payload(playable) for playable in playables]
            retained: list[dict[str, Any]] = []
            insertion_index: int | None = None
            removed = 0
            for route in routes:
                route_id = route.get("@id")
                if isinstance(route_id, str) and re.fullmatch(
                    r"playable_\d+", route_id
                ):
                    if insertion_index is None:
                        insertion_index = len(retained)
                    removed += 1
                else:
                    retained.append(route)
            if insertion_index is None:
                insertion_index = len(retained)
            retained[insertion_index:insertion_index] = desired

            if retained == routes:
                self.stdout.write("Playable routes are already in sync.")
                return

            response = requests.patch(
                routes_url,
                json=retained,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(
                f"Failed to reconcile Caddy routes: {exc}"
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Replaced {removed} playable routes with "
                f"{len(desired)} current routes on {server}."
            )
        )
