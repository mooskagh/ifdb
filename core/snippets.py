from .models import Snippet
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from games.models import GameURL, GameComment
from games.search import GameListFromSearch
from games.tools import FormatLag, ExtractYoutubeId, FormatDateShort
from .models import FeedCache, Game
import datetime
import json


def GameListSnippet(request,
                    query,
                    reltime_field=None,
                    highlight_secs=60 * 60 * 24,
                    max_secs=60 * 60 * 24 * 7,
                    min_count=5,
                    max_count=30):
    games = GameListFromSearch(request, query, reltime_field, max_secs,
                               min_count, max_count)
    items = []
    for x in games:
        lines = []
        if 'lag' in x:
            lines.append({
                'style': ('recent-comment'
                          if x['lag'] > highlight_secs else 'comment'),
                'text': (FormatLag(x['lag'])),
            })
        lines.append({'style': 'strong', 'text': x['title']})
        lines.append({
            'text': ', '.join([y.author.name for y in x['authors']])
        })
        items.append({
            'image': {
                'src': x['poster'] or '/static/noposter.png',
            },
            'lines': lines,
            'link': reverse('show_game', kwargs={
                'game_id': x['id']
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


def LastUrlCat(request, cat, max_secs, min_count, max_count):
    urls = GameURL.objects.select_related().filter(
        category__symbolic_id=cat).order_by('-url__creation_date')[:max_count]

    res = []
    for x in urls:
        delta = (x.url.creation_date - timezone.now()).total_seconds()
        if -delta >= max_secs and len(res) >= min_count:
            break
        res.append({
            'lag': delta,
            'url': x.url.original_url,
            'game': x.game.title,
            'id': x.game.id,
            'desc': x.description,
        })
    return res


def LastUrlCatSnippet(request,
                      cat,
                      highlight_secs=60 * 60 * 24,
                      max_secs=7 * 24 * 60 * 60,
                      min_count=5,
                      max_count=30):
    urls = LastUrlCat(request, cat, max_secs, min_count, max_count)
    items = []
    for x in urls:
        v = {
            'lines': [
                {
                    'style': ('recent-comment'
                              if x['lag'] > highlight_secs else 'comment'),
                    'text': (FormatLag(x['lag'])),
                },
                {
                    'style': 'strong',
                    'text': (x['desc']),
                    'link': x['url'],
                    'newtab': True,
                },
                {
                    'text': (x['game']),
                    'link': reverse('show_game', kwargs={
                        'game_id': x['id']
                    })
                },
            ]
        }
        if cat == 'video':
            idd = ExtractYoutubeId(x['url'])
            if idd:
                v['image'] = {
                    'src': 'https://img.youtube.com/vi/%s/default.jpg' % idd,
                    'link': x['url'],
                    'newtab': True,
                }
        items.append(v)
    return render_to_string('core/snippet.html', {'items': items})


def FeedSnippet(request,
                feed_ids,
                highlight_secs=60 * 60 * 24,
                max_secs=7 * 24 * 60 * 60,
                min_count=5,
                max_count=30):
    now = timezone.now()
    items = []
    for x in FeedCache.objects.filter(
            feed_id__in=feed_ids).order_by('-date_published')[:max_count]:
        lag = (now - x.date_published).total_seconds()
        if lag > max_secs and len(items) >= min_count:
            break
        items.append({
            'link': (x.url),
            'newtab': (True),
            'lines': [
                {
                    'style': ('recent-comment'
                              if lag <= highlight_secs else 'comment'),
                    'text': (FormatLag(-lag)),
                },
                {
                    'style': 'strong',
                    'text': (x.title),
                },
                {
                    'text': (x.authors),
                },
            ]
        })
    return render_to_string('core/snippet.html', {'items': items})


def ThisDayInHistorySnippet(request):
    now = timezone.now()
    items = []
    for daytitle, datedelta in [('Вчера', -1), ('Сегодня', 0), ('Завтра', 1)]:
        t = now + datetime.timedelta(days=datedelta)
        games = Game.objects.filter(
            release_date__month=t.month, release_date__day=t.day).order_by(
                '-release_date').prefetch_related('gameauthor_set__author',
                                                  'gameauthor_set__role')
        if not games:
            continue
        posters = (GameURL.objects.filter(category__symbolic_id='poster')
                   .filter(game__in=games).select_related('url'))

        g2p = {}
        for x in posters:
            g2p[x.game_id] = x.GetLocalUrl()

        for x in games:
            x.poster = g2p.get(x.id)
            x.authors = [
                x for x in x.gameauthor_set.all()
                if x.role.symbolic_id == 'author'
            ]

        items.append({
            'style': 'subheader',
            'text': "%s, %s" % (daytitle, FormatDateShort(t))
        })
        for x in games:
            lines = []
            lines.append({
                'style': ('comment'),
                'text': "%d год" % x.release_date.year,
            })
            lines.append({'style': 'strong', 'text': x.title})
            lines.append({
                'text': ', '.join([y.author.name for y in x.authors])
            })
            items.append({
                'image': {
                    'src': x.poster or '/static/noposter.png',
                },
                'lines': (lines),
                'link': (reverse('show_game', kwargs={
                    'game_id': x.id
                })),
            })
    return render_to_string('core/snippet.html', {'items': items})


###############################################################################


def RenderSnippetContent(request, snippet):
    content_json = json.loads(snippet.content_json)

    if 'method' in content_json:
        method = content_json['method']
        del content_json['method']
        return globals()[method](request, **content_json)
    else:
        return None


def AsyncSnippet(request):
    id = request.GET.get('s')
    snippet = Snippet.objects.get(pk=id)
    if not request.perm(snippet.view_perm):
        raise PermissionDenied()
    x = RenderSnippetContent(request, snippet)
    return HttpResponse(x)


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

        async_id = None
        content = None
        if x.is_async:
            async_id = x.id
        else:
            content = RenderSnippetContent(request, x)
            if not content:
                continue

        style = json.loads(x.style_json)
        box_style = "grid-box-%s" % style['color'] if 'color' in style else ''

        snippets.append({
            'title': x.title,
            'url': x.url,
            'box_style': box_style,
            'async_snippet_id': async_id,
            'content': content,
        })

    return render_to_string('core/snippets.html', {'snippets': snippets})
