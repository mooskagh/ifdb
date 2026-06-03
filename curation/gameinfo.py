"""Rich game info: the canonical document form for a game.

A canonical document is YAML front matter (name, release date, personalities,
tags, urls, attributions) followed by a markdown description body.  This module
owns that form end to end: a loose ``parse``, a strict ``to_canonical``
serializer, a union ``merge`` and a self-contained ``save`` that writes a
``Game`` and syncs its tags/authors/urls/attributions.

It is the typed, request-free replacement for ``games/updater.py`` and so
carries no request/permission/user coupling -- it acts as a maintenance writer.
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field

import yaml
from dateutil.parser import parse as parse_date
from django.utils import timezone

from core.taskqueue import Enqueue
from games.importer.tools import HashizeUrl
from games.models import (
    URL,
    Game,
    GameAuthor,
    GameAuthorRole,
    GameDescriptionAttribution,
    GameTag,
    GameTagCategory,
    GameURL,
    GameURLCategory,
    Personality,
    PersonalityAlias,
    PersonalityAliasRedirect,
)
from games.tasks.uploads import RecodeGame
from games.tools import CreateUrl


@dataclass
class Person:
    alias_id: int | None
    name: str


@dataclass
class Tag:
    category: str
    slug: str | None
    tag_id: int | None
    text: str | None


@dataclass
class GameUrl:
    category: str
    url_id: int | None
    description: str | None
    url: str | None


@dataclass
class Attribution:
    attr_id: int | None
    name: str


@dataclass
class GameInfo:
    name: str | None = None
    date: str | None = None
    description: str | None = None
    # role symbolic_id -> people
    personalities: dict[str, list[Person]] = field(default_factory=dict)
    tags: list[Tag] = field(default_factory=list)
    urls: list[GameUrl] = field(default_factory=list)
    attributions: list[Attribution] = field(default_factory=list)

    # -- Serialization ----------------------------------------------------

    def to_canonical(self) -> str:
        """Resolve ids to names and emit the exact canonical document."""
        refs = _References(self)
        lines: list[str] = []
        if self.name:
            lines.append(f"- name: {_dump(self.name)}")
        if self.date:
            lines.append(f"- release_date: {_dump(self.date)}")
        lines += refs.personality_lines(self.personalities)
        lines += refs.tag_lines(self.tags)
        lines += refs.url_lines(self.urls)
        lines += refs.attribution_lines(self.attributions)
        body = self.description or ""
        return "---\n" + "\n".join(lines) + "\n---\n" + body

    def canonicalize(self) -> None:
        """Resolve existing references without creating game data."""
        for people in self.personalities.values():
            for person in people:
                self._resolve_existing_alias_id(person)
        for tag in self.tags:
            self._resolve_existing_tag_id(tag)
        for url in self.urls:
            self._resolve_existing_url_id(url)
        for attr in self.attributions:
            self._resolve_existing_attribution_id(attr)

    # -- Construction -----------------------------------------------------

    @classmethod
    def from_importer_dict(cls, d: dict) -> "GameInfo":
        """Bridge a legacy importer dict (``games/importer/tools.py``) to here.

        Pure text-level mapping: ids stay ``None`` and names stay as text --
        resolution to DB rows happens later in ``parse``/``save``.  The one DB
        touch is the rare ``role``-title fallback when an author dict carries a
        human role name instead of a ``role_slug`` (no importer emits that
        today, but the old ``Importer2Json`` honored it).
        """
        info = cls(
            name=d.get("title"),
            date=str(d["release_date"]) if d.get("release_date") else None,
            description=d.get("desc"),
        )
        for a in d.get("authors", []):
            role_slug = a.get("role_slug")
            if not role_slug and a.get("role"):
                role = GameAuthorRole.objects.filter(title=a["role"]).first()
                role_slug = role.symbolic_id if role else a["role"]
            if role_slug:
                info.personalities.setdefault(role_slug, []).append(
                    Person(None, a["name"])
                )
        for t in d.get("tags", []):
            if t.get("tag_slug"):
                info.tags.append(Tag("", t["tag_slug"], None, None))
            else:
                info.tags.append(Tag(t["cat_slug"], None, None, t["tag"]))
        for u in d.get("urls", []):
            if not u.get("urlcat_slug"):  # mirrors MergeImport's url filter
                continue
            info.urls.append(
                GameUrl(u["urlcat_slug"], None, u.get("description"), u["url"])
            )
        info.attributions = [
            Attribution(None, name)
            for name in d.get("description_attributions", [])
        ]
        return info

    @classmethod
    def from_game(cls, game: Game) -> "GameInfo":
        """Build from a DB row, mirroring the game-details prefetch pattern."""
        game = Game.objects.prefetch_related(
            "gameauthor_set__role",
            "gameauthor_set__author",
            "gameurl_set__category",
            "gameurl_set__url",
            "description_attributions",
            "tags__category",
        ).get(id=game.id)
        info = cls(
            name=game.title,
            date=game.release_date.isoformat() if game.release_date else None,
            description=game.description or None,
        )
        for ga in game.gameauthor_set.all():
            info.personalities.setdefault(ga.role.symbolic_id, []).append(
                Person(alias_id=ga.author_id, name="")
            )
        for t in game.tags.all():
            info.tags.append(
                Tag(t.category.symbolic_id, t.symbolic_id, t.id, None)
            )
        for gu in game.gameurl_set.all():
            info.urls.append(
                GameUrl(
                    gu.category.symbolic_id,
                    gu.url_id,
                    gu.description,
                    gu.url.original_url,
                )
            )
        for a in game.description_attributions.all():
            info.attributions.append(Attribution(a.id, a.name))
        return info

    # -- Persistence ------------------------------------------------------

    def save(self, game: Game | None = None) -> tuple[Game, str]:
        """Create or update a game; return ``(game, fresh canonical text)``.

        After rows are written the newly created ids are back-filled into this
        ``GameInfo`` so the returned canonical document resolves every entry to
        an id.  Re-saving that document is a no-op.
        """
        now = timezone.now()
        if game is None:
            game = Game(creation_time=now)
        game.edit_time = now
        game.title = self.name or ""
        game.description = self.description
        game.release_date = parse_date(self.date).date() if self.date else None
        game.save()

        self._save_tags(game)
        self._save_authors(game)
        self._save_urls(game)
        self._save_attributions(game)
        return game, self.to_canonical()

    def _save_tags(self, game: Game) -> None:
        existing = {t.id for t in game.tags.all()}
        desired = set()
        for tag in self.tags:
            tag_id = self._resolve_tag_id(tag)
            if tag_id is not None:
                desired.add(tag_id)
        if to_add := desired - existing:
            game.tags.add(*to_add)
        if to_remove := existing - desired:
            game.tags.remove(*to_remove)

    def _resolve_tag_id(self, tag: Tag) -> int | None:
        if tag.tag_id is not None:
            return tag.tag_id
        if tag.slug:
            found = GameTag.objects.filter(symbolic_id=tag.slug).first()
            tag.tag_id = found.id if found else None
            return tag.tag_id
        cat = GameTagCategory.objects.get(symbolic_id=tag.category)
        if cat.allow_new_tags:
            found, _ = GameTag.objects.get_or_create(
                name=tag.text, category=cat
            )
        else:
            found = GameTag.objects.get(name=tag.text, category=cat)
        tag.tag_id, tag.text = found.id, None
        return tag.tag_id

    def _save_authors(self, game: Game) -> None:
        existing = {
            (ga.role_id, ga.author_id): ga.id
            for ga in game.gameauthor_set.all()
        }
        desired = set()
        to_create = []
        for role_slug, people in self.personalities.items():
            role, _ = GameAuthorRole.objects.get_or_create(
                symbolic_id=role_slug, defaults={"title": role_slug}
            )
            for person in people:
                alias = self._resolve_alias(person)
                if alias is None:
                    continue
                if alias.personality_id is None:
                    alias.personality = Personality.objects.create(
                        name=alias.name
                    )
                    alias.save(update_fields=["personality"])
                key = (role.id, alias.id)
                desired.add(key)
                if key not in existing:
                    to_create.append(
                        GameAuthor(
                            game=game, role_id=role.id, author_id=alias.id
                        )
                    )
        GameAuthor.objects.bulk_create(to_create)
        if stale := [v for k, v in existing.items() if k not in desired]:
            GameAuthor.objects.filter(id__in=stale).delete()

    def _resolve_alias(self, person: Person) -> PersonalityAlias | None:
        if person.alias_id is not None:
            return PersonalityAlias.objects.get(pk=person.alias_id)
        name = person.name.strip()
        if not name:
            return None
        alias_id = _existing_alias_id(name)
        if alias_id is None:
            alias_id = PersonalityAlias.objects.create(name=name).id
        person.alias_id, person.name = alias_id, ""
        return PersonalityAlias.objects.get(pk=alias_id)

    def _resolve_existing_alias_id(self, person: Person) -> int | None:
        if person.alias_id is not None:
            return person.alias_id
        alias_id = _existing_alias_id(person.name.strip())
        if alias_id is not None:
            person.alias_id, person.name = alias_id, ""
        return alias_id

    def _resolve_existing_tag_id(self, tag: Tag) -> int | None:
        if tag.tag_id is not None:
            return tag.tag_id
        if tag.slug:
            found = GameTag.objects.filter(symbolic_id=tag.slug).first()
        else:
            found = GameTag.objects.filter(
                category__symbolic_id=tag.category, name=tag.text
            ).first()
        if found is None:
            return None
        tag.category = found.category.symbolic_id
        tag.slug = found.symbolic_id
        tag.tag_id = found.id
        tag.text = None
        return tag.tag_id

    def _resolve_existing_url_id(self, entry: GameUrl) -> int | None:
        if entry.url_id is not None:
            return entry.url_id
        url = URL.objects.filter(original_url=entry.url).first()
        if url is not None:
            entry.url_id = url.id
        return entry.url_id

    def _resolve_existing_attribution_id(
        self, attr: Attribution
    ) -> int | None:
        if attr.attr_id is not None:
            return attr.attr_id
        obj = GameDescriptionAttribution.objects.filter(name=attr.name).first()
        if obj is not None:
            attr.attr_id, attr.name = obj.id, ""
        return attr.attr_id

    def _save_urls(self, game: Game) -> None:
        existing = {
            (gu.category_id, gu.url.original_url): gu.id
            for gu in game.gameurl_set.select_related("url").all()
        }
        desired = set()
        for entry in self.urls:
            cat = GameURLCategory.objects.get(symbolic_id=entry.category)
            if entry.url_id is not None:
                url = URL.objects.get(id=entry.url_id)
            else:
                url = CreateUrl(entry.url, ok_to_clone=cat.allow_cloning)
                entry.url_id = url.id
            key = (cat.id, url.original_url)
            if key in desired:
                continue
            desired.add(key)
            if key not in existing:
                gu = GameURL(
                    game=game,
                    url_id=url.id,
                    category_id=cat.id,
                    description=entry.description or None,
                )
                gu.save()
                if GameURLCategory.IsRecodable(cat.id):
                    Enqueue(RecodeGame, gu.id, name="RecodeGame(%d)" % gu.id)
        if stale := [v for k, v in existing.items() if k not in desired]:
            GameURL.objects.filter(id__in=stale).delete()

    def _save_attributions(self, game: Game) -> None:
        ids = []
        for attr in self.attributions:
            if attr.attr_id is None:
                obj, _ = GameDescriptionAttribution.objects.get_or_create(
                    name=attr.name
                )
                attr.attr_id, attr.name = obj.id, ""
            ids.append(attr.attr_id)
        game.description_attributions.set(ids)


# -- Parsing --------------------------------------------------------------


def parse(text: str) -> GameInfo:
    """Loosely parse a canonical-or-not document into a normalized GameInfo.

    Accepts both the canonical list-of-single-key-maps and a plain mapping, in
    any order, with properties addressable by text.  Text references are
    resolved to DB ids where possible; unresolved ones stay as new entries.
    """
    front, body = _split_front_matter(text)
    sections = _as_mapping(yaml.safe_load(front) if front.strip() else None)

    info = GameInfo(
        name=sections.get("name"),
        date=sections.get("release_date"),
        description=body or None,
    )
    for role, people in _as_mapping(sections.get("personalities")).items():
        info.personalities[role] = [_parse_person(p) for p in people or []]
    info.tags = [_parse_tag(t) for t in sections.get("tags") or []]
    info.urls = [_parse_url(u) for u in sections.get("urls") or []]
    info.attributions = [
        _parse_attribution(a) for a in sections.get("attributions") or []
    ]
    return info


def _parse_person(value) -> Person:
    if isinstance(value, int):
        return Person(alias_id=value, name="")
    alias_id = _existing_alias_id(value)
    if alias_id is not None:
        return Person(alias_id, "")
    return Person(None, value)


def _parse_tag(value) -> Tag:
    if isinstance(value, str):  # slug form
        tag = (
            GameTag.objects
            .filter(symbolic_id=value)
            .select_related("category")
            .first()
        )
        if tag:
            return Tag(tag.category.symbolic_id, value, tag.id, None)
        return Tag("", value, None, None)
    cat, ref = value
    if isinstance(ref, int):  # DB tag, possibly with a slug
        tag = GameTag.objects.filter(id=ref).first()
        return Tag(cat, tag.symbolic_id if tag else None, ref, None)
    tag = GameTag.objects.filter(category__symbolic_id=cat, name=ref).first()
    if tag:
        return Tag(cat, tag.symbolic_id, tag.id, None)
    return Tag(cat, None, None, ref)


def _parse_url(value) -> GameUrl:
    cat, *rest = value
    if len(rest) == 1 and isinstance(rest[0], int):  # DB url; desc/url dropped
        game_url = GameURL.objects.filter(url_id=rest[0]).first()
        return GameUrl(
            cat,
            rest[0],
            game_url.description if game_url else None,
            None,
        )
    if len(rest) == 2:  # [cat, desc, url]
        desc, url = rest
        return GameUrl(cat, None, desc or None, url)
    return GameUrl(cat, None, None, rest[0])  # [cat, url]


def _parse_attribution(value) -> Attribution:
    if isinstance(value, int):
        return Attribution(value, "")
    attr = GameDescriptionAttribution.objects.filter(name=value).first()
    return Attribution(attr.id, "") if attr else Attribution(None, value)


def _existing_alias_id(name: str) -> int | None:
    if not name:
        return None
    redirect = PersonalityAliasRedirect.objects.filter(name=name).first()
    if redirect:
        return redirect.hidden_for_id
    alias = PersonalityAlias.objects.filter(name=name).first()
    return alias.id if alias else None


# -- Merge ----------------------------------------------------------------


def merge(base: GameInfo, incoming: GameInfo) -> GameInfo:
    """Union both docs: de-dup by identity, concat descriptions, first-wins."""
    url_by_id = {
        u.id: u.original_url
        for u in URL.objects.filter(
            id__in={
                u.url_id
                for u in [*base.urls, *incoming.urls]
                if u.url_id is not None
            }
        )
    }
    result = GameInfo(
        name=base.name or incoming.name,
        date=base.date or incoming.date,
    )
    descriptions = [d for d in (base.description, incoming.description) if d]
    result.description = "\n\n---\n\n".join(descriptions) or None

    roles = list(base.personalities) + [
        r for r in incoming.personalities if r not in base.personalities
    ]
    for role in roles:
        people = _dedup(
            base.personalities.get(role, [])
            + incoming.personalities.get(role, []),
            _person_key,
        )
        if people:
            result.personalities[role] = people
    result.tags = _dedup(base.tags + incoming.tags, _tag_key)
    result.urls = _dedup(
        base.urls + incoming.urls, lambda u: _url_key(u, url_by_id)
    )
    result.attributions = _dedup(
        base.attributions + incoming.attributions, _attribution_key
    )
    return result


def _person_key(p: Person):
    return ("id", p.alias_id) if p.alias_id is not None else ("name", p.name)


def _tag_key(t: Tag):
    if t.slug:
        return ("slug", t.slug)
    if t.tag_id is not None:
        return ("id", t.tag_id)
    return ("new", t.category, t.text)


def _url_key(u: GameUrl, url_by_id: dict[int, str | None]):
    url = u.url if u.url is not None else url_by_id.get(u.url_id)
    return (u.category, _hash_url_for_merge(url or ""))


def _hash_url_for_merge(url: str) -> str:
    return HashizeUrl(url).replace("rinform.stormway.ru/", "rinform.org/")


def _attribution_key(a: Attribution):
    return ("id", a.attr_id) if a.attr_id is not None else ("name", a.name)


def _dedup(items, key):
    seen = set()
    out = []
    for item in items:
        k = key(item)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


# -- Internals ------------------------------------------------------------


def _dump(value) -> str:
    """JSON dump: double-quoted strings, flow lists -- all valid YAML."""
    return json.dumps(value, ensure_ascii=False)


def _split_front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        if rest.endswith("\n---"):
            return rest[:-4], ""
        return "", text
    return rest[:end], rest[end + 5 :]


def _as_mapping(value) -> dict:
    """Normalize a section value (list-of-single-key-maps or map) to a dict."""
    if isinstance(value, dict):
        return value
    result: dict = {}
    for item in value or []:
        if isinstance(item, dict):
            result.update(item)
    return result


class _References:
    """Bulk id->name lookups plus category ordering for ``to_canonical``."""

    def __init__(self, info: GameInfo):
        alias_ids = {
            p.alias_id
            for people in info.personalities.values()
            for p in people
            if p.alias_id is not None
        }
        tag_ids = {t.tag_id for t in info.tags if t.tag_id is not None}
        url_ids = {u.url_id for u in info.urls if u.url_id is not None}
        attr_ids = {a.attr_id for a in info.attributions if a.attr_id}

        self.alias = {
            a.id: a.name
            for a in PersonalityAlias.objects.filter(id__in=alias_ids)
        }
        self.tag = {t.id: t for t in GameTag.objects.filter(id__in=tag_ids)}
        self.url = {
            u.id: u.original_url for u in URL.objects.filter(id__in=url_ids)
        }
        self.attr = {
            a.id: a.name
            for a in GameDescriptionAttribution.objects.filter(id__in=attr_ids)
        }
        self.role_order = dict(
            GameAuthorRole.objects.values_list("symbolic_id", "order")
        )
        self.tagcat_order = dict(
            GameTagCategory.objects.values_list("symbolic_id", "order")
        )
        self.urlcat_order = dict(
            GameURLCategory.objects.values_list("symbolic_id", "order")
        )

    def personality_lines(self, personalities: dict[str, list[Person]]):
        lines = []
        roles = sorted(
            (r for r, p in personalities.items() if p),
            key=lambda r: (self.role_order.get(r, 1000), r),
        )
        for role in roles:
            lines.append(f"  - {role}:")
            for p in self._sorted(
                personalities[role], lambda x: x.alias_id, lambda x: x.name
            ):
                if p.alias_id is not None:
                    name = _dump(self.alias[p.alias_id])
                    lines.append(f"    - {p.alias_id}  # {name}")
                else:
                    lines.append(f"    - {_dump(p.name)}")
        return ["- personalities:", *lines] if lines else []

    def tag_lines(self, tags: list[Tag]):
        by_cat: dict[str, list[Tag]] = defaultdict(list)
        for t in tags:
            by_cat[t.category].append(t)
        lines = []
        for cat in sorted(
            by_cat, key=lambda c: (self.tagcat_order.get(c, 0), c)
        ):
            for t in self._sorted(
                by_cat[cat], self._tag_sort_key, lambda x: x.text or ""
            ):
                if t.slug:
                    lines.append(f"  - {_dump(t.slug)}")
                elif t.tag_id is not None:
                    name = self.tag[t.tag_id].name
                    lines.append(
                        f"  - {_dump([cat, t.tag_id])}  # {_dump(name)}"
                    )
                else:
                    lines.append(f"  - {_dump([cat, t.text or ''])}")
        return ["- tags:", *lines] if lines else []

    def url_lines(self, urls: list[GameUrl]):
        by_cat: dict[str, list[GameUrl]] = defaultdict(list)
        for u in urls:
            by_cat[u.category].append(u)
        lines = []
        for cat in sorted(
            by_cat, key=lambda c: (self.urlcat_order.get(c, 0), c)
        ):
            for u in self._sorted(
                by_cat[cat], lambda x: x.url_id, lambda x: x.url or ""
            ):
                if u.url_id is not None:
                    original = self.url[u.url_id]
                    label = f"{_dump(u.description)} " if u.description else ""
                    item = _dump([cat, u.url_id])
                    lines.append(f"  - {item}  # {label}{_dump(original)}")
                else:
                    lines.append(
                        f"  - {_dump([cat, u.description or '', u.url])}"
                    )
        return ["- urls:", *lines] if lines else []

    def attribution_lines(self, attributions: list[Attribution]):
        lines = []
        for a in self._sorted(
            attributions, lambda x: x.attr_id, lambda x: x.name
        ):
            if a.attr_id is not None:
                lines.append(
                    f"  - {a.attr_id}  # {_dump(self.attr[a.attr_id])}"
                )
            else:
                lines.append(f"  - {_dump(a.name)}")
        return ["- attributions:", *lines] if lines else []

    @staticmethod
    def _sorted(items, db_key, new_key):
        """DB entries (id present) first by id, then new entries by name."""
        db = sorted((x for x in items if db_key(x) is not None), key=db_key)
        new = sorted((x for x in items if db_key(x) is None), key=new_key)
        return [*db, *new]

    def _tag_sort_key(self, tag: Tag):
        if tag.slug:
            return (0, tag.slug)
        if tag.tag_id is not None:
            return (1, self.tag[tag.tag_id].name)
        return None
