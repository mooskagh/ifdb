from dataclasses import dataclass

from django.db import transaction
from django.db.models import Model
from django.utils.timezone import now

from contest.models import CompetitionQuestion, CompetitionVote, GameListEntry
from core.models import Package
from games.models import Game, GameAuthor, GameComment, GameURL, GameVote

from .models import GameHistory, GameHistoryAuditLog, GameSource

CONTEST_RELATED_MODELS = [GameListEntry, CompetitionVote, CompetitionQuestion]
CONTEST_RELATED_LABELS = {
    GameListEntry: "списки игр",
    CompetitionVote: "голоса",
    CompetitionQuestion: "вопросы",
}


@dataclass(frozen=True)
class RelatedUsage:
    model: type[Model]
    count: int

    @property
    def label(self) -> str:
        return CONTEST_RELATED_LABELS.get(
            self.model, self.model._meta.verbose_name_plural
        )


def contest_related_usage(game: Game) -> list[RelatedUsage]:
    return [
        RelatedUsage(model, count)
        for model in CONTEST_RELATED_MODELS
        if (count := model.objects.filter(game=game).count())
    ]


@transaction.atomic
def merge_game_into_history(
    *,
    target_history: GameHistory,
    source_game: Game,
    actor,
    remap_contests: bool,
) -> None:
    target_game = target_history.game
    if target_game is None:
        raise ValueError("Target history has no game.")
    if source_game.pk == target_game.pk:
        raise ValueError("Cannot merge a game into itself.")

    source_history = getattr(source_game, "gamehistory", None)
    if source_history and source_history.pk == target_history.pk:
        raise ValueError("Cannot merge a game into itself.")

    usage = contest_related_usage(source_game)
    if usage and not remap_contests:
        raise ValueError("Contest references must be confirmed.")

    target_game = Game.objects.select_for_update().get(pk=target_game.pk)
    source_game = Game.objects.select_for_update().get(pk=source_game.pk)
    source_history = getattr(source_game, "gamehistory", None)

    if not target_game.release_date:
        target_game.release_date = source_game.release_date
    target_game.description = _merged_description(
        target_game.description, source_game.description
    )
    target_game.edit_time = now()
    target_game.save(
        update_fields=["release_date", "description", "edit_time"]
    )
    target_game.tags.add(*source_game.tags.all())

    _move_game_urls(source_game, target_game)
    _move_game_authors(source_game, target_game)
    _move_game_votes(source_game, target_game)
    _move_related(GameComment, source_game, target_game)
    _move_related(Package, source_game, target_game)
    if remap_contests:
        for model in CONTEST_RELATED_MODELS:
            _move_related(model, source_game, target_game)

    if source_history is not None:
        GameSource.objects.filter(history=source_history).update(
            history=target_history
        )
        GameHistoryAuditLog.record_game_merge(
            target_history, actor, source_game, target_game
        )
        GameHistoryAuditLog.record_game_merge(
            source_history, actor, source_game, target_game
        )
        old_state = source_history.state
        source_history.game = None
        source_history.state = GameHistory.State.ABANDONED
        source_history.auto_updates = GameHistory.AutoUpdate.REJECT
        source_history.processing_started_at = None
        source_history.processing_task_id = None
        source_history.edit_time = now()
        source_history.save(
            update_fields=[
                "game",
                "state",
                "auto_updates",
                "processing_started_at",
                "processing_task_id",
                "edit_time",
            ]
        )
        GameHistoryAuditLog.record_change(
            source_history,
            actor,
            GameHistoryAuditLog.AuditField.STATE,
            old_state,
            source_history.state,
        )
    else:
        GameHistoryAuditLog.record_game_merge(
            target_history, actor, source_game, target_game
        )

    source_game.delete()
    target_history.edit_time = now()
    target_history.save(update_fields=["edit_time"])


def _merged_description(left: str | None, right: str | None) -> str:
    return "\n\n".join(x for x in [left or "", right or ""] if x)


def _move_related(model: type[Model], source_game: Game, target_game: Game):
    model.objects.filter(game=source_game).update(game=target_game)


def _move_game_urls(source_game: Game, target_game: Game):
    for row in GameURL.objects.filter(game=source_game):
        if GameURL.objects.filter(
            game=target_game, category=row.category, url=row.url
        ).exists():
            row.delete()
            continue
        row.game = target_game
        row.save(update_fields=["game"])


def _move_game_authors(source_game: Game, target_game: Game):
    for row in GameAuthor.objects.filter(game=source_game).select_related(
        "author__personality"
    ):
        if GameAuthor.objects.filter(
            game=target_game,
            role=row.role,
            author__personality=row.author.personality,
        ).exists():
            row.delete()
            continue
        row.game = target_game
        row.save(update_fields=["game"])


def _move_game_votes(source_game: Game, target_game: Game):
    for row in GameVote.objects.filter(game=source_game):
        if GameVote.objects.filter(game=target_game, user=row.user).exists():
            row.delete()
            continue
        row.game = target_game
        row.save(update_fields=["game"])
