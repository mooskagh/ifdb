from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from curation.models import GameCuration
from games.gameinfo import (
    GameInfo,
    GameUrl,
    Person,
    Tag,
    _as_mapping,
    _dedup,
    _dedup_urls,
    _dump,
    _existing_alias_id,
    _parse_person,
    _parse_tag,
    _parse_url,
    _tag_key,
    _url_key,
)
from games.models import URL, Game, GameTag, PersonalityAlias


def serialize_tag(tag: Tag) -> str | list[Any]:
    if tag.slug:
        return tag.slug
    if tag.tag_id is not None:
        return [tag.category, tag.tag_id]
    return [tag.category, tag.text or ""]


def parse_tags(items: Iterable[Any]) -> list[Tag]:
    tags: list[Tag] = []
    for item in items:
        tags.extend(_parse_tag(item))
    return _dedup(tags, _tag_key)


def tag_key(tag: Tag) -> tuple[str, ...]:
    if tag.tag_id is not None:
        return ("id", str(tag.tag_id))
    if tag.slug:
        found = (
            GameTag.objects
            .filter(symbolic_id=tag.slug)
            .values_list("id", flat=True)
            .first()
        )
        if found:
            tag.tag_id = found
            return ("id", str(found))
        return ("slug", tag.slug)
    if tag.text:
        found = (
            GameTag.objects
            .filter(category__symbolic_id=tag.category, name=tag.text)
            .values_list("id", flat=True)
            .first()
        )
        if found:
            tag.tag_id = found
            return ("id", str(found))
        return ("text", tag.category, tag.text.strip().lower())
    return ("empty", tag.category)


def serialize_personalities(
    personalities: dict[str | None, list[Person]],
) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = {}
    for role, people in personalities.items():
        if not role or not people:
            continue
        serialized_people: list[Any] = []
        for p in people:
            if p.alias_id is not None:
                serialized_people.append(p.alias_id)
            elif p.name:
                serialized_people.append(p.name)
        if serialized_people:
            result[role] = serialized_people
    return result


def parse_personalities(data: Any) -> dict[str | None, list[Person]]:
    result: dict[str | None, list[Person]] = {}
    mapping = _as_mapping(data)
    for role, people in mapping.items():
        if not role:
            continue
        parsed_people = [_parse_person(p) for p in people or []]
        if parsed_people:
            result[role] = parsed_people
    return result


def person_key(p: Person) -> tuple[str, ...]:
    if p.alias_id is not None:
        return ("id", str(p.alias_id))
    if p.name:
        alias_id = _existing_alias_id(p.name)
        if alias_id is not None:
            p.alias_id = alias_id
            return ("id", str(alias_id))
        return ("name", p.name.strip().lower())
    return ("empty", "")


def serialize_urls(urls: list[GameUrl]) -> list[Any]:
    result: list[Any] = []
    for u in urls:
        desc = u.description or ""
        if u.url_id is not None:
            result.append([u.category, desc, u.url_id])
        elif u.url:
            result.append([u.category, desc, u.url])
    return result


def parse_urls(items: Iterable[Any]) -> list[GameUrl]:
    return [_parse_url(item) for item in items]


def url_key(
    u: GameUrl, url_by_id: dict[int, str | None] | None = None
) -> tuple[str, str]:
    if url_by_id is None:
        url_ids = {u.url_id} if u.url_id is not None else set()
        url_by_id = {
            url.id: url.original_url
            for url in URL.objects.filter(id__in=url_ids)
        }
    return _url_key(u, url_by_id)


def _cleanup_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, val in overrides.items():
        if isinstance(val, dict):
            sub_cleaned = {k: v for k, v in val.items() if v}
            if sub_cleaned:
                cleaned[key] = sub_cleaned
        elif isinstance(val, list):
            if val:
                cleaned[key] = val
        elif val:
            cleaned[key] = val
    return cleaned


