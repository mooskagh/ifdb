import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from logging import getLogger
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Any, Protocol, TypeVar, cast
from urllib.parse import urlparse

from dateutil.parser import parse as parse_date
from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse

from contest.models import GameListEntry
from contest.views import CompetitionHead, FormatHead
from moder.actions import GetModerActions
from play.models import Playable

from .gameinfo import GameInfo, Person
from .models import (
    URL,
    Game,
    GameAuthorRole,
    GameCommentVote,
    GameDescriptionAttribution,
    GameTag,
    GameTagCategory,
    GameURLCategory,
    PersonalityAlias,
    URLFetch,
)
from .permissions import (
    can_comment_game,
    can_manage_internal_tags,
    can_vote_game,
)
from .search import BaseXWriter
from .tools import (
    ExtractYoutubeId,
    FormatDate,
    FormatTime,
    RenderMarkdown,
    StarsFromRating,
)

logger = getLogger("web")


class RoleCategory(Protocol):
    title: str
    order: int


class UrlCategory(Protocol):
    symbolic_id: str | None
    title: str
    order: int
    allow_cloning: bool


class TagCategory(Protocol):
    id: int | None
    name: str
    order: int
    is_internal: bool


_CategoryT = TypeVar("_CategoryT")


@dataclass
class GamePerson:
    name: str
    personality_id: int | None


@dataclass
class GameParticipant:
    category: RoleCategory
    items: list[GamePerson]


@dataclass
class GamePeople:
    authors: list[GamePerson]
    participants: list[GameParticipant]


@dataclass
class GameUrlValue:
    category: UrlCategory
    description: str | None
    remote_url: str | None
    local_url: str | None
    is_link_broken: bool
    has_local_copy: bool
    url: URL | None = None

    def GetRemoteUrl(self) -> str | None:
        return self.remote_url

    def GetLocalUrl(self) -> str | None:
        return self.local_url

    def HasLocalCopy(self) -> bool:
        return self.has_local_copy


@dataclass
class GameDownloadVersion:
    fetch_id: int
    download_url: str
    date_str: str
    size_str: str | None = None
    filename: str | None = None

    @property
    def label(self) -> str:
        if self.size_str and self.date_str:
            return f"Версия {self.date_str} ({self.size_str})"
        elif self.date_str:
            return f"Версия {self.date_str}"
        elif self.size_str:
            return f"Версия ({self.size_str})"
        return "Версия"


@dataclass
class GameDownloadItem:
    url: str | None
    title: str
    is_local: bool
    is_link_broken: bool = False
    is_direct: bool = True
    size_str: str | None = None
    filename: str | None = None
    older_versions: list[GameDownloadVersion] = field(default_factory=list)


@dataclass
class GameDownloadGroup:
    main_button: GameDownloadItem
    has_dropdown: bool = False
    dropdown_items: list[GameDownloadItem] = field(default_factory=list)


def format_compact_file_size(num_bytes: int | None) -> str | None:
    if num_bytes is None or num_bytes < 0:
        return None
    if num_bytes < 1024:
        return f"{num_bytes}Б"

    units = ["КБ", "МБ", "ГБ", "ТБ"]
    size = float(num_bytes)
    unit_idx = -1
    while size >= 1024 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1

    val = round(size, 1)
    if val >= 1024 and unit_idx < len(units) - 1:
        val = round(val / 1024.0, 1)
        unit_idx += 1

    unit = units[unit_idx]
    if val.is_integer():
        return f"{int(val)}{unit}"
    return f"{val:.1f}{unit}"


def _extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or None
    except Exception:
        return None


def _is_local_url(url: str | None) -> bool:
    if not url:
        return False
    if url.startswith("/") or url.startswith("./"):
        return True
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return True
        if parsed.path.startswith("/f/"):
            return True
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host in {
            "db.crem.xyz",
            "kontigr.com",
            "zok.quest",
            "localhost",
            "127.0.0.1",
        }:
            return True
    except Exception:
        pass
    return False


@dataclass
class GameUrlGroup:
    category: UrlCategory
    items: list[GameUrlValue]


