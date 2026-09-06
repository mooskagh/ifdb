import shutil
from pathlib import Path

from celery import shared_task
from django.conf import settings

from play.blueprint import GenerateSpec, discover_blueprints
from play.models import Playable


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

        spec = GenerateSpec(
            version=playable.template_version,
            config=playable.config,
            destination=destination,
            game_file=game_file,
        )
        blueprint.generate(spec)

        playable.state = Playable.State.READY
        playable.save(update_fields=["state", "updated"])
    except Exception:
        playable.state = Playable.State.ERROR
        playable.save(update_fields=["state", "updated"])
        raise
