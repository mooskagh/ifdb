from django.db import transaction
from django.urls import reverse
from django.utils.timezone import now

from games.models import (
    Game,
    GameAuthorRole,
    GameTag,
    GameTagCategory,
    GameURLCategory,
    PersonalityAlias,
)

from .gameinfo import GameInfo
from .manual import editor_payload_to_gameinfo
from .merge import contest_related_usage
from .models import GameEdit, GameHistory, GameHistoryAuditLog, GameSource


def choices_payload():
    return {
        "authors": {
            "roles": [
                {"id": row.id, "title": row.title}
                for row in GameAuthorRole.objects.order_by("order", "title")
            ],
            "authors": [
                {"id": row.id, "name": row.name}
                for row in PersonalityAlias.objects.order_by("name")
            ],
        },
        "tags": {
            "categories": [
                {
                    "id": cat.id,
                    "name": cat.name,
                    "allow_new_tags": cat.allow_new_tags,
                    "tags": [
                        {"id": tag.id, "name": tag.name}
                        for tag in GameTag.objects.filter(
                            category=cat
                        ).order_by("name")
                    ],
                }
                for cat in GameTagCategory.objects.order_by("order", "name")
            ]
        },
        "links": {
            "categories": [
                {"id": row.id, "title": row.title}
                for row in GameURLCategory.objects.order_by("order", "title")
            ]
        },
    }


def source_payload(source: GameSource) -> dict:
    return {
        "id": source.id,
        "type": source.get_type_display(),
        "url": source.url or "",
        "detail_url": reverse("curation_source_detail", args=[source.id]),
    }


def column_for_history(history: GameHistory) -> dict:
    game = history.game
    if game is None:
        return _empty_column(
            client_id=f"history-{history.id}",
            history_id=history.id,
            sources=history.gamesource_set.order_by("id"),
        )
    return column_for_game(game, history=history)


def column_for_game(game: Game, *, history: GameHistory | None = None) -> dict:
    if history is None:
        history = getattr(game, "gamehistory", None)
    return {
        "client_id": f"game-{game.id}",
        "history_id": history.id if history else None,
        "game_id": game.id,
        "title": game.title or "",
        "release_date": game.release_date.isoformat()
        if game.release_date
        else "",
        "tags": [
            [tag.category_id, tag.id]
            for tag in game.tags.select_related("category").order_by(
                "category__order", "category__name", "name"
            )
        ],
        "authors": [
            [row.role_id, row.author_id]
            for row in game.gameauthor_set.order_by(
                "role__order", "role__title"
            )
        ],
        "links": [
            [
                row.category_id,
                row.description or "",
                row.url.original_url or "",
            ]
            for row in game.gameurl_set.select_related(
                "url", "category"
            ).order_by("category__order", "category__title", "id")
        ],
        "description_attributions": [
            row.name for row in game.description_attributions.order_by("name")
        ],
        "description": game.description or "",
        "sources": [
            source_payload(source)
            for source in (
                history.gamesource_set.order_by("id") if history else []
            )
        ],
        "delete": False,
    }


def initial_payload(history: GameHistory) -> dict:
    return {
        "base_history_id": history.id,
        "columns": [column_for_history(history)],
        "choices": choices_payload(),
    }


@transaction.atomic
def save_reconcile_payload(data: dict, actor) -> GameHistory:
    columns = [_normalized_column(col) for col in data.get("columns") or []]
    columns = [col for col in columns if not _is_empty_new_column(col)]
    orphan_source_ids = _clean_source_ids(data.get("orphan_source_ids") or [])
    if not columns:
        raise ValueError("Нет колонок для сохранения.")

    histories = _lock_histories(columns)
    games = _lock_games(columns, histories)
    _validate_columns(columns, histories, games)
    _validate_deletions(columns, histories, games, orphan_source_ids)
    sources = _lock_sources(columns, histories, orphan_source_ids)

    targets: dict[str, GameHistory | None] = {}
    for col in columns:
        targets[col["client_id"]] = _save_column(col, histories, games, actor)

    _move_sources(columns, sources, targets, orphan_source_ids, actor)
    _delete_marked_columns(columns, histories, games, actor)

    for history in {h for h in targets.values() if h is not None}:
        _schedule_history(history, actor)

    for history in histories.values():
        history.refresh_from_db()
    return _redirect_history(columns, histories, targets)