def build_initial_overrides(
    info: GameInfo, *, is_rich_source: bool = False
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if not is_rich_source:
        personalities = serialize_personalities(info.personalities)
        if personalities:
            overrides["personalities"] = personalities
        tags = [serialize_tag(t) for t in info.tags]
        if tags:
            overrides["tags"] = tags
    else:
        tags = [
            serialize_tag(t) for t in info.tags if t.category != "language"
        ]
        if tags:
            overrides["tags"] = tags

    urls = serialize_urls(info.urls)
    if urls:
        overrides["urls"] = urls

    return overrides


def apply_and_prune_overrides(
    curation: GameCuration,
    sources_info: GameInfo,
) -> tuple[GameInfo, bool]:
    overrides_changed = False
    include_overrides = dict(curation.include_overrides or {})
    exclude_overrides = dict(curation.exclude_overrides or {})

    # --- 1. Tags ---
    source_tag_map = {tag_key(t): t for t in sources_info.tags}
    raw_includes = include_overrides.get("tags") or []
    raw_excludes = exclude_overrides.get("tags") or []

    parsed_includes = parse_tags(raw_includes)
    kept_include_tags: list[Tag] = []
    for t in parsed_includes:
        k = tag_key(t)
        if k in source_tag_map:
            overrides_changed = True
        else:
            kept_include_tags.append(t)

    parsed_excludes = parse_tags(raw_excludes)
    kept_exclude_tags: list[Tag] = []
    for e in parsed_excludes:
        k = tag_key(e)
        if k not in source_tag_map:
            overrides_changed = True
        else:
            kept_exclude_tags.append(e)

    exclude_keys = {tag_key(e) for e in kept_exclude_tags}
    final_tags = [
        t for t in sources_info.tags if tag_key(t) not in exclude_keys
    ]
    final_tags = _dedup(final_tags + kept_include_tags, _tag_key)
    sources_info.tags = final_tags

    if overrides_changed or len(kept_include_tags) != len(raw_includes):
        include_overrides["tags"] = [
            serialize_tag(t) for t in kept_include_tags
        ]
    if overrides_changed or len(kept_exclude_tags) != len(raw_excludes):
        exclude_overrides["tags"] = [
            serialize_tag(t) for t in kept_exclude_tags
        ]

    # --- 2. Personalities ---
    raw_include_pers = include_overrides.get("personalities") or {}
    raw_exclude_pers = exclude_overrides.get("personalities") or {}
    parsed_include_pers = parse_personalities(raw_include_pers)
    parsed_exclude_pers = parse_personalities(raw_exclude_pers)

    source_person_keys = {
        (role, person_key(p))
        for role, ppl in sources_info.personalities.items()
        for p in ppl
        if role
    }

    kept_include_pers: dict[str | None, list[Person]] = defaultdict(list)
    for role, people in parsed_include_pers.items():
        if not role:
            continue
        for p in people:
            if (role, person_key(p)) in source_person_keys:
                overrides_changed = True
            else:
                kept_include_pers[role].append(p)

    kept_exclude_pers: dict[str | None, list[Person]] = defaultdict(list)
    for role, people in parsed_exclude_pers.items():
        if not role:
            continue
        for p in people:
            if (role, person_key(p)) not in source_person_keys:
                overrides_changed = True
            else:
                kept_exclude_pers[role].append(p)

    exclude_person_keys = {
        (role, person_key(p))
        for role, ppl in kept_exclude_pers.items()
        for p in ppl
    }

    updated_personalities: dict[str | None, list[Person]] = {}
    all_roles = set(sources_info.personalities) | set(kept_include_pers)
    for role in all_roles:
        if not role:
            continue
        source_ppl = sources_info.personalities.get(role, [])
        filtered = [
            p
            for p in source_ppl
            if (role, person_key(p)) not in exclude_person_keys
        ]
        combined = _dedup(
            filtered + kept_include_pers.get(role, []), lambda p: person_key(p)
        )
        if combined:
            updated_personalities[role] = combined
    sources_info.personalities = updated_personalities

    include_overrides["personalities"] = serialize_personalities(
        kept_include_pers
    )
    exclude_overrides["personalities"] = serialize_personalities(
        kept_exclude_pers
    )

    # --- 3. URLs ---
    raw_include_urls = include_overrides.get("urls") or []
    raw_exclude_urls = exclude_overrides.get("urls") or []
    parsed_include_urls = parse_urls(raw_include_urls)
    parsed_exclude_urls = parse_urls(raw_exclude_urls)

    all_url_ids = {
        u.url_id
        for u in [
            *sources_info.urls,
            *parsed_include_urls,
            *parsed_exclude_urls,
        ]
        if u.url_id is not None
    }
    url_by_id = {
        url.id: url.original_url
        for url in URL.objects.filter(id__in=all_url_ids)
    }

    source_url_keys = {url_key(u, url_by_id) for u in sources_info.urls}

    kept_include_urls: list[GameUrl] = []
    for u in parsed_include_urls:
        k = url_key(u, url_by_id)
        if k in source_url_keys:
            overrides_changed = True
        else:
            kept_include_urls.append(u)

    kept_exclude_urls: list[GameUrl] = []
    for exc_u in parsed_exclude_urls:
        uk = url_key(exc_u, url_by_id)
        if uk not in source_url_keys:
            overrides_changed = True
        else:
            kept_exclude_urls.append(exc_u)

    exclude_url_keys = {url_key(e, url_by_id) for e in kept_exclude_urls}
    final_urls = [
        u
        for u in sources_info.urls
        if url_key(u, url_by_id) not in exclude_url_keys
    ]
    final_urls = _dedup_urls(
        final_urls + kept_include_urls, lambda u: url_key(u, url_by_id)
    )
    sources_info.urls = final_urls

    include_overrides["urls"] = serialize_urls(kept_include_urls)
    exclude_overrides["urls"] = serialize_urls(kept_exclude_urls)

    cleaned_includes = _cleanup_overrides(include_overrides)
    cleaned_excludes = _cleanup_overrides(exclude_overrides)

    if cleaned_includes != (curation.include_overrides or {}):
        curation.include_overrides = cleaned_includes
        overrides_changed = True
    if cleaned_excludes != (curation.exclude_overrides or {}):
        curation.exclude_overrides = cleaned_excludes
        overrides_changed = True

    return sources_info, overrides_changed


def update_overrides_from_diff(
    curation: GameCuration, before: GameInfo, after: GameInfo
) -> bool:
    include_overrides = dict(curation.include_overrides or {})
    exclude_overrides = dict(curation.exclude_overrides or {})

    # 1. Tags
    before_tag_map = {tag_key(t): t for t in before.tags}
    after_tag_map = {tag_key(t): t for t in after.tags}

    added_tags = [
        t for k, t in after_tag_map.items() if k not in before_tag_map
    ]
    removed_tags = [
        t for k, t in before_tag_map.items() if k not in after_tag_map
    ]

    existing_inc_tags = {
        tag_key(t): t for t in parse_tags(include_overrides.get("tags") or [])
    }
    existing_exc_tags = {
        tag_key(t): t for t in parse_tags(exclude_overrides.get("tags") or [])
    }

    for t in added_tags:
        k = tag_key(t)
        existing_inc_tags[k] = t
        existing_exc_tags.pop(k, None)

    for t in removed_tags:
        k = tag_key(t)
        existing_exc_tags[k] = t
        existing_inc_tags.pop(k, None)

    include_overrides["tags"] = [
        serialize_tag(t) for t in existing_inc_tags.values()
    ]
    exclude_overrides["tags"] = [
        serialize_tag(t) for t in existing_exc_tags.values()
    ]

    # 2. Personalities
    before_person_map = {
        (role, person_key(p)): p
        for role, ppl in before.personalities.items()
        for p in ppl
        if role
    }
    after_person_map = {
        (role, person_key(p)): p
        for role, ppl in after.personalities.items()
        for p in ppl
        if role
    }

    added_persons = [
        (role, p)
        for (role, k), p in after_person_map.items()
        if (role, k) not in before_person_map
    ]
    removed_persons = [
        (role, p)
        for (role, k), p in before_person_map.items()
        if (role, k) not in after_person_map
    ]

    existing_inc_pers = parse_personalities(
        include_overrides.get("personalities") or {}
    )
    existing_exc_pers = parse_personalities(
        exclude_overrides.get("personalities") or {}
    )

    inc_person_map = {
        (role, person_key(p)): p
        for role, ppl in existing_inc_pers.items()
        for p in ppl
        if role
    }
    exc_person_map = {
        (role, person_key(p)): p
        for role, ppl in existing_exc_pers.items()
        for p in ppl
        if role
    }

    for role, p in added_persons:
        pk = (role, person_key(p))
        inc_person_map[pk] = p
        exc_person_map.pop(pk, None)

    for role, p in removed_persons:
        pk = (role, person_key(p))
        exc_person_map[pk] = p
        inc_person_map.pop(pk, None)

    grouped_inc_pers: dict[str | None, list[Person]] = defaultdict(list)
    for (role, _), p in inc_person_map.items():
        grouped_inc_pers[role].append(p)
    grouped_exc_pers: dict[str | None, list[Person]] = defaultdict(list)
    for (role, _), p in exc_person_map.items():
        grouped_exc_pers[role].append(p)

    include_overrides["personalities"] = serialize_personalities(
        grouped_inc_pers
    )
    exclude_overrides["personalities"] = serialize_personalities(
        grouped_exc_pers
    )

    # 3. URLs
    all_url_ids = {
        u.url_id for u in [*before.urls, *after.urls] if u.url_id is not None
    }
    url_by_id = {
        url.id: url.original_url
        for url in URL.objects.filter(id__in=all_url_ids)
    }

    before_url_map = {url_key(u, url_by_id): u for u in before.urls}
    after_url_map = {url_key(u, url_by_id): u for u in after.urls}

    added_urls = [
        u for k, u in after_url_map.items() if k not in before_url_map
    ]
    removed_urls = [
        u for k, u in before_url_map.items() if k not in after_url_map
    ]

    parsed_inc_urls = parse_urls(include_overrides.get("urls") or [])
    parsed_exc_urls = parse_urls(exclude_overrides.get("urls") or [])

    inc_url_map = {url_key(u, url_by_id): u for u in parsed_inc_urls}
    exc_url_map = {url_key(u, url_by_id): u for u in parsed_exc_urls}

    for u in added_urls:
        k = url_key(u, url_by_id)
        inc_url_map[k] = u
        exc_url_map.pop(k, None)

    for u in removed_urls:
        k = url_key(u, url_by_id)
        exc_url_map[k] = u
        inc_url_map.pop(k, None)

    include_overrides["urls"] = serialize_urls(list(inc_url_map.values()))
    exclude_overrides["urls"] = serialize_urls(list(exc_url_map.values()))

    cleaned_includes = _cleanup_overrides(include_overrides)
    cleaned_excludes = _cleanup_overrides(exclude_overrides)

    changed = cleaned_includes != (
        curation.include_overrides or {}
    ) or cleaned_excludes != (curation.exclude_overrides or {})
    curation.include_overrides = cleaned_includes
    curation.exclude_overrides = cleaned_excludes
    return changed


@dataclass
class OverrideTagDisplay:
    category: str
    name: str
    slug: str | None = None


@dataclass
class OverridePersonDisplay:
    role: str
    name: str


@dataclass
class OverrideUrlDisplay:
    category: str
    description: str
    url: str


@dataclass
class OverridesDisplay:
    has_content: bool
    tags: list[OverrideTagDisplay]
    personalities: list[OverridePersonDisplay]
    urls: list[OverrideUrlDisplay]


def format_overrides_for_display(overrides_data: Any) -> OverridesDisplay:
    if not isinstance(overrides_data, dict):
        return OverridesDisplay(
            has_content=False, tags=[], personalities=[], urls=[]
        )

    raw_tags = overrides_data.get("tags") or []
    parsed_tags = parse_tags(raw_tags)
    tag_displays: list[OverrideTagDisplay] = []
    tag_ids = {t.tag_id for t in parsed_tags if t.tag_id is not None}
    db_tags = {t.id: t.name for t in GameTag.objects.filter(id__in=tag_ids)}
    for t in parsed_tags:
        name = ""
        if t.tag_id in db_tags:
            name = db_tags[t.tag_id]
        elif t.slug:
            found = GameTag.objects.filter(symbolic_id=t.slug).first()
            name = found.name if found else t.slug
        else:
            name = t.text or ""
        tag_displays.append(
            OverrideTagDisplay(category=t.category, name=name, slug=t.slug)
        )

    raw_pers = overrides_data.get("personalities") or {}
    parsed_pers = parse_personalities(raw_pers)
    person_displays: list[OverridePersonDisplay] = []
    alias_ids = {
        p.alias_id
        for ppl in parsed_pers.values()
        for p in ppl
        if p.alias_id is not None
    }
    aliases = {
        a.id: a.name for a in PersonalityAlias.objects.filter(id__in=alias_ids)
    }
    for role, ppl in parsed_pers.items():
        if not role:
            continue
        for p in ppl:
            name = (
                aliases.get(p.alias_id, "")
                if p.alias_id is not None
                else p.name
            )
            person_displays.append(OverridePersonDisplay(role=role, name=name))

    raw_urls = overrides_data.get("urls") or []
    parsed_urls = parse_urls(raw_urls)
    url_displays: list[OverrideUrlDisplay] = []
    url_ids = {u.url_id for u in parsed_urls if u.url_id is not None}
    urls_map = {
        url.id: url.original_url for url in URL.objects.filter(id__in=url_ids)
    }
    for u in parsed_urls:
        url_val = (
            urls_map.get(u.url_id, "")
            if u.url_id is not None
            else (u.url or "")
        )
        url_displays.append(
            OverrideUrlDisplay(
                category=u.category,
                description=u.description or "",
                url=url_val,
            )
        )

    has_content = bool(tag_displays or person_displays or url_displays)
    return OverridesDisplay(
        has_content=has_content,
        tags=tag_displays,
        personalities=person_displays,
        urls=url_displays,
    )


def format_overrides_yaml(overrides_data: Any) -> str:
    if not isinstance(overrides_data, dict):
        return ""

    raw_tags = overrides_data.get("tags") or []
    raw_pers = overrides_data.get("personalities") or {}
    raw_urls = overrides_data.get("urls") or []

    parsed_tags = parse_tags(raw_tags)
    parsed_pers = parse_personalities(raw_pers)
    parsed_urls = parse_urls(raw_urls)

    if not parsed_tags and not parsed_pers and not parsed_urls:
        return ""

    lines: list[str] = []

    if parsed_pers:
        alias_ids = {
            p.alias_id
            for ppl in parsed_pers.values()
            for p in ppl
            if p.alias_id is not None
        }
        aliases = (
            {
                a.id: a.name
                for a in PersonalityAlias.objects.filter(id__in=alias_ids)
            }
            if alias_ids
            else {}
        )
        lines.append("personalities:")
        for role, people in parsed_pers.items():
            if not role:
                continue
            lines.append(f"  {role}:")
            for p in people:
                if p.alias_id is not None:
                    name = aliases.get(p.alias_id)
                    if name:
                        lines.append(f"    - {p.alias_id}  # {_dump(name)}")
                    else:
                        lines.append(f"    - {p.alias_id}")
                else:
                    lines.append(f"    - {_dump(p.name)}")

    if parsed_tags:
        tag_ids = {t.tag_id for t in parsed_tags if t.tag_id is not None}
        db_tags = (
            {t.id: t.name for t in GameTag.objects.filter(id__in=tag_ids)}
            if tag_ids
            else {}
        )
        slug_tags = {
            t.slug for t in parsed_tags if t.slug and t.tag_id is None
        }
        db_slugs = (
            {
                t.symbolic_id: t.name
                for t in GameTag.objects.filter(symbolic_id__in=slug_tags)
            }
            if slug_tags
            else {}
        )
        lines.append("tags:")
        for t in parsed_tags:
            if t.slug:
                name = db_slugs.get(t.slug)
                if name:
                    lines.append(f"  - {_dump(t.slug)}  # {_dump(name)}")
                else:
                    lines.append(f"  - {_dump(t.slug)}")
            elif t.tag_id is not None:
                name = db_tags.get(t.tag_id)
                if name:
                    lines.append(
                        f"  - {_dump([t.category, t.tag_id])}  # {_dump(name)}"
                    )
                else:
                    lines.append(f"  - {_dump([t.category, t.tag_id])}")
            else:
                lines.append(f"  - {_dump([t.category, t.text or ''])}")

    if parsed_urls:
        url_ids = {u.url_id for u in parsed_urls if u.url_id is not None}
        urls_map = (
            {
                url.id: url.original_url
                for url in URL.objects.filter(id__in=url_ids)
            }
            if url_ids
            else {}
        )
        lines.append("urls:")
        for u in parsed_urls:
            desc = u.description or ""
            if u.url_id is not None:
                original = urls_map.get(u.url_id, "")
                label = f"{_dump(desc)} " if desc else ""
                item = _dump([u.category, desc, u.url_id])
                if original:
                    lines.append(f"  - {item}  # {label}{_dump(original)}")
                else:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"  - {_dump([u.category, desc, u.url or ''])}")

    return "\n".join(lines)


