from .models import Snippet
from django.template.loader import render_to_string
from django.utils import timezone
from games.models import GameURL, GameComment
from games.search import MakeSearch
from games.tools import FormatLag, ExtractYoutubeId
from django.urls import reverse
import json


def GameListFromSearch(request, query, reltime_field=None):
    s = MakeSearch(request.perm)
    s.UpdateFromQuery(query)
    games = s.Search(
        prefetch_related=['gameauthor_set__author', 'gameauthor_set__role'],
        start=0,
        limit=30)

    posters = (GameURL.objects.filter(category__symbolic_id='poster').filter(
        game__in=games).select_related('url'))

    g2p = {}
    for x in posters:
        g2p[x.game_id] = x.GetLocalUrl()

    for x in games:
        x.poster = g2p.get(x.id)
        x.authors = [
            x for x in x.gameauthor_set.all() if x.role.symbolic_id == 'author'
        ]

    total_recent = 0
    if reltime_field:
        for x in games:
            delta = (
                getattr(x, reltime_field) - timezone.now()).total_seconds()
            x.recent_lag = delta > -60 * 60 * 24
            if delta > -3 * 60 * 60 * 24:
                total_recent += 1
            x.lag = FormatLag(delta)
    if total_recent < 5:
        total_recent = 5
    return games[:total_recent]


def GameListSnippet(request, query, reltime_field=None):
    games = GameListFromSearch(request, query, reltime_field)
    items = []
    for x in games:
        lines = []
        if hasattr(x, 'lag'):
            lines.append({
                'style': ('recent-comment' if x.recent_lag else 'comment'),
                'text': (x.lag),
            })
        lines.append({'style': 'strong', 'text': x.title})
        lines.append({'text': ', '.join([y.author.name for y in x.authors])})
        items.append({
            'image': x.poster or '/static/noposter.png',
            'lines': lines,
            'link': reverse('show_game', kwargs={
                'game_id': x.id
            }),
        })
    return render_to_string('core/snippet.html', {'items': items})


def LastComments(request):
    games = set()
    # TODO Game permissions!
    comments = GameComment.objects.select_related().filter(
        is_deleted=False).order_by('-creation_time')[:300]
    res = []
    for x in comments:
        if x.game.id in games:
            continue
        games.add(x.game.id)
        delta = (x.creation_time - timezone.now()).total_seconds()
        recent = -delta < 60 * 60 * 24
        if not recent and len(res) >= 5:
            break
        x.lag = FormatLag(delta)
        x.recent_lag = recent
        res.append(x)
        if len(res) == 30:
            break
    return res


def CommentsSnippet(request):
    comments = LastComments(request)
    items = []
    for x in comments:
        items.append({
            'link': (reverse('show_game', kwargs={
                'game_id': x.game.id
            })),
            'lines': [
                {
                    'style': 'float-right',
                    'text': (x.user.username if x.user else 'Анонимоўс'),
                },
                {
                    'style': ('recent-comment' if x.recent_lag else 'comment'),
                    'text': (x.lag),
                },
                {
                    'style': 'strong',
                    'text': (x.subject or '...'),
                },
                {
                    'text': (x.game.title),
                },
            ]
        })
    return render_to_string('core/snippet.html', {'items': items})


def LastUrlCat(request, cat):
    games = set()
    urls = GameURL.objects.select_related().filter(
        category__symbolic_id=cat).order_by('-url__creation_date')[:50]

    res = []
    for x in urls:
        if x.game.id in games:
            continue
        games.add(x.game.id)
        delta = (x.url.creation_date - timezone.now()).total_seconds()
        recent = -delta < 60 * 60 * 24
        if -delta >= 3 * 60 * 60 * 24 and len(res) >= 5:
            break
        res.append({
            'lag': FormatLag(delta),
            'recent_lag': recent,
            'url': x.url.original_url,
            'game': x.game.title,
            'id': x.game.id,
            'desc': x.description,
        })
        if len(res) == 30:
            break
    return res


def LastUrlCatSnippet(request, cat):
    urls = LastUrlCat(request, cat)
    items = []
    for x in urls:
        v = {
            'link': (reverse('show_game', kwargs={
                'game_id': x['id']
            })),
            'lines': [
                {
                    'style': ('recent-comment'
                              if x['recent_lag'] else 'comment'),
                    'text': (x['lag']),
                },
                {
                    'style': 'strong',
                    'text': (x['game']),
                },
                {
                    'text': (x['desc']),
                },
            ]
        }
        if cat == 'video':
            idd = ExtractYoutubeId(x['url'])
            if idd:
                v['image'] = 'https://img.youtube.com/vi/%s/default.jpg' % idd
        items.append(v)
    return render_to_string('core/snippet.html', {'items': items})


def RenderSnippets(request):
    snippets = []
    now = timezone.now()
    for x in Snippet.objects.order_by('order'):
        if not request.perm(x.view_perm):
            continue
        if x.show_start and x.show_start > now:
            continue
        if x.show_end and x.show_end < now:
            continue
        style = json.loads(x.style_json)
        content_json = json.loads(x.content_json)

        box_style = "grid-box-%s" % style['color'] if 'color' in style else ''

        if 'method' in content_json:
            method = content_json['method']
            del content_json['method']
            content = globals()[method](request, **content_json)
        else:
            content = ''

        snippets.append({
            'title': x.title,
            'box_style': box_style,
            'content': content,
        })

    return render_to_string('core/snippets.html', {'snippets': snippets})
