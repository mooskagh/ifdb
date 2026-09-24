from django.db import transaction
from django.utils.timezone import now

from games.gameinfo import (
    Attribution,
    GameInfo,
    GameUrl,
    Person,
    Tag,
    parse,
)
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
from games.permissions import can_manage_internal_tags
from play.services import PinnedURLError, format_pinned_url_error

from .models import GameCuration, GameHistoryAuditLog
from .overrides import build_initial_overrides, update_overrides_from_diff


def editor_payload_to_gameinfo(data: dict) -> GameInfo:
    info = GameInfo(
        name=data.get("title") or None,
        date=data.get("release_date") or None,
        description=data.get("desc") or None,
    )
    info.personalities = _personalities_from_payload(data.get("authors") or [])
    info.tags = [
        tag
        for row in data.get("tags") or []
        if (tag := _tag_from_payload(row)) is not None
    ]
    info.urls = [_url_from_payload(row) for row in data.get("links") or []]
    info.attributions = [
        _attribution_from_payload(item)
        for item in data.get("description_attributions") or []
        if str(item).strip()
    ]
    info.canonicalize()
    return info


def _validate_pinned_urls(game: Game, info: GameInfo) -> None:
    for gu in (
        game.gameurl_set
        .filter(playables__isnull=False)
        .distinct()
        .select_related("url", "category")
    ):
        retained = any(
            u.category == gu.category.symbolic_id
            and (
                u.url_id == gu.url_id
                or (u.url and u.url.strip() == gu.url.original_url.strip())
            )
            for u in info.urls
        )
        if not retained:
            raise PinnedURLError(format_pinned_url_error(gu))


@transaction.atomic
def store_manual_edit(
    game: Game, data: dict, user, *, apply: bool
) -> GameRevision:
    curation = _curation_for_game(game)
    previous_edit = _latest_applied_edit(game)
    before = previous_edit.canonical_text if previous_edit else ""
    info = editor_payload_to_gameinfo(data)
    _validate_pinned_urls(game, info)
    if not can_manage_internal_tags(user):
        internal_tags = [
            Tag(
                category=t.category.symbolic_id or "",
                slug=t.symbolic_id,
                tag_id=t.id,
                text=t.name,
            )
            for t in game.tags.filter(
                category__is_internal=True
            ).select_related("category")
        ]
        if internal_tags:
            info.tags.extend(internal_tags)
            info.canonicalize()
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
        before_info = parse(before) if before else GameInfo()
        update_overrides_from_diff(curation, before_info, info)
        curation_fields = [
            "state",
            "note",
            "include_overrides",
            "exclude_overrides",
        ]
    else:
        curation.state = GameCuration.State.NEEDS_ATTENTION
        curation.note = "Пользователь предложил правку"
        curation_fields = ["state", "note"]
    GameHistoryAuditLog.record_note_change(game, user, old_note, curation.note)
    curation.save(update_fields=curation_fields)
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
        include_overrides=build_initial_overrides(info, is_rich_source=False),
        exclude_overrides={},
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


def _tag_from_payload(row: list) -> Tag | None:
    if len(row) < 2:
        return None
    cat_value, tag_value = row[0], row[1]
    if tag_value is None or (
        isinstance(tag_value, str) and not tag_value.strip()
    ):
        return None
    if isinstance(cat_value, int):
        cat = GameTagCategory.objects.filter(pk=cat_value).first()
        if cat is None:
            raise ValueError(f"Категория свойства {cat_value} не найдена.")
        category = cat.symbolic_id
    else:
        category = str(cat_value).strip()
    if not category:
        return None
    if isinstance(tag_value, int):
        tag = (
            GameTag.objects
            .select_related("category")
            .filter(pk=tag_value)
            .first()
        )
        if tag is None:
            raise ValueError(f"Свойство с id {tag_value} не найдено.")
        return Tag(tag.category.symbolic_id, tag.symbolic_id, tag.id, None)
    return Tag(category, None, None, str(tag_value).strip())


def _url_from_payload(row: list | dict) -> GameUrl:
    if isinstance(row, dict):
        cat_value = row.get("category")
        description = row.get("description")
        url = row.get("url")
    else:
        cat_value, description, url = row
    if isinstance(cat_value, str) and cat_value.isdigit():
        cat_value = int(cat_value)
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