def is_rich_source_game(game: Game | None) -> bool:
    if not game or not getattr(game, "pk", None):
        return False
    from curation.models import GameSource

    return bool(
        GameSource.objects.filter(
            game=game,
            type__in=[
                GameSource.SourceType.IFWIKI,
                GameSource.SourceType.QUESTBOOK,
            ],
        ).exists()
    )


def merge_overrides_dicts(
    base: dict[str, Any] | None, incoming: dict[str, Any] | None
) -> dict[str, Any]:
    base = base or {}
    incoming = incoming or {}
    result: dict[str, Any] = {}

    # Tags
    base_tags = parse_tags(base.get("tags") or [])
    inc_tags = parse_tags(incoming.get("tags") or [])
    merged_tags = _dedup(base_tags + inc_tags, tag_key)
    if merged_tags:
        result["tags"] = [serialize_tag(t) for t in merged_tags]

    # Personalities
    base_pers = parse_personalities(base.get("personalities") or {})
    inc_pers = parse_personalities(incoming.get("personalities") or {})
    all_roles = set(base_pers.keys()) | set(inc_pers.keys())
    merged_pers: dict[str | None, list[Person]] = {}
    for role in all_roles:
        if not role:
            continue
        merged_pers[role] = _dedup(
            base_pers.get(role, []) + inc_pers.get(role, []),
            person_key,
        )
    serialized_pers = serialize_personalities(merged_pers)
    if serialized_pers:
        result["personalities"] = serialized_pers

    # URLs
    base_urls = parse_urls(base.get("urls") or [])
    inc_urls = parse_urls(incoming.get("urls") or [])
    all_urls = base_urls + inc_urls
    url_ids = {u.url_id for u in all_urls if u.url_id is not None}
    url_by_id = {
        url.id: url.original_url for url in URL.objects.filter(id__in=url_ids)
    }
    merged_urls = _dedup_urls(all_urls, lambda u: _url_key(u, url_by_id))
    if merged_urls:
        result["urls"] = serialize_urls(merged_urls)

    return _cleanup_overrides(result)


