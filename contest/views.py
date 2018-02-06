from django.shortcuts import render
from .models import Competition, CompetitionURL, CompetitionDocument, GameList
from django.http import Http404
from django.template.loader import render_to_string
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from games.tools import RenderMarkdown, PartitionItems, ComputeGameRating
from games.models import GameURL, GameAuthor
from django.db.models import Count, Max
import json
import datetime
from collections import defaultdict


class CompetitionGameFetcher:
    def __init__(self, comp):
        self.comp = comp
        self.options = json.loads(comp.options)

    def GetCompetitionGamesRaw(self):
        lists = []
        for x in GameList.objects.filter(
                competition=self.comp).order_by('order'):
            ranked = []
            unranked = []
            for y in x.gamelistentry_set.annotate(
                    coms_count=Count('game__gamecomment'),
                    coms_recent=Max(
                        'game__gamecomment__creation_time')).prefetch_related(
                            'game__gamevote_set',
                            'game__gameauthor_set__role',
                            'game__gameauthor_set__author',
                        ).order_by('rank', 'date', 'game__title'):
                if y.rank is None:
                    unranked.append(y)
                else:
                    ranked.append(y)
            if ranked or unranked:
                lists.append({
                    'title': x.title,
                    'unranked': unranked,
                    'ranked': ranked,
                })
        return lists

    def FetchSnippetData(self):
        raw = self.GetCompetitionGamesRaw()
        games = set()
        for x in raw:
            for y in ['unranked', 'ranked']:
                for z in x[y]:
                    if z.game:
                        games.add(z.game_id)

        posters = (GameURL.objects.filter(category__symbolic_id='poster')
                   .filter(game__in=games).select_related('url'))
        screenshots = (
            GameURL.objects.filter(category__symbolic_id='screenshot')
            .filter(game__in=games).select_related('url'))
        authors = GameAuthor.objects.filter(
            game__in=games,
            role__symbolic_id='author').select_related('author')

        g2p = {}
        authors = defaultdict(list)
        for x in posters:
            g2p[x.game_id] = x.GetLocalUrl()
        for x in screenshots:
            if x.game_id not in g2p:
                g2p[x.game_id] = x.GetLocalUrl()
        for x in authors:
            authors[x.game_id].append(x.author.name)

        now = timezone.now()
        for x in raw:
            for y in ['unranked', 'ranked']:
                for z in x[y]:
                    if self.options.get('listtype') == 'parovoz':
                        z.head = self.FormatParovoz(z)
                    else:
                        z.head = self.FormatHead(z)

                    if z.game:
                        g = z.game
                        g.added_age = None
                        g.release_age = None
                        if g.creation_time:
                            g.added_age = (
                                now - g.creation_time).total_seconds()
                        if g.release_date:
                            g.release_age = (
                                now.date() - g.release_date).total_seconds()
                        g.poster = g2p.get(z.game_id)
                        g.authors = ', '.join(authors[g.id])

                        votes = [x.star_rating for x in g.gamevote_set.all()]
                        g.rating = ComputeGameRating(votes)
        return raw

    def FormatHead(self, g):
        if g.rank:
            return {'primary': g.rank, 'secondary': 'место'}

    def FormatParovoz(self, g):
        if g.date:
            end = g.date + datetime.timedelta(days=6)
            return {
                'primary': g.date.strftime('%d.%m'),
                'secondary': end.strftime('— %d.%m')
            }


class SnippetProvider:
    def __init__(self, comp):
        self.fetcher = CompetitionGameFetcher(comp)

    def render_RESULTS(self):
        lists = self.fetcher.FetchSnippetData()
        return render_to_string('contest/rankings.html', {
            'nominations': lists
        })

    def render_PARTICIPANTS(self):
        return self.render_RESULTS()


def list_competitions(request):
    logos = CompetitionURL.objects.filter(category__symbolic_id='logo')
    g2l = {}
    for x in logos:
        g2l.setdefault(x.competition_id, x.GetLocalUrl())

    contests = []
    for x in Competition.objects.order_by('-end_date'):
        contests.append({
            'slug': x.slug,
            'title': x.title,
            'logo': g2l.get(x.id, '/static/default_competition_logo.jpg')
        })
    return render(request, 'contest/index.html', {'contests': contests})


def show_competition(request, slug, doc=''):
    try:
        comp = Competition.objects.get(slug=slug)
        docobj = CompetitionDocument.objects.get(slug=doc, competition=comp)
    except ObjectDoesNotExist:
        raise Http404()

    request.perm.Ensure(docobj.view_perm)

    logos = CompetitionURL.objects.filter(
        category__symbolic_id='logo', competition=comp)
    logo = logos[0].GetLocalUrl() if logos else None

    links = []
    for x in CompetitionDocument.objects.filter(
            competition=comp).order_by('slug'):
        if not request.perm(docobj.view_perm):
            continue
        if x.slug == doc:
            continue
        links.append(x)

    logos, ext_links = PartitionItems(comp.competitionurl_set.all(),
                                      [('logo', )])
    #    for x in CompetitionURL.objects.exclude(category__symbolic_id='logo'):
    #        ext_links.append({'description': x.description

    return render(
        request, 'contest/competition.html', {
            'comp': comp,
            'doc': docobj,
            'markdown': RenderMarkdown(docobj.text, SnippetProvider(comp)),
            'logo': logo,
            'docs': links,
            'links': ext_links,
        })