@dataclass
class GameUrlGroups:
    media: list[GameUrlValue]
    online: list[GameUrlValue]
    download: list[GameUrlValue]
    links: list[GameUrlGroup]


@dataclass
class GameMedia:
    type: str
    caption: str | None
    img: str | None = None
    id: str | None = None
    url: str | None = None


@dataclass
class GameTagValue:
    name: str
    search_query: str | None = None


@dataclass
class GameTagDetails:
    tags: list[GameTagValue] = field(default_factory=list)
    genres: list[GameTagValue] = field(default_factory=list)
    primary_properties: list[tuple[TagCategory, list[GameTagValue]]] = field(
        default_factory=list
    )
    secondary_properties: list[tuple[TagCategory, list[GameTagValue]]] = field(
        default_factory=list
    )


@dataclass
class CommentVotes:
    likes: int
    dislikes: int
    allow_vote: bool
    own_vote: int


@dataclass
class GameScore:
    user_played: bool = False
    user_hours: str = ""
    played_count: int = 0
    avg_rating: str | None = None
    stars: list[int] = field(default_factory=list)
    user_score: int | None = None


@dataclass
class GameCommentValue:
    id: int
    user_id: int | None
    username: str
    parent_id: int | None
    created: str | None
    created_raw: datetime
    edited: str | None
    text: str
    is_deleted: bool
    likes: CommentVotes


@dataclass
class GameCompetition:
    slug: str
    title: str
    nomination: str
    head: CompetitionHead | None


@dataclass
class GameContent:
    title: str | None
    description: str | None
    release_date: str | None
    markdown: str
    authors: list[GamePerson]
    participants: list[GameParticipant]
    metadata: GameTagDetails
    media: list[GameMedia]
    online: list[GameUrlValue]
    download: list[GameUrlValue]
    links: list[GameUrlGroup]
    description_attributions: list[str]
    playables: list[Playable]
    playable_base_domain: str
    download_groups: list[GameDownloadGroup]


@dataclass
class GamePage(GameContent):
    comment_perm: bool
    vote_perm: bool
    added_date: str | None
    game: Game
    moder_actions: list[Any]
    last_edit_date: str | None
    votes: GameScore
    comments: list[GameCommentValue]
    competitions: list[GameCompetition]


def _Category(row: _CategoryT | None, symbolic_id: str | None) -> _CategoryT:
    if row is not None:
        return row
    label = symbolic_id or "Прочее"
    return cast(
        _CategoryT,
        SimpleNamespace(
            id=None,
            symbolic_id=symbolic_id,
            name=label,
            title=label,
            order=1000,
            allow_cloning=False,
            is_internal=False,
        ),
    )


def AnnotateMedia(media: list[GameUrlValue]) -> list[GameMedia]:
    result = []
    for item in sorted(
        media,
        key=lambda x: (
            x.category.symbolic_id == "video",
            x.description or "",
        ),
    ):
        category = item.category.symbolic_id
        if category in {"poster", "screenshot"}:
            result.append(
                GameMedia("img", item.description, img=item.local_url)
            )
        elif category == "video":
            youtube_id = (
                ExtractYoutubeId(item.remote_url) if item.remote_url else None
            )
            if youtube_id:
                result.append(
                    GameMedia("youtube", item.description, id=youtube_id)
                )
            else:
                logger.error("Unknown video url: %s", item.remote_url)
                result.append(
                    GameMedia("unknown", item.description, url=item.local_url)
                )
        else:
            logger.error("Unexpected category: %s", item)
    return result


def _PartitionUrls(urls: list[GameUrlValue]) -> GameUrlGroups:
    groups: dict[str | None, list[GameUrlValue]] = defaultdict(list)
    for url in urls:
        groups[url.category.symbolic_id].append(url)

    def take(*symbolic_ids: str) -> list[GameUrlValue]:
        return [url for sid in symbolic_ids for url in groups.get(sid, [])]

    fixed = {
        "poster",
        "screenshot",
        "play_online",
        "download_direct",
        "download_landing",
    }
    rest = sorted(
        (sid for sid in groups if sid not in fixed),
        key=lambda sid: (
            groups[sid][0].category.order,
            groups[sid][0].category.title,
            sid or "",
        ),
    )
    return GameUrlGroups(
        media=take("poster", "screenshot"),
        online=take("play_online"),
        download=take("download_direct", "download_landing"),
        links=[
            GameUrlGroup(groups[sid][0].category, groups[sid]) for sid in rest
        ],
    )