def _empty_column(*, client_id, history_id=None, sources=()):
    return {
        "client_id": client_id,
        "history_id": history_id,
        "game_id": None,
        "title": "",
        "release_date": "",
        "tags": [],
        "authors": [],
        "links": [],
        "description_attributions": [],
        "description": "",
        "sources": [source_payload(source) for source in sources],
        "delete": False,
    }


def _normalized_column(col: dict) -> dict:
    return {
        "client_id": str(col.get("client_id") or ""),
        "history_id": _int_or_none(col.get("history_id")),
        "game_id": _int_or_none(col.get("game_id")),
        "title": str(col.get("title") or "").strip(),
        "release_date": str(col.get("release_date") or "").strip(),
        "tags": _clean_pairs(col.get("tags") or []),
        "authors": _clean_pairs(col.get("authors") or []),
        "links": _clean_links(col.get("links") or []),
        "description_attributions": _clean_strings(
            col.get("description_attributions") or []
        ),
        "description": str(col.get("description") or ""),
        "sources": _clean_sources(col.get("sources") or []),
        "delete": bool(col.get("delete")),
    }


def _int_or_none(value):
    if value in (None, ""):
        return None
    return int(value)


def _clean_pairs(rows: list) -> list:
    return [
        row
        for row in rows
        if len(row) >= 2 and _filled(row[0]) and _filled(row[1])
    ]


def _clean_links(rows: list) -> list:
    return [
        row
        for row in rows
        if len(row) >= 3 and _filled(row[0]) and str(row[2]).strip()
    ]


def _clean_strings(rows: list) -> list[str]:
    return [value for value in (str(row).strip() for row in rows) if value]


def _clean_sources(rows: list) -> list[dict]:
    return [{"id": int(row["id"])} for row in rows if row.get("id")]


def _clean_source_ids(rows: list) -> list[int]:
    return list(dict.fromkeys(int(row) for row in rows if row))


def _filled(value) -> bool:
    return value is not None and str(value).strip() != ""


def _is_empty_new_column(col: dict) -> bool:
    return (
        col["history_id"] is None
        and col["game_id"] is None
        and not col["title"]
        and not col["release_date"]
        and not col["tags"]
        and not col["authors"]
        and not col["links"]
        and not col["description_attributions"]
        and not col["description"].strip()
        and not col["sources"]
    )


def _lock_histories(columns: list[dict]) -> dict[int, GameHistory]:
    ids = {col["history_id"] for col in columns if col["history_id"]}
    histories = {
        row.id: row
        for row in GameHistory.objects.select_for_update().filter(id__in=ids)
    }
    if missing := ids - set(histories):
        raise ValueError(f"Истории не найдены: {sorted(missing)}.")
    return histories


def _lock_games(
    columns: list[dict], histories: dict[int, GameHistory]
) -> dict[int, Game]:
    ids = {col["game_id"] for col in columns if col["game_id"]}
    ids |= {
        history.game_id for history in histories.values() if history.game_id
    }
    games = {
        row.id: row
        for row in Game.objects.select_for_update().filter(id__in=ids)
    }
    if missing := ids - set(games):
        raise ValueError(f"Игры не найдены: {sorted(missing)}.")
    return games


