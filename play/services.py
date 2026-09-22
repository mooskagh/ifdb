from collections.abc import Sequence

from django.conf import settings
from django.db import transaction

from games.models import Game, GameURL
from play.models import Playable


class PinnedURLError(ValueError):
    """Raised when an operation would remove or modify a pinned GameURL."""


def is_game_url_pinned(game_url: GameURL | int) -> bool:
    """Return True if the GameURL is referenced by one or more Playables."""
    if isinstance(game_url, int):
        return bool(Playable.objects.filter(game_url_id=game_url).exists())
    return bool(game_url.playables.exists())


def get_pinned_playables(game_url: GameURL | int) -> list[Playable]:
    """Return all Playables referencing the GameURL."""
    if isinstance(game_url, int):
        return list(
            Playable.objects.filter(game_url_id=game_url).order_by("pk")
        )
    return list(game_url.playables.order_by("pk"))


def format_pinned_url_error(
    game_url: GameURL, playables: Sequence[Playable] | None = None
) -> str:
    """Produce a human-readable error naming the affected playable site(s)."""
    if playables is None:
        playables = get_pinned_playables(game_url)

    sites: list[str] = []
    base_domain = getattr(settings, "PLAYABLE_BASE_DOMAIN", "play.crem.xyz")
    for p in playables:
        if p.slug:
            sites.append(f"{p.slug}.{base_domain}")
        else:
            sites.append(f"playable #{p.pk}")

    if len(sites) == 1:
        return f"URL нельзя удалить: из него создан сайт {sites[0]}"
    sites_str = ", ".join(sites)
    return f"URL нельзя удалить: из него созданы сайты {sites_str}"


@transaction.atomic
def move_game_url(source_url: GameURL, target_game: Game) -> GameURL:
    """Move a GameURL to target_game together with referencing Playables.

    If target_game already has an equivalent (category, url) GameURL:
    - repoint attached Playables to the destination GameURL;
    - update Playable.game = target_game;
    - delete the duplicate source row.

    If target_game does not have an equivalent row:
    - update source GameURL.game = target_game;
    - update attached Playable.game = target_game.
    """
    src = GameURL.objects.select_for_update().get(pk=source_url.pk)
    target = Game.objects.select_for_update().get(pk=target_game.pk)

    if src.game_id == target.pk:
        Playable.objects.filter(game_url=src).exclude(game=target).update(
            game=target
        )
        return src

    dest = (
        GameURL.objects
        .select_for_update()
        .filter(game=target, category_id=src.category_id, url_id=src.url_id)
        .first()
    )

    if dest is not None:
        playables = list(
            Playable.objects.select_for_update().filter(game_url=src)
        )
        for p in playables:
            p.game = target
            p.game_url = dest
            p.save(update_fields=["game", "game_url"])
        src.delete()
        return dest

    src.game = target
    src.save(update_fields=["game"])
    playables = list(Playable.objects.select_for_update().filter(game_url=src))
    for p in playables:
        p.game = target
        p.save(update_fields=["game"])
    return src


@transaction.atomic
def transfer_game_playables(source_game: Game, target_game: Game) -> None:
    """Transfer all playables belonging to source_game to target_game.

    For playables with game_url, moves GameURL (and any attached playables).
    For playables with game_url=None, updates playable.game directly.
    """
    target = Game.objects.select_for_update().get(pk=target_game.pk)
    source = Game.objects.select_for_update().get(pk=source_game.pk)

    playables = list(Playable.objects.select_for_update().filter(game=source))
    processed_url_ids: set[int] = set()

    for p in playables:
        if p.game_url_id is not None:
            if p.game_url_id not in processed_url_ids:
                move_game_url(p.game_url, target)
                processed_url_ids.add(p.game_url_id)
        else:
            p.game = target
            p.save(update_fields=["game"])
