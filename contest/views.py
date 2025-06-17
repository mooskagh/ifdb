import datetime
import json
from collections import defaultdict

from dateutil import relativedelta
from django import forms
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db.models import Count, Max
from django.forms import widgets
from django.http import Http404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from games.models import GameAuthor, GameURL
from games.tools import (
    ComputeGameRating,
    FormatDate,
    PartitionItems,
    RenderMarkdown,
)
from moder.actions import GetModerActions
from moder.userlog import LogAction

from .models import (
    Competition,
    CompetitionDocument,
    CompetitionSchedule,
    CompetitionURL,
    CompetitionVote,
    GameList,
    GameListEntry,
)
from .voting import RenderVoting


def FormatHead(g, options):
    if options.get("listtype") == "parovoz":
        if g.date:
            end = g.date + datetime.timedelta(days=6)
            return {
                "primary": g.date.strftime("%d.%m"),
                "secondary": end.strftime("— %d.%m"),
            }
    else:
        if g.result:
            return {"combined": g.result}
        if g.rank:
            return {"primary": g.rank, "secondary": "место"}


class CompetitionGameFetcher:
    def __init__(self, comp):
        self.comp = comp
        self.options = json.loads(comp.options)

    def GetCompetitionGamesRaw(self):
        lists = []
        for x in GameList.objects.filter(competition=self.comp).order_by(
            "order"
        ):
            ranked = []
            unranked = []
            for y in (
                x.gamelistentry_set.annotate(
                    coms_count=Count("game__gamecomment"),
                    coms_recent=Max("game__gamecomment__creation_time"),
                )
                .prefetch_related(
                    "game__gamevote_set",
                    "game__gameauthor_set__role",
                    "game__gameauthor_set__author",
                )
                .order_by("rank", "date", "result", "game__title")
            ):
                if y.rank is None:
                    unranked.append(y)
                else:
                    ranked.append(y)
            if ranked or unranked:
                lists.append({
                    "title": x.title,
                    "unranked": unranked,
                    "ranked": ranked,
                })
        return lists

    def FetchSnippetData(self):
        raw = self.GetCompetitionGamesRaw()
        games = set()
        for x in raw:
            for y in ["unranked", "ranked"]:
                for z in x[y]:
                    if z.game:
                        games.add(z.game_id)

        posters = (
            GameURL.objects.filter(category__symbolic_id="poster")
            .filter(game__in=games)
            .select_related("url")
        )
        screenshots = (
            GameURL.objects.filter(category__symbolic_id="screenshot")
            .filter(game__in=games)
            .select_related("url")
        )
        author_objs = GameAuthor.objects.filter(
            game__in=games, role__symbolic_id="author"
        ).select_related("author")

        g2p = {}
        authors = defaultdict(list)
        for x in posters:
            g2p[x.game_id] = x.GetLocalUrl()
        for x in screenshots:
            if x.game_id not in g2p:
                g2p[x.game_id] = x.GetLocalUrl()
        for x in author_objs:
            authors[x.game_id].append(x.author.name)

        now = timezone.now()
        for x in raw:
            for y in ["unranked", "ranked"]:
                for z in x[y]:
                    z.head = FormatHead(z, self.options)
                    if z.game:
                        g = z.game
                        g.added_age = None
                        g.release_age = None
                        if g.creation_time:
                            g.added_age = (
                                now - g.creation_time
                            ).total_seconds()
                        if g.release_date:
                            g.release_age = (
                                now.date() - g.release_date
                            ).total_seconds()
                        g.poster = g2p.get(z.game_id)
                        g.authors = ", ".join(authors[g.id])

                        votes = [x.star_rating for x in g.gamevote_set.all()]
                        g.rating = ComputeGameRating(votes)
        return raw