def _validate_columns(
    columns: list[dict],
    histories: dict[int, GameHistory],
    games: dict[int, Game],
):
    client_ids = [col["client_id"] for col in columns]
    if len(client_ids) != len(set(client_ids)):
        raise ValueError("В редакторе есть повторяющиеся колонки.")
    for col in columns:
        if not col["client_id"]:
            raise ValueError("У колонки нет технического id.")
        history = histories.get(col["history_id"])
        game = games.get(col["game_id"])
        if history and game and history.game_id != game.id:
            raise ValueError(
                f"История #{history.id} не относится к игре #{game.id}."
            )
        if col["delete"]:
            continue
        has_or_creates_game = bool(
            game
            or (history and history.game_id)
            or not history
            or _has_game_data(col)
        )
        if has_or_creates_game:
            if not col["title"]:
                raise ValueError(
                    "У каждой новой или существующей игры должно быть "
                    "название."
                )


def _validate_deletions(
    columns: list[dict],
    histories: dict[int, GameHistory],
    games: dict[int, Game],
    orphan_source_ids: list[int],
):
    non_deleted_clients = {
        col["client_id"] for col in columns if not col["delete"]
    }
    source_targets = {
        source["id"]: col["client_id"]
        for col in columns
        for source in col["sources"]
    }
    orphan_ids = set(orphan_source_ids)
    for col in columns:
        if not col["delete"] or col["game_id"] is None:
            continue
        game = games[col["game_id"]]
        if usage := contest_related_usage(game):
            related = ", ".join(
                f"{item.label}: {item.count}" for item in usage
            )
            raise ValueError(
                f"Игру #{game.id} нельзя удалить: "
                f"есть конкурсные ссылки ({related})."
            )
        if col["history_id"] is None:
            continue
        current_source_ids = set(
            GameSource.objects.filter(
                history=histories[col["history_id"]]
            ).values_list("id", flat=True)
        )
        remaining = sorted(
            source_id
            for source_id in current_source_ids
            if source_id not in orphan_ids
            and source_targets.get(source_id) not in non_deleted_clients
        )
        if remaining:
            ids = ", ".join(f"#{source_id}" for source_id in remaining)
            raise ValueError(
                "Нельзя удалить игру с источниками. "
                f"Сначала перенесите или открепите: {ids}."
            )


def _lock_sources(
    columns: list[dict],
    histories: dict[int, GameHistory],
    orphan_source_ids: list[int],
) -> dict[int, GameSource]:
    source_ids = [source["id"] for col in columns for source in col["sources"]]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError(
            "Один и тот же источник находится в нескольких колонках."
        )
    if overlap := set(source_ids) & set(orphan_source_ids):
        ids = ", ".join(f"#{source_id}" for source_id in sorted(overlap))
        raise ValueError(
            f"Источник нельзя одновременно оставить и открепить: {ids}."
        )
    wanted_source_ids = [*source_ids, *orphan_source_ids]
    sources = {
        row.id: row
        for row in GameSource.objects.select_for_update().filter(
            id__in=wanted_source_ids
        )
    }
    if missing := set(wanted_source_ids) - set(sources):
        raise ValueError(f"Источники не найдены: {sorted(missing)}.")
    allowed_history_ids = set(histories)
    for source in sources.values():
        if source.history_id not in allowed_history_ids:
            raise ValueError(
                f"Источник #{source.id} уже не принадлежит открытым историям."
            )
    return sources


def _save_column(
    col: dict,
    histories: dict[int, GameHistory],
    games: dict[int, Game],
    actor,
) -> GameHistory | None:
    history = histories.get(col["history_id"])
    if col["delete"]:
        return None

    game = games.get(col["game_id"])
    if game is None and history and history.game_id:
        game = games[history.game_id]
    if game is None and _has_game_data(col):
        game = _apply_game_info(col, None, history, actor)
        game.added_by = (
            actor if getattr(actor, "is_authenticated", False) else None
        )
        game.save(update_fields=["added_by"])
    elif game is not None:
        game = _apply_game_info(col, game, history, actor)

    if history is None and game is not None:
        history, _ = GameHistory.objects.select_for_update().get_or_create(
            game=game, defaults={"creation_time": now()}
        )
    elif (
        history is not None and game is not None and history.game_id != game.id
    ):
        history.game = game
        history.save(update_fields=["game"])
    return history


