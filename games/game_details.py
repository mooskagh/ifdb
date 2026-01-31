import json
from collections import defaultdict
from dataclasses import dataclass, field
from logging import getLogger
from statistics import mean
from typing import Tuple

from django.conf import settings
from django.urls import reverse

from contest.models import GameListEntry
from contest.views import FormatHead
from core.views import BuildPackageUserFingerprint
from moder.actions import GetModerActions

from .models import Game, GameCommentVote, GameTagCategory
from .search import BaseXWriter
from .tools import (
    ExtractYoutubeId,
    FormatDate,
    FormatTime,
    PartitionItems,
    RenderMarkdown,
    StarsFromRating,
)

logger = getLogger("web")


def AnnotateMedia(media):
    res = []
    media.sort(
        key=lambda x: (x.category.symbolic_id == "video", x.description)
    )
    for y in media:
        val = {}
        if y.category.symbolic_id in ["poster", "screenshot"]:
            val["type"] = "img"
            val["img"] = y.GetLocalUrl()
        elif y.category.symbolic_id == "video":
            idd = ExtractYoutubeId(y.url.original_url)
            if idd:
                val["type"] = "youtube"
                val["id"] = idd
            else:
                logger.error("Unknown video url: %s" % y.url.original_url)
                val["type"] = "unknown"
                val["url"] = y.GetLocalUrl()
        else:
            logger.error("Unexpected category: %s" % y)
            continue
        val["caption"] = y.description
        res.append(val)
    return res


def GetCommentVotes(vote_set, user, comment):
    likes = vote_set.filter(vote=1).count()
    dislikes = vote_set.filter(vote=-1).count()
    own_vote = 0

    if user and not user.is_authenticated:
        user = None
    allow_vote = (
        user is not None and comment.user != user and not comment.is_deleted
    )

    try:
        own_vote = vote_set.get(user=user).vote
    except GameCommentVote.DoesNotExist:
        pass

    return {
        "likes": likes,
        "dislikes": dislikes,
        "allow_vote": allow_vote,
        "own_vote": own_vote,
    }


@dataclass
class GameTagDetails:
    tags: list = field(default_factory=list)
    genres: list = field(default_factory=list)
    primary_properties: list[Tuple[GameTagCategory, list]] = field(
        default_factory=list
    )
    secondary_properties: list[Tuple[GameTagCategory, list]] = field(
        default_factory=list
    )


