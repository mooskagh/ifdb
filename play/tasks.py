import os
import shutil
import stat
from pathlib import Path

from celery import shared_task
from django.conf import settings

from play.blueprint import GenerateSpec, discover_blueprints
from play.caddy import configure_caddy_playable
from play.domain import generate_playable_domain
from play.models import Playable


def ensure_group_readable(destination: Path) -> None:
    if not destination.exists():
        return
    for root, dirs, files in os.walk(destination):
        root_path = Path(root)
        if not root_path.is_symlink():
            mode = root_path.stat().st_mode & 0o777
            target = mode | stat.S_IRGRP | stat.S_IXGRP
            if mode != target:
                root_path.chmod(target)
        for f in files:
            file_path = root_path / f
            if not file_path.is_symlink():
                mode = file_path.stat().st_mode & 0o777
                target = mode | stat.S_IRGRP
                if mode != target:
                    file_path.chmod(target)
    if destination.is_file() and not destination.is_symlink():
        mode = destination.stat().st_mode & 0o777
        target = mode | stat.S_IRGRP
        if mode != target:
            destination.chmod(target)


@shared_task  # type: ignore[untyped-decorator]
def generate_playable(playable_id: int) -> None:
    playable = Playable.objects.select_related("game_url__url", "game").get(
        pk=playable_id
    )
    playable.state = Playable.State.BUILDING
    playable.save(update_fields=["state", "updated"])

    try:
        blueprints = {
            info.name: info.blueprint for info in discover_blueprints()
        }
        blueprint = blueprints.get(playable.template)
        if blueprint is None:
            raise ValueError(f"Blueprint {playable.template} not found")

        if not playable.game_url or not playable.game_url.url:
            raise ValueError("Playable has no associated game_url")

        url = playable.game_url.url
        storage = url.GetFs()
        local_filename = url.local_filename
        if not local_filename or not storage.exists(local_filename):
            raise FileNotFoundError(f"Local file not found for URL {url.pk}")

        game_file = Path(storage.path(local_filename))
        destination = Path(settings.PLAYABLE_DIR) / str(playable.pk)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)

        if not playable.slug:
            playable.slug = generate_playable_domain(
                playable.game, current_playable_pk=playable.pk
            )
            playable.save(update_fields=["slug", "updated"])

        spec = GenerateSpec(
            version=playable.template_version,
            config=playable.config,
            destination=destination,
            game_file=game_file,
        )
        blueprint.generate(spec)

        ensure_group_readable(destination)

        if getattr(settings, "CADDY_ADMIN_URL", None):
            if not configure_caddy_playable(playable):
                raise RuntimeError(
                    f"Failed to configure Caddy for playable {playable.pk}"
                )

        playable.state = Playable.State.READY
        playable.save(update_fields=["state", "updated"])
    except Exception:
        destination = Path(settings.PLAYABLE_DIR) / str(playable.pk)
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        playable.state = Playable.State.ERROR
        playable.save(update_fields=["state", "updated"])
        raise