def _has_game_data(col: dict) -> bool:
    return any([
        col["title"],
        col["release_date"],
        col["tags"],
        col["authors"],
        col["links"],
        col["description_attributions"],
        col["description"].strip(),
    ])


def _apply_game_info(
    col: dict, game: Game | None, history: GameHistory | None, actor
) -> Game:
    before = GameInfo.from_game(game).to_canonical() if game else ""
    info = editor_payload_to_gameinfo({
        "title": col["title"],
        "release_date": col["release_date"],
        "tags": col["tags"],
        "authors": col["authors"],
        "links": col["links"],
        "description_attributions": col["description_attributions"],
        "desc": col["description"],
    })
    game, after = info.save(game)
    if history is None:
        history, _ = GameHistory.objects.get_or_create(
            game=game, defaults={"creation_time": now()}
        )
    elif history.game_id != game.id:
        history.game = game
        history.save(update_fields=["game"])
    if before.rstrip("\n") != after.rstrip("\n"):
        GameEdit.objects.create(
            history=history,
            proposed_at=now(),
            approved_at=now(),
            proposed_by=actor,
            approver=actor,
            status=GameEdit.EditStatus.APPLIED,
            origin=GameEdit.Origin.MANUAL_EDIT,
            previous_canonical_text=before,
            canonical_text=after,
        )
    return game


def _move_sources(
    columns: list[dict],
    sources: dict[int, GameSource],
    targets: dict[str, GameHistory | None],
    orphan_source_ids: list[int],
    actor,
):
    for source_id in orphan_source_ids:
        _move_source(sources[source_id], None, actor)

    history_by_source = {
        source["id"]: targets[col["client_id"]]
        for col in columns
        for source in col["sources"]
    }
    for source_id, target_history in history_by_source.items():
        _move_source(sources[source_id], target_history, actor)


def _move_source(
    source: GameSource, target_history: GameHistory | None, actor
):
    if source.history_id == (target_history.id if target_history else None):
        return
    old_history = source.history
    if old_history is not None:
        GameHistoryAuditLog.record_source(
            old_history,
            actor,
            GameHistoryAuditLog.AuditKind.SOURCE_DETACHED,
            source,
        )
    source.history = target_history
    source.save(update_fields=["history"])
    if target_history is not None:
        GameHistoryAuditLog.record_source(
            target_history,
            actor,
            GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED,
            source,
        )


def _delete_marked_columns(
    columns: list[dict],
    histories: dict[int, GameHistory],
    games: dict[int, Game],
    actor,
):
    for col in columns:
        if not col["delete"]:
            continue
        history = histories.get(col["history_id"])
        game = games.get(col["game_id"])
        if history is not None:
            old_state = history.state
            history.game = None
            history.state = GameHistory.State.ABANDONED
            history.auto_updates = GameHistory.AutoUpdate.REJECT
            history.processing_started_at = None
            history.processing_task_id = None
            history.edit_time = now()
            history.save(
                update_fields=[
                    "game",
                    "state",
                    "auto_updates",
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
        if game is not None:
            game.delete()


def _schedule_history(history: GameHistory, actor):
    history.refresh_from_db()
    if history.state == GameHistory.State.ABANDONED:
        return
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


def _redirect_history(
    columns: list[dict],
    histories: dict[int, GameHistory],
    targets: dict[str, GameHistory | None],
) -> GameHistory:
    for col in columns:
        if not col["delete"] and targets.get(col["client_id"]):
            return targets[col["client_id"]]
    for col in columns:
        if col["history_id"] and col["history_id"] in histories:
            return histories[col["history_id"]]
    raise ValueError("Не удалось выбрать страницу для перехода.")