def remove_from_overrides_dict(
    overrides: dict[str, Any] | None, to_remove: dict[str, Any] | None
) -> dict[str, Any]:
    if not overrides or not to_remove:
        return _cleanup_overrides(dict(overrides or {}))
    result = dict(overrides)

    # Tags
    if "tags" in result and "tags" in to_remove:
        remove_keys = {tag_key(t) for t in parse_tags(to_remove["tags"])}
        kept_tags = [
            t
            for t in parse_tags(result["tags"])
            if tag_key(t) not in remove_keys
        ]
        result["tags"] = [serialize_tag(t) for t in kept_tags]

    # Personalities
    if "personalities" in result and "personalities" in to_remove:
        rem_pers = parse_personalities(to_remove["personalities"])
        curr_pers = parse_personalities(result["personalities"])
        cleaned_pers: dict[str | None, list[Person]] = {}
        for role, people in curr_pers.items():
            if not role:
                continue
            rem_keys = {person_key(p) for p in rem_pers.get(role, [])}
            kept_people = [p for p in people if person_key(p) not in rem_keys]
            if kept_people:
                cleaned_pers[role] = kept_people
        result["personalities"] = serialize_personalities(cleaned_pers)

    # URLs
    if "urls" in result and "urls" in to_remove:
        rem_urls = parse_urls(to_remove["urls"])
        curr_urls = parse_urls(result["urls"])
        all_url_ids = {
            u.url_id for u in rem_urls + curr_urls if u.url_id is not None
        }
        url_by_id = {
            url.id: url.original_url
            for url in URL.objects.filter(id__in=all_url_ids)
        }
        rem_keys = {_url_key(u, url_by_id) for u in rem_urls}
        kept_urls = [
            u for u in curr_urls if _url_key(u, url_by_id) not in rem_keys
        ]
        result["urls"] = serialize_urls(kept_urls)

    return _cleanup_overrides(result)
