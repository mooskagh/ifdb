from dataclasses import dataclass

from django.db import transaction
from django.utils.timezone import now

from games.models import Game, GameAuthor, GameURL

from .models import GameHistory, GameHistoryAuditLog, GameSource


@dataclass(frozen=True)
class SplitOptions:
    keep_tags: bool
    copy_tags: bool
    keep_authors: bool
    copy_authors: bool
    keep_urls: bool
    copy_urls: bool
    keep_description: bool
    copy_description: bool


@transaction.atomic
def split_game_from_history(
    *,
    base_history: GameHistory,
    split_source_ids: list[int],
    split_title: str,
    options: SplitOptions,
    actor,
) -> GameHistory:
    base_history = GameHistory.objects.select_for_update().get(
        pk=base_history.pk
    )
    if base_history.game_id is None:
        raise ValueError("У этой истории нет игры для разделения.")
    if base_history.state == GameHistory.State.ABANDONED:
        raise ValueError("Заброшенную историю нельзя разделить.")
    if not split_source_ids:
        raise ValueError("Выберите хотя бы один источник для новой игры.")

    base_game = Game.objects.select_for_update().get(pk=base_history.game_id)
    split_sources = list(
        GameSource.objects.select_for_update().filter(
            pk__in=split_source_ids, history=base_history
        )
    )
    if len(split_sources) != len(set(split_source_ids)):
        raise ValueError("Некоторые выбранные источники не принадлежат игре.")

    split_game = Game.objects.create(
        title=split_title.strip() or base_game.title,
        description=(
            base_game.description if options.copy_description else None
        ),
        creation_time=now(),
        added_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    split_history = GameHistory.objects.create(
        game=split_game,
        creation_time=now(),
        state=GameHistory.State.SCHEDULED_FOR_UPDATE,
    )

    _copy_metadata(base_game, split_game, options)
    _prune_base_metadata(base_game, options)
    _move_sources(base_history, split_history, split_sources, actor)

    for history in [base_history, split_history]:
        old_state = history.state
        history.state = GameHistory.State.SCHEDULED_FOR_UPDATE
        history.processing_started_at = None
        history.processing_task_id = None
        history.edit_time = now()
        history.save(
            update_fields=[
                "state",
                "processing_started_at",
                "processing_task_id",
                "edit_time",
            ]
        )
        if old_state != history.state:
            GameHistoryAuditLog.record_change(
                history,
                actor,
                GameHistoryAuditLog.AuditField.STATE,
                old_state,
                history.state,
            )

    base_game.edit_time = now()
    base_game.save(update_fields=["edit_time"])
    split_game.edit_time = now()
    split_game.save(update_fields=["edit_time"])
    return split_history


def _copy_metadata(base_game: Game, split_game: Game, options: SplitOptions):
    if options.copy_tags:
        split_game.tags.set(base_game.tags.all())
    if options.copy_authors:
        GameAuthor.objects.bulk_create(
            GameAuthor(game=split_game, role=row.role, author=row.author)
            for row in GameAuthor.objects.filter(game=base_game)
        )
    if options.copy_urls:
        GameURL.objects.bulk_create(
            GameURL(
                game=split_game,
                url=row.url,
                category=row.category,
                description=row.description,
            )
            for row in GameURL.objects.filter(game=base_game)
        )
    if options.copy_description:
        split_game.description_attributions.set(
            base_game.description_attributions.all()
        )


def _prune_base_metadata(base_game: Game, options: SplitOptions):
    update_fields = []
    if not options.keep_tags:
        base_game.tags.clear()
    if not options.keep_authors:
        GameAuthor.objects.filter(game=base_game).delete()
    if not options.keep_urls:
        GameURL.objects.filter(game=base_game).delete()
    if not options.keep_description:
        base_game.description = None
        base_game.description_attributions.clear()
        update_fields.append("description")
    if update_fields:
        base_game.edit_time = now()
        update_fields.append("edit_time")
        base_game.save(update_fields=update_fields)


def _move_sources(
    base_history: GameHistory,
    split_history: GameHistory,
    sources: list[GameSource],
    actor,
):
    for source in sources:
        GameHistoryAuditLog.record_source(
            base_history,
            actor,
            GameHistoryAuditLog.AuditKind.SOURCE_DETACHED,
            source,
        )
        source.history = split_history
        source.save(update_fields=["history"])
        GameHistoryAuditLog.record_source(
            split_history,
            actor,
            GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED,
            source,
        )