class SnippetProvider:
    def __init__(self, request, comp):
        self.request = request
        self.comp = comp
        self.fetcher = CompetitionGameFetcher(comp)

    def render_RESULTS(self):
        lists = self.fetcher.FetchSnippetData()
        return render_to_string(
            "contest/rankings.html", {"nominations": lists}
        )

    def render_PARTICIPANTS(self):
        return self.render_RESULTS()

    def render_VOTING(self, group=None):
        return RenderVoting(self.request, self.comp, group)

    def render_VOTING_PREVIEW(self, group=None):
        return RenderVoting(self.request, self.comp, group, preview=True)


def show_competition(request, slug, doc=""):
    try:
        comp = Competition.objects.get(slug=slug)
        docobj = CompetitionDocument.objects.get(slug=doc, competition=comp)
    except ObjectDoesNotExist:
        raise Http404()

    request.perm.Ensure(docobj.view_perm)
    LogAction(request, "comp-view", is_mutation=False, obj=comp, obj2=docobj)

    logos = CompetitionURL.objects.filter(
        category__symbolic_id="logo", competition=comp
    )
    logo = logos[0].GetLocalUrl() if logos else None

    links = []
    for x in CompetitionDocument.objects.filter(competition=comp).order_by(
        "order", "slug"
    ):
        if not request.perm(x.view_perm):
            continue
        x.current = x.slug == doc
        links.append(x)

    logos, ext_links = PartitionItems(
        comp.competitionurl_set.all(), [("logo",)]
    )
    return render(
        request,
        "contest/competition.html",
        {
            "comp": comp,
            "doc": docobj,
            "markdown": RenderMarkdown(
                docobj.text, SnippetProvider(request, comp)
            ),
            "logo": logo,
            "docs": links,
            "links": ext_links,
            "moder_actions": (
                GetModerActions(request, "CompetitionDocument", docobj)
                if settings.SITE_ID == 1
                else {}
            ),
        },
    )


MONTHS = [
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
]

SHOW_LINKS = [
    "official_page",
    "other_site",
    "forum",
]

COLOR_RULES = [
    ("kril", "green"),
    ("parovoz", "red"),
    ("lok", "yellow"),
    ("zok", "blue"),
    ("parserfest", "black"),
    ("zh", "brown"),
    ("qspcompo", "salad"),
    ("kontigr", "purple"),
]


def _seconds_until_midnight():
    """Calculate seconds until next midnight for cache expiration."""
    now = timezone.now()
    tomorrow = now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + datetime.timedelta(days=1)
    return int((tomorrow - now).total_seconds())


def _render_snippet_html(items):
    """Fast HTML generation alternative to template rendering.

    UNUSED: Kept for potential future use after Django 5 upgrade.
    This function provides ~10x faster snippet rendering than Django templates
    but we're keeping template rendering for now to see if Django 5 optimizes.
    """
    # Much faster than Django template rendering for repetitive HTML
    # Generates same output as core/snippet.html template
    parts = []

    for item in items:
        if item.get("style") == "subheader":
            text = str(item["text"])
            if item.get("link"):
                target = ' target="_blank"' if item.get("newtab") else ""
                parts.append(
                    f'<a class="grid-box-subheader" '
                    f'href="{item["link"]}"{target}>{text}</a>'
                )
            else:
                parts.append(f'<div class="grid-box-subheader">{text}</div>')
        else:
            # Main item
            if item.get("link"):
                target = ' target="_blank"' if item.get("newtab") else ""
                parts.append(
                    f'<a class="grid-box-item" href="{item["link"]}"{target}>'
                )
            else:
                parts.append('<div class="grid-box-item">')

            # Head
            if item.get("head"):
                parts.append('<div class="grid-box-item-head-container">')
                head = item["head"]
                if head.get("combined"):
                    parts.append(str(head["combined"]))
                else:
                    primary = head.get("primary", "")
                    secondary = str(head.get("secondary", ""))
                    parts.append(f'<span class="rank">{primary}</span><br />')
                    parts.append(secondary)
                parts.append("</div>")

            # Tiny head
            if item.get("tinyhead"):
                parts.append('<div class="grid-box-item-head-container-tiny">')
                tinyhead = item["tinyhead"]
                if tinyhead.get("combined"):
                    combined = tinyhead["combined"]
                    parts.append(f'<span class="rank-tiny">{combined}</span>')
                else:
                    primary = str(tinyhead.get("primary", ""))
                    secondary = tinyhead.get("secondary", "")
                    parts.append(primary)
                    parts.append(f'<span class="rank-tiny">{secondary}</span>')
                parts.append("</div>")

            # Lines
            parts.append('<div class="grid-box-lines-container">')
            for line in item.get("lines", []):
                styles = line.get("style", [])
                style_str = " ".join(f"grid-box-line-{s}" for s in styles)
                line_class = f"grid-box-line {style_str}".strip()

                if line.get("link"):
                    target = ' target="_blank"' if line.get("newtab") else ""
                    parts.append(
                        f'<a class="{line_class}" '
                        f'href="{line["link"]}"{target}>'
                    )
                else:
                    parts.append(f'<div class="{line_class}">')

                parts.append(str(line.get("text", "")))
                parts.append("</a>" if line.get("link") else "</div>")
            parts.append("</div>")

            # Close main
            parts.append("</a>" if item.get("link") else "</div>")

    return "".join(parts)