def BuildDownloadGroups(
    raw_urls: list[Any],
    stored_urls: dict[int, URL],
    categories: dict[str | None, UrlCategory],
) -> list[GameDownloadGroup]:
    download_categories = {"download_direct", "download_landing"}
    download_entries = [
        entry
        for entry in raw_urls
        if getattr(entry, "category", None) in download_categories
    ]
    if not download_entries:
        return []

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, entry in enumerate(download_entries):
        url_obj = stored_urls.get(entry.url_id) if entry.url_id else None
        remote_url = (
            entry.url
            if entry.url is not None
            else (getattr(url_obj, "original_url", None) if url_obj else None)
        )
        is_broken = url_obj.is_link_broken() if url_obj else False
        is_uploaded = bool(getattr(url_obj, "is_uploaded", False))
        is_direct = entry.category == "download_direct"

        fetches: list[URLFetch] = []
        if url_obj:
            fetches = list(url_obj.fetches.all())
            fetches.sort(key=lambda f: (f.last_fetch, f.id or 0), reverse=True)

        latest_fetch = fetches[0] if fetches else None
        stored_file = None
        content_hash = None
        local_url = None
        file_size = None
        orig_filename = None

        if latest_fetch and latest_fetch.stored_file:
            stored_file = latest_fetch.stored_file
            content_hash = stored_file.content_hash
            file_size = stored_file.file_size
            local_url = stored_file.public_url
            orig_filename = (
                latest_fetch.original_filename
                or Path(stored_file.storage_path).name
            )
        elif url_obj and url_obj.stored_file:
            stored_file = url_obj.stored_file
            content_hash = stored_file.content_hash
            file_size = stored_file.file_size
            local_url = stored_file.public_url
            orig_filename = (
                url_obj.get_original_filename()
                or Path(stored_file.storage_path).name
            )

        seen_file_ids = set()
        if stored_file and hasattr(stored_file, "id"):
            seen_file_ids.add(stored_file.id)
        elif latest_fetch:
            seen_file_ids.add(latest_fetch.stored_file_id)

        older_versions: list[GameDownloadVersion] = []
        for f in fetches[1:]:
            if f.stored_file_id not in seen_file_ids:
                seen_file_ids.add(f.stored_file_id)
                dt = f.first_fetch or getattr(
                    f.stored_file, "created_at", None
                )
                dt_str = dt.strftime("%Y-%m-%d") if dt else ""
                v_size_str = format_compact_file_size(f.stored_file.file_size)
                v_fname = (
                    f.original_filename
                    or Path(f.stored_file.storage_path).name
                )
                older_versions.append(
                    GameDownloadVersion(
                        fetch_id=f.id,
                        download_url=f.stored_file.public_url,
                        date_str=dt_str,
                        size_str=v_size_str,
                        filename=v_fname,
                    )
                )

        if content_hash:
            group_key = f"hash:{content_hash}"
        else:
            group_key = f"entry:{idx}"

        groups[group_key].append({
            "entry": entry,
            "url_obj": url_obj,
            "remote_url": remote_url,
            "local_url": local_url,
            "stored_file": stored_file,
            "file_size": file_size,
            "orig_filename": orig_filename,
            "is_link_broken": is_broken,
            "is_uploaded": is_uploaded,
            "is_direct": is_direct,
            "older_versions": older_versions,
        })

    result: list[GameDownloadGroup] = []
    for entries in groups.values():
        local_item = next((e for e in entries if e["local_url"]), None)
        if local_item:
            primary_entry = next(
                (
                    e
                    for e in entries
                    if e["is_uploaded"] or _is_local_url(e["remote_url"])
                ),
                entries[0],
            )
            base_desc = (
                primary_entry["entry"].description or ""
            ).strip() or "Скачать"
            size_str = format_compact_file_size(local_item["file_size"])
            main_title = f"{base_desc} ({size_str})" if size_str else base_desc
            main_button = GameDownloadItem(
                url=local_item["local_url"],
                title=main_title,
                is_local=True,
                is_link_broken=False,
                is_direct=True,
                size_str=size_str,
                filename=primary_entry["orig_filename"]
                or local_item["orig_filename"],
            )

            dropdown_items: list[GameDownloadItem] = []
            for e in entries:
                if e["remote_url"] and not _is_local_url(e["remote_url"]):
                    domain = _extract_domain(e["remote_url"])
                    desc = (e["entry"].description or "").strip()
                    if not desc or desc.lower() == "скачать":
                        item_title = (
                            f"Скачать с {domain}" if domain else "Скачать"
                        )
                    else:
                        item_title = desc
                    dropdown_items.append(
                        GameDownloadItem(
                            url=e["remote_url"],
                            title=item_title,
                            is_local=False,
                            is_link_broken=e["is_link_broken"],
                            is_direct=e["is_direct"],
                            size_str=format_compact_file_size(e["file_size"]),
                            filename=e["orig_filename"],
                            older_versions=e["older_versions"],
                        )
                    )
                elif e["older_versions"]:
                    desc = (
                        e["entry"].description or ""
                    ).strip() or "Основная версия"
                    dropdown_items.append(
                        GameDownloadItem(
                            url=e["local_url"],
                            title=desc,
                            is_local=True,
                            is_link_broken=False,
                            is_direct=True,
                            size_str=format_compact_file_size(e["file_size"]),
                            filename=e["orig_filename"],
                            older_versions=e["older_versions"],
                        )
                    )

            has_dropdown = bool(dropdown_items)
            result.append(
                GameDownloadGroup(
                    main_button=main_button,
                    has_dropdown=has_dropdown,
                    dropdown_items=dropdown_items,
                )
            )
        else:
            primary_entry = entries[0]
            base_desc = (
                primary_entry["entry"].description or ""
            ).strip() or "Скачать"
            size_str = format_compact_file_size(primary_entry["file_size"])
            main_title = f"{base_desc} ({size_str})" if size_str else base_desc
            is_local = _is_local_url(primary_entry["remote_url"])
            main_button = GameDownloadItem(
                url=primary_entry["remote_url"],
                title=main_title,
                is_local=is_local,
                is_link_broken=primary_entry["is_link_broken"],
                is_direct=primary_entry["is_direct"],
                size_str=size_str,
                filename=primary_entry["orig_filename"],
            )

            dropdown_items = []
            for e in entries[1:]:
                domain = _extract_domain(e["remote_url"])
                desc = (e["entry"].description or "").strip()
                if not desc or desc.lower() == "скачать":
                    item_title = f"Скачать с {domain}" if domain else "Скачать"
                else:
                    item_title = desc
                dropdown_items.append(
                    GameDownloadItem(
                        url=e["remote_url"],
                        title=item_title,
                        is_local=_is_local_url(e["remote_url"]),
                        is_link_broken=e["is_link_broken"],
                        is_direct=e["is_direct"],
                        size_str=format_compact_file_size(e["file_size"]),
                        filename=e["orig_filename"],
                        older_versions=e["older_versions"],
                    )
                )

            if primary_entry["older_versions"]:
                domain = _extract_domain(primary_entry["remote_url"])
                desc = (primary_entry["entry"].description or "").strip()
                if not desc or desc.lower() == "скачать":
                    item_title = f"Скачать с {domain}" if domain else "Скачать"
                else:
                    item_title = desc
                dropdown_items.insert(
                    0,
                    GameDownloadItem(
                        url=primary_entry["remote_url"],
                        title=item_title,
                        is_local=is_local,
                        is_link_broken=primary_entry["is_link_broken"],
                        is_direct=primary_entry["is_direct"],
                        size_str=size_str,
                        filename=primary_entry["orig_filename"],
                        older_versions=primary_entry["older_versions"],
                    ),
                )

            has_dropdown = bool(dropdown_items)
            result.append(
                GameDownloadGroup(
                    main_button=main_button,
                    has_dropdown=has_dropdown,
                    dropdown_items=dropdown_items,
                )
            )

    return result


