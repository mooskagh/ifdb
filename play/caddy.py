import logging
from pathlib import Path
from typing import Any

import requests
from django.conf import settings

from play.models import Playable

logger = logging.getLogger("worker")
REQUEST_TIMEOUT_SECONDS = 5


def caddy_route_id_for_playable(playable_pk: int) -> str:
    return f"playable_{playable_pk}"


def caddy_route_payload(playable: Playable) -> dict[str, Any]:
    root_dir = str(Path(settings.PLAYABLE_DIR) / str(playable.pk))
    host = f"{playable.slug}.{settings.PLAYABLE_BASE_DOMAIN}"
    return {
        "@id": caddy_route_id_for_playable(playable.pk),
        "match": [{"host": [host]}],
        "handle": [{"handler": "file_server", "root": root_dir}],
    }


def configure_caddy_playable(playable: Playable) -> bool:
    admin_url_setting = getattr(settings, "CADDY_ADMIN_URL", None)
    if not admin_url_setting or not playable.slug:
        return False

    admin_url = str(admin_url_setting).rstrip("/")
    route_id = caddy_route_id_for_playable(playable.pk)
    payload = caddy_route_payload(playable)

    try:
        check_resp = requests.get(
            f"{admin_url}/id/{route_id}",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if check_resp.status_code == 200:
            # Route exists with this @id, update it
            update_resp = requests.put(
                f"{admin_url}/id/{route_id}",
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            update_resp.raise_for_status()
            logger.info("Updated Caddy route @id=%s", route_id)
            return True
        elif check_resp.status_code == 404:
            # Route does not exist, append to server routes
            server_name = getattr(settings, "CADDY_SERVER_NAME", "srv0")
            routes_url = (
                f"{admin_url}/config/apps/http/servers/{server_name}/routes/"
            )
            post_resp = requests.post(
                routes_url,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            post_resp.raise_for_status()
            logger.info(
                "Created Caddy route @id=%s on server %s",
                route_id,
                server_name,
            )
            return True
        else:
            logger.warning(
                "Unexpected status %s checking Caddy @id=%s: %s",
                check_resp.status_code,
                route_id,
                check_resp.text,
            )
            return False
    except requests.RequestException:
        logger.exception(
            "Failed to configure Caddy route @id=%s via %s",
            route_id,
            admin_url,
        )
        return False


def delete_caddy_playable(playable_pk: int) -> bool:
    admin_url_setting = getattr(settings, "CADDY_ADMIN_URL", None)
    if not admin_url_setting:
        return False

    admin_url = str(admin_url_setting).rstrip("/")
    route_id = caddy_route_id_for_playable(playable_pk)
    try:
        resp = requests.delete(
            f"{admin_url}/id/{route_id}",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if resp.status_code in (200, 404):
            logger.info("Deleted Caddy route @id=%s", route_id)
            return True
        logger.warning(
            "Failed to delete Caddy route @id=%s (status %s): %s",
            route_id,
            resp.status_code,
            resp.text,
        )
        return False
    except requests.RequestException:
        logger.exception(
            "Exception deleting Caddy route @id=%s via %s", route_id, admin_url
        )
        return False