def get_competitions_data():
    """Cache competition database queries until midnight.

    Uses file-based cache to ensure consistency across processes and
    persistence across server restarts. Competition data changes rarely
    but queries are expensive (86 competitions with complex joins).
    """
    import logging

    logger = logging.getLogger(__name__)

    cache_key = "contest:competitions_list_data"
    data = cache.get(cache_key)
    if data is None:
        logger.info("Competition data cache MISS - querying database")
        start_time = timezone.now()

        # Cache expensive database queries
        competitions = list(
            Competition.objects.filter(published=True).order_by("-end_date")
        )

        schedule = defaultdict(list)
        for x in CompetitionSchedule.objects.filter(show=True).order_by(
            "when"
        ):
            schedule[x.competition_id].append({
                "when": x.when,
                "title": x.title,
            })

        links = defaultdict(list)
        for x in CompetitionURL.objects.filter(
            category__symbolic_id__in=SHOW_LINKS
        ).select_related():
            links[x.competition_id].append({
                "description": x.description,
                "url": x.GetRemoteUrl(),
            })

        logos = {}
        for x in CompetitionURL.objects.filter(
            category__symbolic_id="logo"
        ).select_related():
            logos[x.competition_id] = x.GetLocalUrl()

        # Cache competition games data (the main performance bottleneck)
        competition_games = {
            comp.id: CompetitionGameFetcher(comp).GetCompetitionGamesRaw()
            for comp in competitions
        }

        # Pre-parse JSON options to avoid repeated parsing
        competition_options = {
            comp.id: json.loads(comp.options) for comp in competitions
        }

        data = {
            "competitions": competitions,
            "schedule": schedule,
            "links": links,
            "logos": logos,
            "competition_games": competition_games,
            "competition_options": competition_options,
        }

        query_time = (timezone.now() - start_time).total_seconds()
        timeout = _seconds_until_midnight()
        cache.set(cache_key, data, timeout)

        logger.info(
            f"Competition data cached: {len(competitions)} competitions, "
            f"query took {query_time:.3f}s, cache expires in "
            f"{timeout / 3600:.1f}h"
        )
    else:
        logger.info("Competition data cache HIT - using cached data")

    return data