def GetCommentVotes(vote_set: Any, user: Any, comment: Any) -> CommentVotes:
    likes = vote_set.filter(vote=1).count()
    dislikes = vote_set.filter(vote=-1).count()
    if user and not user.is_authenticated:
        user = None
    try:
        own_vote = vote_set.get(user=user).vote
    except GameCommentVote.DoesNotExist:
        own_vote = 0
    return CommentVotes(
        likes=likes,
        dislikes=dislikes,
        allow_vote=(
            user is not None
            and comment.user != user
            and not comment.is_deleted
        ),
        own_vote=own_vote,
    )


class GameDetailsBuilder:
    def __init__(self, info: GameInfo):
        self.info = info

    def GetContentDict(
        self, request: HttpRequest | None = None
    ) -> GameContent:
        people = self.GetPeople()
        urls = _PartitionUrls(self.GetUrls())
        return GameContent(
            title=self.info.name,
            description=self.info.description,
            release_date=self._GetReleaseDate(),
            markdown=RenderMarkdown(self.info.description),
            authors=people.authors,
            participants=people.participants,
            metadata=self.GetTagsForDetails(request),
            media=AnnotateMedia(urls.media),
            online=urls.online,
            download=urls.download,
            links=urls.links,
            description_attributions=self.GetAttributions(),
            playables=[],
            playable_base_domain=settings.PLAYABLE_BASE_DOMAIN,
            download_groups=self.GetDownloadGroups(),
        )

    def GetGameDict(self, game: Game, request: HttpRequest) -> GamePage:
        content = self.GetContentDict(request)
        content.playables = list(
            Playable.objects
            .filter(
                game=game,
                visible=True,
                state=Playable.State.READY,
            )
            .exclude(slug__isnull=True)
            .exclude(slug="")
            .order_by("pk")
        )
        return GamePage(
            **vars(content),
            comment_perm=can_comment_game(request.user, game),
            vote_perm=can_vote_game(request.user, game),
            added_date=FormatDate(game.creation_time),
            game=game,
            moder_actions=GetModerActions(request, "Game", game),
            last_edit_date=FormatDate(game.edit_time),
            votes=self.GetGameScore(game, request),
            comments=self.GetGameComments(game, request),
            competitions=self.GetCompetitions(game),
        )

    def _GetReleaseDate(self) -> str | None:
        if not self.info.date:
            return None
        value = (
            self.info.date
            if isinstance(self.info.date, date)
            else parse_date(self.info.date).date()
        )
        return cast(str | None, FormatDate(value))

    def GetPeople(self) -> GamePeople:
        role_ids = {
            role for role in self.info.personalities if role is not None
        }
        roles: dict[str | None, RoleCategory] = {
            role.symbolic_id: role
            for role in GameAuthorRole.objects.filter(symbolic_id__in=role_ids)
        }
        alias_ids = {
            person.alias_id
            for people in self.info.personalities.values()
            for person in people
            if person.alias_id is not None
        }
        aliases = {
            alias.id: alias
            for alias in PersonalityAlias.objects.filter(
                id__in=alias_ids
            ).select_related("personality")
        }

        def render_person(person: Person) -> GamePerson:
            alias = aliases.get(person.alias_id)
            return GamePerson(
                name=(
                    alias.name
                    if alias
                    else person.name
                    or f"(неизвестный псевдоним #{person.alias_id})"
                ),
                personality_id=alias.personality_id if alias else None,
            )

        authors = []
        participants = []
        for role_id, people in self.info.personalities.items():
            if not people:
                continue
            category: RoleCategory = _Category(roles.get(role_id), role_id)
            items = [render_person(person) for person in people]
            if role_id == "author":
                authors.extend(items)
            else:
                participants.append(GameParticipant(category, items))
        participants.sort(key=lambda x: (x.category.order, x.category.title))
        return GamePeople(authors, participants)

    def _GetStoredData(
        self,
    ) -> tuple[dict[int, URL], dict[str | None, UrlCategory]]:
        if not hasattr(self, "_stored_urls") or not hasattr(
            self, "_stored_categories"
        ):
            url_ids = {
                entry.url_id
                for entry in self.info.urls
                if entry.url_id is not None
            }
            self._stored_urls = {
                url.id: url
                for url in URL.objects.filter(id__in=url_ids).prefetch_related(
                    "fetches__stored_file"
                )
            }
            self._stored_categories = {
                category.symbolic_id: category
                for category in GameURLCategory.objects.filter(
                    symbolic_id__in={
                        entry.category for entry in self.info.urls
                    }
                )
            }
        return self._stored_urls, self._stored_categories

    def GetDownloadGroups(self) -> list[GameDownloadGroup]:
        stored, categories = self._GetStoredData()
        return BuildDownloadGroups(self.info.urls, stored, categories)

    def GetUrls(self) -> list[GameUrlValue]:
        stored, categories = self._GetStoredData()
        result = []
        for entry in self.info.urls:
            category: UrlCategory = _Category(
                categories.get(entry.category), entry.category
            )
            url = (
                stored.get(entry.url_id) if entry.url_id is not None else None
            )
            remote_url = (
                entry.url
                if entry.url is not None
                else getattr(url, "original_url", None)
            )
            if url is not None:
                local_url = (
                    url.get_local_url() or remote_url
                    if category.allow_cloning
                    else remote_url
                )
                is_broken = url.is_link_broken()
                has_local_copy = bool(
                    category.allow_cloning
                    and not url.is_uploaded
                    and url.has_stored_copy()
                )
            else:
                local_url = remote_url
                is_broken = False
                has_local_copy = False
            result.append(
                GameUrlValue(
                    category=category,
                    description=entry.description,
                    remote_url=remote_url,
                    local_url=local_url,
                    is_link_broken=is_broken,
                    has_local_copy=has_local_copy,
                    url=url,
                )
            )
        return result

    def GetTagsForDetails(
        self, request: HttpRequest | None = None
    ) -> GameTagDetails:
        user = (
            request.user if request and request.user.is_authenticated else None
        )
        can_view_internal = can_manage_internal_tags(user)
        primary_sids = {"version", "language", "platform", "age"}
        stored = {
            tag.id: tag
            for tag in GameTag.objects.filter(
                id__in={
                    entry.tag_id
                    for entry in self.info.tags
                    if entry.tag_id is not None
                }
            ).select_related("category")
        }
        category_ids = {entry.category for entry in self.info.tags}
        category_ids.update(
            tag.category.symbolic_id for tag in stored.values()
        )
        categories: dict[str | None, TagCategory] = {
            category.symbolic_id: category
            for category in GameTagCategory.objects.filter(
                symbolic_id__in=category_ids
            )
        }
        grouped: dict[str | None, list[GameTagValue]] = defaultdict(list)
        category_values: dict[str | None, TagCategory] = {}
        for entry in self.info.tags:
            tag_row = stored.get(entry.tag_id)
            category_id: str | None = (
                tag_row.category.symbolic_id if tag_row else entry.category
            )
            category_row = categories.get(category_id) or (
                tag_row.category if tag_row else None
            )
            category: TagCategory = cast(
                TagCategory, _Category(category_row, category_id)
            )
            if (
                getattr(category, "is_internal", False)
                and not can_view_internal
            ):
                continue
            if tag_row:
                writer = BaseXWriter()
                writer.addHeader(2, category.id)
                writer.addSet([tag_row.id])
                value = GameTagValue(
                    name=tag_row.name,
                    search_query=f"{reverse('list_games')}?q={writer.GetStr()}",
                )
            else:
                value = GameTagValue(
                    name=(
                        entry.text
                        if entry.text is not None
                        else entry.slug or f"(неизвестный тег #{entry.tag_id})"
                    )
                )
            grouped[category_id].append(value)
            category_values[category_id] = category

        ordered = sorted(
            grouped,
            key=lambda category_id: (
                category_values[category_id].order,
                min(tag.name for tag in grouped[category_id]),
                category_id or "",
            ),
        )
        details = GameTagDetails()
        for category_id in ordered:
            tags = sorted(grouped[category_id], key=lambda tag: tag.name)
            category = category_values[category_id]
            if category_id == "genre":
                details.genres.extend(tags)
            elif category_id == "tag":
                details.tags.extend(tags)
            elif category_id in primary_sids:
                details.primary_properties.append((category, tags))
            else:
                details.secondary_properties.append((category, tags))
        return details

    def GetAttributions(self) -> list[str]:
        stored = {
            attribution.id: attribution
            for attribution in GameDescriptionAttribution.objects.filter(
                id__in={
                    entry.attr_id
                    for entry in self.info.attributions
                    if entry.attr_id is not None
                }
            )
        }
        names: list[str] = []
        for entry in self.info.attributions:
            names.append(
                cast(str, stored[entry.attr_id].name)
                if entry.attr_id in stored
                else entry.name or f"(неизвестный источник #{entry.attr_id})"
            )
        return sorted(names)

    def GetCompetitions(self, game: Game) -> list[GameCompetition]:
        comps = GameListEntry.objects.filter(
            game=game, gamelist__competition__isnull=False
        ).select_related("gamelist", "gamelist__competition")
        return [
            GameCompetition(
                slug=entry.gamelist.competition.slug,
                title=entry.gamelist.competition.title,
                nomination=entry.gamelist.title,
                head=FormatHead(
                    entry,
                    json.loads(entry.gamelist.competition.options),
                ),
            )
            for entry in comps
        ]

    def GetGameScore(self, game: Game, request: HttpRequest) -> GameScore:
        user = request.user if request.user.is_authenticated else None
        votes = list(game.gamevote_set.all())
        scores = [vote.star_rating for vote in votes]
        result = GameScore(played_count=len(scores))
        for vote in votes:
            if vote.user == user:
                result.user_played = True
                result.user_score = vote.star_rating
        if scores:
            average = mean(scores)
            result.avg_rating = ("%3.1f" % average).replace(".", ",")
            result.stars = StarsFromRating(average)
        return result

    def GetGameComments(
        self, game: Game, request: HttpRequest
    ) -> list[GameCommentValue]:
        comments = []
        for comment in game.gamecomment_set.select_related(
            "user"
        ).prefetch_related("gamecommentvote_set"):
            comments.append(
                GameCommentValue(
                    id=comment.id,
                    user_id=comment.user.id if comment.user else None,
                    username=comment.GetUsername(),
                    parent_id=comment.parent.id if comment.parent else None,
                    created=FormatTime(comment.creation_time),
                    created_raw=comment.creation_time,
                    edited=FormatTime(comment.edit_time),
                    text=RenderMarkdown(comment.text),
                    is_deleted=comment.is_deleted,
                    likes=GetCommentVotes(
                        comment.gamecommentvote_set, request.user, comment
                    ),
                )
            )

        parent_to_cluster: dict[int, int] = {}
        clusters: list[list[GameCommentValue]] = []
        pending = comments
        while pending:
            swap = []
            for comment in pending:
                parent_id = comment.parent_id
                if not parent_id:
                    parent_to_cluster[comment.id] = len(clusters)
                    clusters.append([comment])
                elif parent_id in parent_to_cluster:
                    clusters[parent_to_cluster[parent_id]].append(comment)
                    parent_to_cluster[comment.id] = parent_to_cluster[
                        parent_id
                    ]
                else:
                    swap.append(comment)
            pending = swap
        clusters.sort(key=lambda cluster: cluster[0].created_raw)
        for cluster in clusters:
            cluster[1:] = sorted(
                cluster[1:], key=lambda comment: comment.created_raw
            )
        return [comment for cluster in clusters for comment in cluster]
