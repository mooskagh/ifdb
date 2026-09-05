from django.db import transaction
from django.utils.timezone import now

from games.gameinfo import Attribution, GameInfo, GameUrl, Person, Tag
from games.importer.discord import PostNewGameToDiscord
from games.models import (
    Game,
    GameAuthorRole,
    GameDescriptionAttribution,
    GameRevision,
    GameTag,
    GameTagCategory,
    GameURLCategory,
)

from .models import GameCuration, GameHistoryAuditLog


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
) -> GameRevision:
    curation = _curation_for_game(game)
    previous_edit = _latest_applied_edit(game)
    before = previous_edit.canonical_text if previous_edit else ""
    info = editor_payload_to_gameinfo(data)
    canonical = info.to_canonical()
    edit = GameRevision.objects.create(
        game=game,
        created_at=now(),
        created_by=user,
        origin=(
            GameRevision.Origin.MANUAL_EDIT
            if apply
            else GameRevision.Origin.USER_SUGGESTION
        ),
        status=(
            GameRevision.Status.ACCEPTED
            if apply
            else GameRevision.Status.PROPOSED
        ),
        published_at=now() if apply else None,
        published_by=user if apply else None,
        previous_canonical_text=before if apply else None,
        canonical_text=canonical,
    )
    if previous_edit is not None:
        edit.used_sources.set(previous_edit.used_sources.all())

    old_note = curation.note
    if apply:
        game.publish_revision(edit, actor=user)
        curation.state = GameCuration.State.SETTLED
        curation.note = None
    else:
        curation.state = GameCuration.State.NEEDS_ATTENTION
        curation.note = "Пользователь предложил правку"
    GameHistoryAuditLog.record_note_change(game, user, old_note, curation.note)
    curation.save(update_fields=["state", "note"])
    return edit


@transaction.atomic
def store_manual_add(data: dict, user, *, apply: bool) -> GameRevision:
    info = editor_payload_to_gameinfo(data)
    canonical = info.to_canonical()
    game, after = info.save(
        None, state=Game.State.PUBLISHED if apply else Game.State.DRAFT
    )
    game.added_by = user
    game.save(update_fields=["added_by"])

    curation = GameCuration.objects.create(
        game=game,
        state=(
            GameCuration.State.SETTLED
            if apply
            else GameCuration.State.NEEDS_ATTENTION
        ),
        note=None if apply else "Пользователь предложил новую игру",
    )
    edit = GameRevision.objects.create(
        game=game,
        created_at=now(),
        created_by=user,
        origin=(
            GameRevision.Origin.MANUAL_EDIT
            if apply
            else GameRevision.Origin.USER_SUGGESTION
        ),
        status=(
            GameRevision.Status.ACCEPTED
            if apply
            else GameRevision.Status.PROPOSED
        ),
        published_at=now() if apply else None,
        published_by=user if apply else None,
        previous_canonical_text="" if apply else None,
        canonical_text=after if apply else canonical,
    )
    if not apply:
        GameHistoryAuditLog.record_note_change(game, user, None, curation.note)
    else:
        game.publish_revision(edit, actor=user)
        PostNewGameToDiscord(game.id)
    return edit


def _curation_for_game(game: Game) -> GameCuration:
    curation, _ = GameCuration.objects.get_or_create(game=game)
    return curation


_history_for_game = _curation_for_game


def _latest_applied_edit(target: Game | GameCuration) -> GameRevision | None:
    game = target.game if isinstance(target, GameCuration) else target
    if game.published_revision_id:
        return game.published_revision
    return (
        game.gamerevision_set
        .filter(status=GameRevision.Status.ACCEPTED)
        .order_by("-published_at", "-created_at", "-id")
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
