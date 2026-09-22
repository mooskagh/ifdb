from django.conf import settings
from django.db import transaction

from games.models import Game, GameURL
from play.models import Playable


class PinnedURLError(ValueError):
    """Raised when an operation would remove or modify a pinned GameURL."""


def format_pinned_url_error(game_url: GameURL) -> str:
    domain = getattr(settings, "PLAYABLE_BASE_DOMAIN", "play.crem.xyz")
    sites = [
        f"{p.slug}.{domain}" if p.slug else f"#{p.pk}"
        for p in game_url.playables.all()
    ]
    plural = "ы" if len(sites) > 1 else ""
    return (
        f"URL нельзя удалить: из него создан{plural} сайт{plural} "
        f"{', '.join(sites)}"
    )


@transaction.atomic
def move_game_url(source_url: GameURL, target_game: Game) -> GameURL:
    src = GameURL.objects.select_for_update().get(pk=source_url.pk)
    target = Game.objects.select_for_update().get(pk=target_game.pk)
    if src.game_id == target.pk:
        Playable.objects.filter(game_url=src).update(game=target)
        return src

    dest = (
        GameURL.objects
        .select_for_update()
        .filter(game=target, category_id=src.category_id, url_id=src.url_id)
        .first()
    )
    if dest is not None:
        Playable.objects.filter(game_url=src).update(
            game=target, game_url=dest
        )
        src.delete()
        return dest

    src.game = target
    src.save(update_fields=["game"])
    Playable.objects.filter(game_url=src).update(game=target)
    return src


@transaction.atomic
def transfer_game_playables(source_game: Game, target_game: Game) -> None:
    pinned = list(
        source_game.gameurl_set.filter(playables__isnull=False).distinct()
    )
    for gu in pinned:
        move_game_url(gu, target_game)
    Playable.objects.filter(game=source_game, game_url__isnull=True).update(
        game=target_game
    )