def list_competitions(request):
    end_date = datetime.date.today().replace(
        day=1
    ) + relativedelta.relativedelta(months=1)
    now = timezone.now()

    # Get cached database data
    cached_data = get_competitions_data()

    # Process cached schedule data with fresh date formatting
    schedule = defaultdict(list)
    for comp_id, entries in cached_data["schedule"].items():
        for entry in entries:
            schedule[comp_id].append({
                "lines": [
                    {
                        "text": FormatDate(entry["when"]),
                        "style": (
                            ["float-right"]
                            + (["dimmed"] if entry["when"] < now else [])
                        ),
                    },
                    {
                        "text": entry["title"],
                        "style": ["strong"],
                    },
                ]
            })

    # Process cached links data
    links = defaultdict(list)
    for comp_id, entries in cached_data["links"].items():
        for entry in entries:
            links[comp_id].append({
                "lines": [
                    {
                        "text": entry["description"],
                        "link": entry["url"],
                        "newtab": True,
                        "style": ["strong"],
                    }
                ]
            })

    # Use cached logos
    logos = cached_data["logos"]

    upcoming = []
    contests = []

    # Main competition processing loop
    d = now.date()
    eighteen_months = relativedelta.relativedelta(months=18)  # Pre-compute

    for x in cached_data["competitions"]:
        options = cached_data["competition_options"][x.id]
        if x.start_date and x.start_date < d:
            d = x.start_date

        if x.end_date - eighteen_months < d:
            d = x.end_date - eighteen_months

        x.box_color = None
        for pref, col in COLOR_RULES:
            if x.slug.startswith(pref):
                x.box_color = col
                break
        if x.end_date < now.date():
            x.top = 1 + (end_date - x.end_date).days
        else:
            x.top = 0
        x.logo = logos.get(x.id)

        items = []

        if x.end_date >= now.date():
            if schedule[x.id]:
                items.append({
                    "style": "subheader",
                    "text": "Расписание",
                })
                items.extend(schedule[x.id])
            if links[x.id]:
                items.append({
                    "style": "subheader",
                    "text": "Ссылки",
                })
                items.extend(links[x.id])

        games = cached_data["competition_games"].get(x.id, [])
        if games:
            for entry in games:
                if entry["title"] or x.end_date >= now.date():
                    items.append({
                        "style": "subheader",
                        "text": entry["title"] or "Участники",
                    })
                for z in entry["ranked"] + entry["unranked"]:
                    lines = []
                    item = {}
                    item["lines"] = lines
                    item["tinyhead"] = FormatHead(z, options)
                    if z.game:
                        g = z.game
                        lines.append({"text": g.title})
                        item["link"] = reverse(
                            "show_game", kwargs={"game_id": g.id}
                        )

                    else:
                        if z.comment:
                            lines.append({
                                "text": z.comment,
                                "style": ["light"],
                            })
                        else:
                            lines.append({})
                    items.append(item)
        x.snippet = render_to_string("core/snippet.html", {"items": items})
        # NOTE: Can use _render_snippet_html(items) for ~10x faster rendering

        if x.start_date and x.start_date >= now.date():
            upcoming.append(x)
        else:
            contests.append(x)

    d = d.replace(day=1)
    ruler = []
    total_height = 30
    while d < end_date:
        days = (d + relativedelta.relativedelta(months=1) - d).days
        ruler.append({
            "label": "%s '%02d" % (MONTHS[d.month - 1], d.year % 100),
            "days": days,
            "long": d.month == 12,
        })
        total_height += days
        d += relativedelta.relativedelta(months=1)
    ruler.append({"label": "текущие", "days": 1, "long": True})
    ruler.reverse()

    return render(
        request,
        "contest/index.html",
        {
            "ruler": ruler,
            "contests": contests,
            "upcoming": upcoming,
        },
    )


class NominationSelectionForm(forms.Form):
    def __init__(self, *args, competition=None, **argw):
        super().__init__(*args, **argw)
        if competition:
            self.fields["category"].choices = [
                (x.id, x.title or "(основная)")
                for x in GameList.objects.filter(
                    competition=competition
                ).order_by("order")
            ]

    category = forms.ChoiceField(
        label="Номинация", required=True, choices=[(None, "(нету)")]
    )