class GameDetailsBuilder:
    def __init__(self, game_id, request):
        self.game = (
            Game.objects
            .prefetch_related(
                "gameauthor_set__role",
                "gameauthor_set__author",
                "gameurl_set__category",
                "gameurl_set__url",
                "tags__category",
            )
            .select_related()
            .get(id=game_id)
        )
        self.request = request
        request.perm.Ensure(self.game.view_perm)

    def GetGameDict(self):
        release_date = FormatDate(self.game.release_date)
        last_edit_date = FormatDate(self.game.edit_time)
        added_date = FormatDate(self.game.creation_time)
        authors, participants = PartitionItems(
            self.game.gameauthor_set.all(),
            [("author",)],
            catfield="role",
            follow="author",
        )
        media, online, download, links = PartitionItems(
            self.game.gameurl_set.all(),
            [
                ("poster", "screenshot"),
                ("play_in_interpreter", "play_online"),
                ("download_direct", "download_landing"),
            ],
        )
        media = AnnotateMedia(media)
        md = RenderMarkdown(self.game.description)
        metadata = self.GetTagsForDetails()
        votes = self.GetGameScore()
        comments = self.GetGameComments()
        competitions = self.GetCompetitions()
        loonchator_links = []
        for x in self.game.package_set.all():
            loonchator_links.append(
                "%s://rungame/%s"
                % (
                    ("ersatzplut-debug" if settings.DEBUG else "ersatzplut"),
                    BuildPackageUserFingerprint(
                        (
                            self.request.user
                            if self.request.user.is_authenticated
                            else None
                        ),
                        x.id,
                    ),
                )
            )
        return {
            "comment_perm": self.request.perm(self.game.comment_perm),
            "vote_perm": self.request.perm(self.game.vote_perm),
            "added_date": added_date,
            "authors": authors,
            "participants": participants,
            "game": self.game,
            "moder_actions": GetModerActions(self.request, "Game", self.game),
            "last_edit_date": last_edit_date,
            "markdown": md,
            "release_date": release_date,
            "metadata": metadata,
            "links": links,
            "media": media,
            "online": online,
            "download": download,
            "votes": votes,
            "comments": comments,
            "loonchator_links": loonchator_links,
            "competitions": competitions,
        }

    def GetCompetitions(self):
        comps = GameListEntry.objects.filter(
            game=self.game, gamelist__competition__isnull=False
        ).select_related("gamelist", "gamelist__competition")
        res = []
        for x in comps:
            opts = json.loads(x.gamelist.competition.options)
            item = {
                "slug": x.gamelist.competition.slug,
                "title": x.gamelist.competition.title,
                "nomination": x.gamelist.title,
                "head": FormatHead(x, opts),
            }

            res.append(item)
        return res

    def GetTagsForDetails(self) -> GameTagDetails:
        primary_sids = {"version", "language", "platform", "age"}
        grouped = defaultdict(list)

        queryset = self.game.tags.select_related("category").order_by(
            "category__order", "name"
        )

        for tag in queryset:
            cat = tag.category
            if not self.request.perm(cat.show_in_details_perm):
                continue

            # Augment tag
            writer = BaseXWriter()
            writer.addHeader(2, cat.id)
            writer.addSet([tag.id])
            tag.search_query = f"{reverse('list_games')}?q={writer.GetStr()}"

            grouped[cat].append(tag)

        details = GameTagDetails()

        for cat, tags in grouped.items():
            if cat.symbolic_id == "genre":
                details.genres.extend(tags)
            elif cat.symbolic_id == "tag":
                details.tags.extend(tags)
            elif cat.symbolic_id in primary_sids:
                details.primary_properties.append((cat, tags))
            else:
                details.secondary_properties.append((cat, tags))

        return details

    ################################################
    # Returns:
    # - avg_rating
    # - stars[5]
    # - played_count
    # - finished_count
    # - played_hours
    # - played_mins
    # - finished_hours
    # - finished_mins
    # - user_played
    # - user_hours
    # - user_mins
    # - user_score
    def GetGameScore(self):
        user = self.request.user
        res = {"user_played": False}
        if user and not user.is_authenticated:
            user = None
        played_votes = []
        res["user_hours"] = ""

        for v in self.game.gamevote_set.all():
            played_votes.append(v.star_rating)
            if v.user == user:
                res["user_played"] = True
                res["user_score"] = v.star_rating

        res["played_count"] = len(played_votes)
        if played_votes:
            avg = mean(played_votes)
            res["avg_rating"] = ("%3.1f" % avg).replace(".", ",")
            res["stars"] = StarsFromRating(avg)

        return res

    # Returns repeated:
    # user__name
    # parent__id
    #
    def GetGameComments(self):
        res = []
        for v in self.game.gamecomment_set.select_related(
            "user"
        ).prefetch_related("gamecommentvote_set"):
            likes = GetCommentVotes(
                v.gamecommentvote_set, self.request.user, v
            )
            res.append({
                "id": v.id,
                "user_id": v.user.id if v.user else None,
                "username": v.GetUsername(),
                "parent_id": v.parent.id if v.parent else None,
                "created": FormatTime(v.creation_time),
                "created_raw": v.creation_time,
                "edited": FormatTime(v.edit_time),
                "text": RenderMarkdown(v.text),
                "is_deleted": v.is_deleted,
                "likes": likes,
            })

        parent_to_cluster = {}
        clusters = []

        while res:
            swap = []
            for v in res:
                if not v["parent_id"]:
                    parent_to_cluster[v["id"]] = len(clusters)
                    clusters.append([v])
                elif v["parent_id"] in parent_to_cluster:
                    clusters[parent_to_cluster[v["parent_id"]]].append(v)
                    parent_to_cluster[v["id"]] = parent_to_cluster[
                        v["parent_id"]
                    ]
                else:
                    swap.append(v)
            res = swap

        clusters.sort(key=lambda x: x[0]["created_raw"])
        for x in clusters:
            x[1:] = sorted(x[1:], key=lambda t: t["created_raw"])

        return [x for y in clusters for x in y]
