"""DB-configurable enrichment pass: the rule-based reborn of the old
``games/importer/enrichment.py``.

Each :class:`~curation.models.EnrichmentRule` carries a plain-Python
``condition`` expression and ``action`` statement(s), evaluated against a small
namespace of helpers bound to the draft ``GameInfo``.  Python's own ``and`` /
``or`` / ``not`` replace the old ``And`` / ``Or`` / ``Not`` rule classes -- no
DSL, no parser.  Rules are admin-only, so ``__builtins__`` is stripped and only
the helpers are exposed.

Two fixed transforms run after the rules as built-in steps, mirroring the old
``AddFunction(LowerCaseTags)`` / ``AddFunction(TagsToGenre)`` order; the
tag->genre step is driven by :class:`~curation.models.GenreMapping`.
"""

import re
from functools import lru_cache
from urllib.parse import urlsplit

from curation.edit import GameEditPass, GameEditState, register_pass
from curation.gameinfo import GameInfo, GameUrl, Tag
from curation.models import EnrichmentRule, GenreMapping
from games.models import GameTag


@register_pass
class EnrichmentPass(GameEditPass):
    name = "enrich"

    def apply(self, state: GameEditState) -> None:
        info = state.current
        ns = _namespace(info)
        for rule in EnrichmentRule.objects.filter(enabled=True):
            if not rule.condition or eval(
                _compile(rule.condition, "eval"), {"__builtins__": {}}, ns
            ):
                exec(_compile(rule.action, "exec"), {"__builtins__": {}}, ns)
        _lowercase_tags(info)
        _tags_to_genre(info)


@lru_cache(maxsize=None)
def _compile(source: str, mode: str):
    return compile(source, "<enrichment-rule>", mode)


# -- Helper namespace -----------------------------------------------------


def _namespace(info: GameInfo) -> dict:
    """Closures over ``info`` exposed to rule condition / action code."""

    def has_tag(category, *patterns):
        regexes = [re.compile(p) for p in patterns]
        return any(
            r.match(ident.lower())
            for tag in info.tags
            if tag.category == category
            for ident in _tag_identifiers(tag)
            for r in regexes
        )

    def has_url_category(category):
        return any(u.category == category for u in info.urls)

    def is_from_site(category, site):
        return any(
            u.category == category and urlsplit(u.url or "").netloc == site
            for u in info.urls
        )

    def add_tag(*slugs):
        present = {t.slug for t in info.tags if t.slug}
        for slug in slugs:
            if slug not in present:
                info.tags.append(Tag("", slug, None, None))
                present.add(slug)

    def add_raw_tag(category, text):
        if not any(
            t.category == category and t.text == text for t in info.tags
        ):
            info.tags.append(Tag(category, None, None, text))

    def clone_url(from_cat, to_cat, desc_template):
        existing = {u.url for u in info.urls if u.category == to_cat}
        for src in [u for u in info.urls if u.category == from_cat]:
            if src.url in existing:
                continue
            existing.add(src.url)
            fields = {
                "category": src.category,
                "description": src.description or "",
                "url": src.url or "",
            }
            info.urls.append(
                GameUrl(
                    to_cat, src.url_id, desc_template.format(**fields), src.url
                )
            )

    return {
        "has_tag": has_tag,
        "has_url_category": has_url_category,
        "is_from_site": is_from_site,
        "add_tag": add_tag,
        "add_raw_tag": add_raw_tag,
        "clone_url": clone_url,
    }


def _tag_identifiers(tag: Tag) -> list[str]:
    """Names a tag may be matched by: free text, slug, resolved DB name."""
    idents = []
    if tag.text:
        idents.append(tag.text)
    if tag.slug:
        idents.append(tag.slug)
    if tag.tag_id is not None:
        name = (
            GameTag.objects
            .filter(id=tag.tag_id)
            .values_list("name", flat=True)
            .first()
        )
        if name:
            idents.append(name)
    return idents


# -- Built-in transforms --------------------------------------------------


def _lowercase_tags(info: GameInfo) -> None:
    for tag in info.tags:
        if tag.category == "tag" and tag.text:
            tag.text = tag.text.lower()


def _tags_to_genre(info: GameInfo) -> None:
    mapping = {m.tag: m for m in GenreMapping.objects.all()}
    extra: list[Tag] = []
    for tag in info.tags:
        if tag.category != "tag" or not tag.text:
            continue
        m = mapping.get(tag.text.lower())
        if m is None:
            continue
        if m.replace:
            tag.category, tag.slug, tag.tag_id, tag.text = (
                "genre",
                m.genre_slug,
                None,
                None,
            )
        else:
            extra.append(Tag("genre", m.genre_slug, None, None))
    info.tags.extend(extra)