class VotesToShow(forms.Form):
    def __init__(self, *args, fields, **argw):
        super().__init__(*args, **argw)
        self.fields["fields"].choices = [
            (x["name"], x["label"]) for x in fields
        ]

    shown = forms.BooleanField(
        initial=True, widget=widgets.HiddenInput(), required=False
    )

    fields = forms.MultipleChoiceField(
        label="Поля", required=True, widget=forms.CheckboxSelectMultiple
    )

    showtime = forms.BooleanField(label="Показывать время", required=False)

    highlight = forms.DateTimeField(
        label="Выделять новее чем",
        required=False,
        input_formats=["%Y-%m-%d %H:%M"],
    )


def FirstNotNone(*argv):
    for x in argv:
        if x is not None:
            return x
    return None


def list_votes(request, id):
    comp = Competition.objects.get(pk=id)
    options = json.loads(comp.options)
    voting = options.get("voting")
    if not voting:
        raise PermissionDenied
    if comp.owner:
        request.perm.Ensure("(o @admin [%d])" % comp.owner_id)
    else:
        request.perm.Ensure("(o @admin)")

    if "category" in request.GET:
        nomination_form = NominationSelectionForm(
            request.GET, competition=comp
        )
    else:
        nomination_form = NominationSelectionForm(
            {
                "category": (
                    GameList.objects.filter(competition=comp)
                    .order_by("order")[0]
                    .id
                ),
            },
            competition=comp,
        )

    if nomination_form.is_valid():
        selected_nomination = int(nomination_form.cleaned_data["category"])
        prefix = "n%d" % selected_nomination
        next(x for x in voting["view_nominations"] if x == selected_nomination)
        if "%s-shown" % prefix in request.GET:
            details_form = VotesToShow(
                request.GET, fields=voting["fields"], prefix=prefix
            )
        else:
            details_form = VotesToShow(
                {
                    "%s-fields" % prefix: [voting["fields"][0]["name"]],
                    "%s-highlight" % prefix: (
                        (timezone.now() - datetime.timedelta(days=1)).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                    ),
                },
                fields=voting["fields"],
                prefix=prefix,
            )
    else:
        details_form = {"as_ul": ""}

    if nomination_form.is_valid() and details_form.is_valid():
        games = GameListEntry.objects.filter(
            gamelist_id=selected_nomination
        ).select_related("game")

        raw_votes = list(
            CompetitionVote.objects.filter(
                competition=comp, nomination_id=selected_nomination
            ).select_related()
        )

        fields_to_show = details_form.cleaned_data["fields"]

        groupped_votes = {}
        for v in raw_votes:
            groupped_votes.setdefault(
                v.user_id, {"name": v.user.username, "votes": {}}
            )["votes"].setdefault(v.game_id, {})[v.field] = {
                "value": FirstNotNone(v.bool_val, v.text_val, v.int_val),
                "timestamp": v.when,
            }

        fields_order = {y["name"]: x for x, y in enumerate(voting["fields"])}

        votes = []
        for _, x in sorted(groupped_votes.items()):
            vote_per_game = []
            for y in games:
                game_votes = x["votes"].get(y.game.id, {})
                print(game_votes)
                vote_per_game.append([
                    x
                    for key, x in sorted(
                        game_votes.items(),
                        key=lambda z: fields_order.get(z[0], -1),
                    )
                    if key in fields_to_show
                ])
            votes.append({"name": x["name"], "votes": vote_per_game})

        table = {
            "games": [x.game for x in games],
            "votes": votes,
            "showtime": details_form.cleaned_data["showtime"],
            "highlight": details_form.cleaned_data["highlight"],
        }
    else:
        table = {}

    return render(
        request,
        "contest/showvotes.html",
        {
            "nomination_form": nomination_form,
            "details_form": details_form,
            "table": table,
        },
    )
