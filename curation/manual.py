from django.db import transaction
from django.utils.timezone import now

from games.importer.discord import PostNewGameToDiscord
from games.models import (
    Game,
    GameAuthorRole,
    GameDescriptionAttribution,
    GameTag,
    GameTagCategory,
    GameURLCategory,
)

from .gameinfo import Attribution, GameInfo, GameUrl, Person, Tag
from .models import GameEdit, GameHistory, GameHistoryAuditLog


def editor_payload_to_gameinfo(data: dict) -> GameInfo:
    info = GameInfo(
        name=data.get("title") or None,
        date=data.get("release_date") or None,
        description=data.get("desc") or None,
    )
    info.personalities = _personalities_from_payload(data.get("authors") or [])
    info.tags = [_tag_from_payload(row) for row in data.get("tags") or []]
    info.urls = [_url_from_payload(row) for row in data.get("links") or []]
    info.attributions = [
        _attribution_from_payload(item)
        for item in data.get("description_attributions") or []
        if str(item).strip()
    ]
    info.canonicalize()
    return info


@transaction.atomic
def store_manual_edit(
    game: Game, data: dict, user, *, apply: bool
) -> GameEdit:
    history = _history_for_game(game)
    before = GameInfo.from_game(game).to_canonical()
    info = editor_payload_to_gameinfo(data)
    canonical = info.to_canonical()
    previous_edit = _latest_applied_edit(history)
    edit = GameEdit.objects.create(
        history=history,
        proposed_at=now(),
        proposed_by=user,
        origin=(
            GameEdit.Origin.MANUAL_EDIT
            if apply
            else GameEdit.Origin.USER_SUGGESTION
        ),
        status=(
            GameEdit.EditStatus.APPLIED
            if apply
            else GameEdit.EditStatus.PROPOSED
        ),
        approved_at=now() if apply else None,
        approver=user if apply else None,
        previous_canonical_text=before if apply else None,
        canonical_text=canonical,
    )
    if previous_edit is not None:
        edit.used_sources.set(previous_edit.used_sources.all())

    if apply:
        _, after = info.save(game)
        edit.canonical_text = after
        edit.save(update_fields=["canonical_text"])
        GameHistoryAuditLog.record_change(
            history,
            user,
            GameHistoryAuditLog.AuditField.CANONICAL_TEXT,
            before,
            after,
        )
        history.state = GameHistory.State.SETTLED
        history.attention_reason = None
    else:
        history.state = GameHistory.State.NEEDS_ATTENTION
        history.attention_reason = "Пользователь предложил правку"
    history.edit_time = now()
    history.save(update_fields=["state", "attention_reason", "edit_time"])
    return edit


@transaction.atomic
def store_manual_add(data: dict, user, *, apply: bool) -> GameEdit:
    history = GameHistory.objects.create(creation_time=now())
    info = editor_payload_to_gameinfo(data)
    canonical = info.to_canonical()
    edit = GameEdit.objects.create(
        history=history,
        proposed_at=now(),
        proposed_by=user,
        origin=(
            GameEdit.Origin.MANUAL_EDIT
            if apply
            else GameEdit.Origin.USER_SUGGESTION
        ),
        status=(
            GameEdit.EditStatus.APPLIED
            if apply
            else GameEdit.EditStatus.PROPOSED
        ),
        approved_at=now() if apply else None,
        approver=user if apply else None,
        previous_canonical_text="" if apply else None,
        canonical_text=canonical,
    )

    if apply:
        game, after = info.save(None)
        game.added_by = user
        game.save(update_fields=["added_by"])
        edit.canonical_text = after
        edit.save(update_fields=["canonical_text"])
        history.game = game
        history.state = GameHistory.State.SETTLED
        history.attention_reason = None
        GameHistoryAuditLog.record_change(
            history,
            user,
            GameHistoryAuditLog.AuditField.CANONICAL_TEXT,
            "",
            after,
        )
        PostNewGameToDiscord(game.id)
    else:
        history.state = GameHistory.State.NEEDS_ATTENTION
        history.attention_reason = "Пользователь предложил новую игру"
    history.edit_time = now()
    history.save(
        update_fields=["game", "state", "attention_reason", "edit_time"]
    )
    return edit


def _history_for_game(game: Game) -> GameHistory:
    history, _ = GameHistory.objects.get_or_create(
        game=game,
        defaults={"creation_time": now()},
    )
    return history


def _latest_applied_edit(history: GameHistory) -> GameEdit | None:
    return (
        history.gameedit_set
        .filter(status=GameEdit.EditStatus.APPLIED)
        .order_by("-approved_at", "-proposed_at", "-id")
        .first()
    )


def _personalities_from_payload(rows: list) -> dict[str, list[Person]]:
    personalities: dict[str, list[Person]] = {}
    for role_value, person_value, *_ in rows:
        role_slug = _role_slug(role_value)
        person = (
            Person(person_value, "")
            if isinstance(person_value, int)
            else Person(None, str(person_value).strip())
        )
        if person.alias_id is None and not person.name:
            continue
        personalities.setdefault(role_slug, []).append(person)
    return personalities


def _role_slug(value) -> str:
    if isinstance(value, int):
        return GameAuthorRole.objects.get(pk=value).symbolic_id
    return str(value)


def _tag_from_payload(row: list) -> Tag:
    cat_value, tag_value = row
    category = (
        GameTagCategory.objects.get(pk=cat_value).symbolic_id
        if isinstance(cat_value, int)
        else str(cat_value)
    )
    if isinstance(tag_value, int):
        tag = GameTag.objects.select_related("category").get(pk=tag_value)
        return Tag(tag.category.symbolic_id, tag.symbolic_id, tag.id, None)
    return Tag(category, None, None, str(tag_value).strip())


def _url_from_payload(row: list) -> GameUrl:
    cat_value, description, url = row
    category = (
        GameURLCategory.objects.get(pk=cat_value).symbolic_id
        if isinstance(cat_value, int)
        else str(cat_value)
    )
    return GameUrl(category, None, description or None, url or None)


def _attribution_from_payload(value) -> Attribution:
    if isinstance(value, int):
        return Attribution(value, "")
    name = str(value).strip()
    attr, _ = GameDescriptionAttribution.objects.get_or_create(name=name)
    return Attribution(attr.id, "")
