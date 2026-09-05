from dataclasses import dataclass

from django.db import transaction
from django.db.models import Model
from django.utils.timezone import now

from contest.models import CompetitionQuestion, CompetitionVote, GameListEntry
from core.models import Package
from games.gameinfo import GameInfo, merge
from games.models import (
    Game,
    GameAuthor,
    GameComment,
    GameRevision,
    GameURL,
    GameVote,
)

from .models import GameCuration, GameHistoryAuditLog, GameSource

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
def merge_game_into_game(
    *,
    target_game: Game,
    source_game: Game,
    actor,
    remap_contests: bool,
) -> None:
    if source_game.pk == target_game.pk:
        raise ValueError("Cannot merge a game into itself.")

    usage = contest_related_usage(source_game)
    if usage and not remap_contests:
        raise ValueError("Contest references must be confirmed.")

    target_game = Game.objects.select_for_update().get(pk=target_game.pk)
    source_game = Game.objects.select_for_update().get(pk=source_game.pk)
    source_curation = getattr(source_game, "curation", None)

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

    target_info = (
        GameInfo.from_game(target_game)
        if target_game.published_revision_id
        else None
    )
    source_info = (
        GameInfo.from_game(source_game)
        if source_game.published_revision_id
        else None
    )
    if target_info and source_info:
        merged_info = merge(target_info, source_info)
    elif target_info:
        merged_info = target_info
        if not merged_info.date and target_game.release_date:
            merged_info.date = target_game.release_date.isoformat()
        merged_info.description = target_game.description
    elif source_info:
        merged_info = source_info
        merged_info.name = target_game.title
        merged_info.description = target_game.description
    else:
        merged_info = GameInfo(
            name=target_game.title,
            description=target_game.description,
            date=(
                target_game.release_date.isoformat()
                if target_game.release_date
                else None
            ),
        )

    previous_canonical_text = (
        target_game.published_revision.canonical_text
        if target_game.published_revision_id
        else ""
    )
    rev = GameRevision(
        game=target_game,
        created_at=now(),
        created_by=actor,
        origin=GameRevision.Origin.MERGE,
        previous_canonical_text=previous_canonical_text,
        canonical_text=merged_info.to_canonical(),
    )
    target_game.publish_revision(rev, actor=actor)

    GameSource.objects.filter(game=source_game).update(game=target_game)
    GameHistoryAuditLog.record_game_merge(
        target_game, actor, source_game, target_game
    )
    if source_curation is not None:
        GameHistoryAuditLog.record_game_merge(
            source_game, actor, source_game, target_game
        )
        old_state = source_curation.state
        source_curation.state = GameCuration.State.ABANDONED
        source_curation.auto_updates = GameCuration.AutoUpdate.REJECT
        source_curation.processing_started_at = None
        source_curation.processing_task_id = None
        source_curation.save(
            update_fields=[
                "state",
                "auto_updates",
                "processing_started_at",
                "processing_task_id",
            ]
        )
        GameHistoryAuditLog.record_change(
            source_game,
            actor,
            GameHistoryAuditLog.AuditField.STATE,
            old_state,
            source_curation.state,
        )

    source_game.state = Game.State.REDIRECT
    source_game.redirect_to = target_game
    source_game.save(update_fields=["state", "redirect_to"])


def merge_game_into_history(
    *,
    target_history,
    source_game: Game,
    actor,
    remap_contests: bool,
) -> None:
    target_game = (
        target_history.game
        if hasattr(target_history, "game")
        else target_history
    )
    return merge_game_into_game(
        target_game=target_game,
        source_game=source_game,
        actor=actor,
        remap_contests=remap_contests,
    )


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
