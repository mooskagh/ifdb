from django.shortcuts import render
from .models import Competition, CompetitionURL, CompetitionDocument, GameList
from django.http import Http404
from django.template.loader import render_to_string
from django.core.exceptions import ObjectDoesNotExist
from games.tools import RenderMarkdown, PartitionItems
from games.models import GameURL


def FetchSnippetData(d):
    games = set()
    for x in d:
        for y in ['unranked', 'ranked']:
            for z in x[y]:
                if z.game:
                    games.add(z.game_id)

    posters = (GameURL.objects.filter(category__symbolic_id='poster').filter(
        game__in=games).select_related('url'))
    screenshots = (GameURL.objects.filter(category__symbolic_id='screenshot')
                   .filter(game__in=games).select_related('url'))

    g2p = {}
    for x in posters:
        g2p[x.game_id] = x.GetLocalUrl()
    for x in screenshots:
        if x.game_id not in g2p:
            g2p[x.game_id] = x.GetLocalUrl()

    for x in d:
        for y in ['unranked', 'ranked']:
            for z in x[y]:
                if z.game:
                    z.game.poster = g2p.get(z.game_id, '/static/noposter.png')
                    z.game.authors = ', '.join([
                        k.author.name for k in z.game.gameauthor_set.all()
                        if k.role.symbolic_id == 'author'
                    ])


class SnippetProvider:
    def __init__(self, comp):
        self.comp = comp

    def FormatHead(self, g):
        if g.rank:
            return {'primary': g.rank, 'secondary': 'место'}

    def render_RESULTS(self):
        lists = []
        for x in GameList.objects.filter(
                competition=self.comp).order_by('order'):
            ranked = []
            unranked = []
            for y in x.gamelistentry_set.order_by('rank', 'datetime',
                                                  'game__title'):
                y.head = self.FormatHead(y)
                if y.rank is None:
                    unranked.append(y)
                else:
                    ranked.append(y)
            lists.append({
                'title': x.title,
                'unranked': unranked,
                'ranked': ranked,
            })
        FetchSnippetData(lists)
        return render_to_string('contest/rankings.html', {
            'nominations': lists
        })


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
