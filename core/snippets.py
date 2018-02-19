from .models import Snippet, SnippetPin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.db.models import Max, Count
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from contest.models import (Competition, CompetitionSchedule, CompetitionURL)
from contest.views import CompetitionGameFetcher
from games.models import GameURL, GameComment
from games.search import MakeSearch
from games.tools import (FormatLag, ExtractYoutubeId, FormatDateShort,
                         FormatDate, SnippetFromList, ComputeGameRating,
                         ConcoreNumeral)
from moder.tools import GetPopularGameids
from .models import FeedCache, Game, BlogFeed
import json

COMMENT_SVG = ('M40 4H8C5.79 4 4.02 5.79 4.02 8L4 44l8-8h28c2.21 0 4-1.79 '
               '4-4V8c0-2.21-1.79-4-4-4zm-4 '
               '24H12v-4h24v4zm0-6H12v-4h24v4zm0-6H12v-4h24v4z')

DUCK_SVG = (
    "M 19.29035,48.1475 C 13.97066,47.772958 8.6268257,46.416248 4.0676443,"
    "43.579669 -0.22559692,37.473429 -0.90177434,29.164425 1.7378713,22.261"
    "303 c 0.912833,-2.209144 2.2008281,-4.28308 3.9016505,-5.97271 2.52295"
    "43,-0.543783 4.5847042,1.576241 6.5108472,2.870163 2.090784,1.288093 2"
    ".651662,4.842766 5.587264,3.598886 1.671529,-0.365845 5.119772,0.70017"
    "4 3.012115,-1.724882 C 18.333242,15.857546 20.412124,9.0016116 25.5460"
    "84,6.3300462 30.298555,3.6843118 37.000257,5.366726 39.739609,10.09667"
    "5 c 0.52175,2.791334 3.228344,2.407393 5.365601,2.269148 2.472671,-0.8"
    "07329 3.725461,1.478674 2.999526,3.666324 -0.461961,3.83938 -4.209962,"
    "6.960384 -8.086506,6.495194 -1.900163,1.295996 1.056765,3.886233 0.796"
    "055,5.85315 1.078337,5.783808 -0.504927,12.071817 -4.42526,16.497164 C"
    " 31.11883,47.489003 25.134354,48.446343 19.29035,48.1475 Z m 3.95657,-"
    "2.45312 c 3.942722,-0.207644 7.859319,-1.099422 11.466825,-2.713716 4."
    "545701,-5.169031 5.173958,-13.19339 1.906636,-19.179486 -0.206426,-2.4"
    "44352 2.678069,-3.896286 2.441107,-6.45971 0.718522,-4.977117 -3.56133"
    "6,-10.130085 -8.694893,-9.831471 -4.813755,0.1376475 -8.769018,4.86531"
    "2 -8.126968,9.622078 0.19322,2.46325 1.614649,4.624265 3.324702,6.2925"
    "43 0.724531,3.028451 -3.885728,1.429425 -5.599409,1.668505 -2.535564,-"
    "0.153561 -6.01467,1.630906 -7.209291,-1.559914 C 11.408879,21.546142 9"
    ".5120615,19.811784 7.2479756,18.973258 5.204057,19.122875 4.8437482,21"
    ".99978 3.8982705,23.509932 1.7235858,29.334714 2.394933,36.177482 5.59"
    "89451,41.49073 c 1.1827071,1.202681 2.9654197,1.570947 4.4724739,2.260"
    "109 4.199861,1.531145 8.713083,2.188084 13.175501,1.943541 z m 9.26197"
    ",-30.02567 c -3.494696,-0.740101 -0.579759,-6.3086453 2.096534,-3.8253"
    "34 1.674148,1.450196 0.113448,4.539451 -2.096534,3.825334 z m 9.5843,5"
    ".08429 c 2.941263,-0.661244 4.830406,-3.860715 4.43325,-6.77002 -1.608"
    "051,0.471047 -5.664415,-1.175862 -4.975679,1.358781 0.441952,1.785547 "
    "-0.96043,4.513123 -0.528126,5.575647 0.360493,-0.02728 0.717199,-0.089"
    "91 1.070555,-0.164408 z"
    "")


# Supported annotations:
# added_age
# released_age
# comments
# stars
def GameListSnippet(request,
                    query,
                    sort=None,
                    annotate=['stars', 'comments', 'added_age'],
                    limit_field='added_age',
                    age_field='added_age',
                    limit_val=7 * 60 * 60 * 24,
                    min_count=5,
                    max_count=30):
    s = MakeSearch(request.perm)
    s.UpdateFromQuery(query)

    prefetch_related = ['gameauthor_set__author', 'gameauthor_set__role']
    annotate_query = {}
    for x in annotate:
        if x == 'comments':
            # TODO(crem) take care of deleted comments
            annotate_query['coms_recent'] = Max('gamecomment__creation_time')

    games = s.Search(
        prefetch_related=prefetch_related,
        start=0,
        limit=max_count,
        annotate=annotate_query)

    SnippetFromList(games)

    now = timezone.now()
    for x in games:
        if x.creation_time:
            x.added_age = (now - x.creation_time).total_seconds()
        if x.release_date:
            x.release_age = (now.date() - x.release_date).total_seconds()

    if min_count < len(games) and limit_field:
        res = []
        for x in games:
            if getattr(x, limit_field) is None:
                continue
            if len(res) >= min_count and getattr(x, limit_field) > limit_val:
                break
            res.append(x)
        games = res

    age = None
    if age_field:
        for x in games:
            if not hasattr(x, age_field):
                continue
            at = getattr(x, age_field)
            if at is None:
                continue
            if age is None or at < age:
                age = at

    if sort:
        field = sort
        inv = field[0] == '-'
        if inv:
            field = field[1:]

        def GetKey(obj):
            res = []
            val = getattr(obj, field)
            if val is None:
                res.append(not inv)
                res.append(None)
            else:
                res.append(inv)
                res.append(val)
            return res

        games.sort(key=GetKey, reverse=inv)
    items = []
    for x in games:
        lines = []
        for y in reversed(annotate):
            text = None
            svg = None
            highlighted = False
            if y == 'added_age':
                text = FormatLag(-x.added_age)
                highlighted = x.added_age <= 24 * 60 * 60
            elif y == 'release_age':
                text = FormatLag(-x.release_age)
                highlighted = x.release_age <= 24 * 60 * 60
            elif y == 'comments':
                if x.coms_count:
                    text = '%d' % x.coms_count
                    svg = COMMENT_SVG
                    highlighted = (
                        now - x.coms_recent).total_seconds() < 24 * 60 * 60
            elif y == 'stars':
                if x.rating['avg']:
                    text = x.rating['avg_txt']
                    svg = DUCK_SVG
            styles = ['float-right']
            styles.append('recent-comment' if highlighted else 'comment')
            if text:
                lines.append({'style': styles, 'text': text, 'svg': svg})
        lines.append({'style': 'comment'})
        lines.append({'style': 'strong', 'text': x.title})
        lines.append({'text': ', '.join([y.author.name for y in x.authors])})
        items.append({
            'image': {
                'src': x.poster or '/static/noposter_7355.png',
            },
            'lines': lines,
            'link': reverse('show_game', kwargs={'game_id': x.id})
        })
    return ItemsSnippet(request, items, age)


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
        x.lag = delta
        x.recent_lag = recent
        res.append(x)
        if len(res) == 30:
            break
    return res


def CommentsSnippet(request):
    comments = LastComments(request)
    games = [x.game for x in comments]
    SnippetFromList(games, False)
    if not comments:
        return {}
    items = []
    for x, y in zip(comments, games):
        items.append({
            'image': {
                'src': y.poster or '/static/noposter_7355.png'
            },
            'link': (reverse('show_game', kwargs={'game_id': x.game.id})),
            'lines': [
                {
                    'style': 'float-left',
                    'text': x.GetUsername(),
                },
                {
                    'style': ('recent-comment' if x.recent_lag else 'comment'),
                    'text': (FormatLag(x.lag)),
                },
                {
                    'style': 'strong',
                    'text': (x.game.title),
                },
                {
                    'text': (x.text[:100]),
                },
            ]
        })

    return ItemsSnippet(request, items, -comments[0].lag)


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
            'local_url': x.GetLocalUrl(),
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
    if not urls:
        return {}

    items = []
    for x in urls:
        v = {
            'lines': [
                {
                    'style': ('recent-comment'
                              if -x['lag'] < highlight_secs else 'comment'),
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
                    'link': reverse('show_game', kwargs={'game_id': x['id']})
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
        elif cat in ['poster', 'screenshot']:
            v['image'] = {
                'src': x['local_url'],
                'link': x['url'],
                'newtab': True,
            }
        items.append(v)
    return ItemsSnippet(request, items, -urls[0]['lag'])


def FeedSnippet(request,
                feed_ids,
                highlight_secs=60 * 60 * 24,
                max_secs=7 * 24 * 60 * 60,
                min_count=5,
                max_count=30,
                rest_str=None,
                default_age=7 * 24 * 60 * 60):
    now = timezone.now()
    itemses = []
    items = dict()
    count = 0
    age = default_age
    for x in FeedCache.objects.filter(feed_id__in=feed_ids.keys()).order_by(
            '-date_published')[:max_count]:
        lag = (now - x.date_published).total_seconds()
        if lag < age:
            age = lag
        if lag > max_secs and count >= min_count:
            break
        if x.feed_id not in items:
            n = []
            itemses.append((x.feed_id, n))
            items[x.feed_id] = n
        count += 1
        lines = [{
            'style': ('recent-comment'
                      if lag <= highlight_secs else 'comment'),
            'text': (FormatLag(-lag)),
        }, {
            'style': 'strong',
            'text': (x.title),
        }]
        if feed_ids[x.feed_id].get('show_author', True) and x.authors:
            lines.append({'text': (x.authors)})

        items[x.feed_id].append({
            'link': (x.url),
            'newtab': (True),
            'lines': lines,
        })
    res = []
    for k, v in itemses:
        if len(feed_ids) != 1:
            res.append({
                'style': 'subheader',
                'text': feed_ids[k].get('title'),
                'newtab': True,
                'link': feed_ids[k].get('link')
            })
        res.extend(v)
    if len(feed_ids) != 1 and rest_str:
        not_shown = set(feed_ids.keys()) - set(items.keys())
        if not_shown:
            res.append({
                'style': 'subheader',
                'text': rest_str,
            })
            for x in sorted(not_shown):
                res.append({
                    'link': feed_ids[x].get('link'),
                    'newtab': True,
                    'lines': [{
                        'text': feed_ids[x].get('title'),
                    }]
                })
    return ItemsSnippet(request, res, age)


def ThisDayInHistorySnippet(request, default_age=24 * 60 * 60):
    now = timezone.now()
    items = []
    games = Game.objects.filter(
        release_date__month=now.month,
        release_date__day=now.day,
        release_date__year__lt=now.year).order_by(
            '-release_date').prefetch_related('gameauthor_set__author',
                                              'gameauthor_set__role')
    if not games:
        return None
    SnippetFromList(games)

    items.append({
        'style': 'subheader',
        'text': "Игры, выпущенные %s" % FormatDateShort(now),
    })
    for x in games:
        ago = now.year - x.release_date.year
        lines = []
        lines.append({
            'style': ('comment'),
            'text':
                "%d год (%s назад)" % (x.release_date.year,
                                       ConcoreNumeral(ago, 'год,года,лет')),
        })
        lines.append({'style': 'strong', 'text': x.title})
        lines.append({'text': ', '.join([y.author.name for y in x.authors])})
        items.append({
            'image': {
                'src': x.poster or '/static/noposter_7355.png',
            },
            'lines': (lines),
            'link': (reverse('show_game', kwargs={'game_id': x.id})),
        })
    return ItemsSnippet(request, items, default_age)


def PopularGamesSnippet(
        request,
        count=5,
        default_age=22 * 60 * 60,
        daily_decay=3,
        anonymous_factor=0.3,
        annotate=['stars', 'comments', 'release_age'],
):
    ids = next(
        zip(*GetPopularGameids(
            daily_decay=daily_decay, anonymous_factor=anonymous_factor)
            .most_common(count)))
    games = Game.objects.filter(id__in=ids).annotate(
        coms_count=Count('gamecomment'),
        coms_recent=Max('gamecomment__creation_time')).prefetch_related(
            'gamevote_set')
    SnippetFromList(games)
    id_to_game = {x.id: x for x in games}
    now = timezone.now()

    for x in games:
        if x.creation_time:
            x.added_age = (now - x.creation_time).total_seconds()
        if x.release_date:
            x.release_age = (now.date() - x.release_date).total_seconds()
        votes = [y.star_rating for y in x.gamevote_set.all()]
        x.rating = ComputeGameRating(votes)

    items = []
    for i in ids:
        lines = []
        x = id_to_game[i]
        for y in reversed(annotate):
            text = None
            svg = None
            highlighted = False
            if y == 'added_age':
                text = FormatLag(-x.added_age)
                highlighted = x.added_age <= 24 * 60 * 60
            elif y == 'release_age':
                if (x.release_date):
                    text = FormatLag(-x.release_age)
                    highlighted = x.release_age <= 24 * 60 * 60
            elif y == 'comments':
                if x.coms_count:
                    text = '%d' % x.coms_count
                    svg = COMMENT_SVG
                    highlighted = (
                        now - x.coms_recent).total_seconds() < 24 * 60 * 60
            elif y == 'stars':
                if x.rating['avg']:
                    text = x.rating['avg_txt']
                    svg = DUCK_SVG
            styles = ['float-right']
            styles.append('recent-comment' if highlighted else 'comment')
            if text:
                lines.append({'style': styles, 'text': text, 'svg': svg})
        lines.append({'style': 'comment'})
        lines.append({'style': 'strong', 'text': x.title})
        lines.append({'text': ', '.join([y.author.name for y in x.authors])})
        items.append({
            'image': {
                'src': x.poster or '/static/noposter_7355.png',
            },
            'lines': lines,
            'link': reverse('show_game', kwargs={'game_id': x.id})
        })
    return ItemsSnippet(request, items, default_age)


def RawHtmlSnippet(request, raw_html, default_age=10 * 24 * 60 * 60):
    return {'content': raw_html, 'age': default_age}


def BlogSnippet(request,
                highlight_secs=60 * 60 * 24,
                max_secs=7 * 24 * 60 * 60,
                min_count=5,
                max_count=30,
                rest_str="Остальные блоги",
                default_age=7 * 24 * 60 * 60,
                prefix=''):
    feed_ids = dict()
    for x in BlogFeed.objects.all():
        if not x.feed_id.startswith(prefix):
            continue
        feed_ids[x.feed_id] = {
            'title': x.title,
            'link': x.url,
            'show_author': x.show_author
        }
    return FeedSnippet(
        request=request,
        feed_ids=feed_ids,
        highlight_secs=highlight_secs,
        max_secs=max_secs,
        min_count=min_count,
        max_count=max_count,
        rest_str=rest_str,
        default_age=default_age)


def ContestSnippet(
        request,
        slug,
        show_games=True,
        show_schedule=True,
        show_links=[
            'official_page',
            'other_site',
            'forum',
        ],
        annotate=['stars', 'comments', 'added_age'],
        age=14 * 24 * 60 * 60,
):
    try:
        comp = Competition.objects.get(slug=slug)
    except Competition.DoesNotExist:
        return {}
    # TODO(crem) Check permisions when there is support for them.
    #if not request.perm(comp.view_perm):
    #    return {}

    res = []
    if show_schedule:
        items = CompetitionSchedule.objects.filter(
            competition=comp, show=True).order_by('when')
        if items:
            res.append({
                'style': 'subheader',
                'text': 'Расписание',
            })
            now = timezone.now()
            for x in items:
                res.append({
                    'lines': [
                        {
                            'text':
                                FormatDate(x.when),
                            'style': (['float-right'] +
                                      (['dimmed'] if x.when < now else [])),
                        },
                        {
                            'text': x.title,
                            'style': 'strong'
                        },
                    ]
                })
    if show_links:
        links = CompetitionURL.objects.filter(
            category__symbolic_id__in=show_links, competition=comp)
        if links:
            res.append({
                'style': 'subheader',
                'text': 'Ссылки',
            })
            for x in links:
                res.append({
                    'lines': [{
                        'text': x.description,
                        'link': x.GetRemoteUrl(),
                        'newtab': True,
                    }]
                })
    if show_games:
        games = CompetitionGameFetcher(comp).FetchSnippetData()
        if games:
            now = timezone.now()
            for entry in games:
                res.append({
                    'style': 'subheader',
                    'text': entry['title'] or 'Участники',
                })
                for z in entry['ranked'] + entry['unranked']:
                    lines = []
                    item = {}
                    item['lines'] = lines
                    item['head'] = z.head if hasattr(z, 'head') else None
                    if z.game:
                        x = z.game
                        for y in reversed(annotate):
                            text = None
                            svg = None
                            highlighted = False
                            if y == 'added_age':
                                text = FormatLag(-x.added_age)
                                highlighted = x.added_age <= 24 * 60 * 60
                            elif y == 'release_age':
                                text = FormatLag(-x.release_date)
                                highlighted = x.release_date <= 24 * 60 * 60
                            elif y == 'comments':
                                if z.coms_count:
                                    text = '%d' % z.coms_count
                                    svg = COMMENT_SVG
                                    highlighted = (
                                        now - z.coms_recent
                                    ).total_seconds() < 24 * 60 * 60
                            elif y == 'stars':
                                if x.rating['avg']:
                                    text = x.rating['avg_txt']
                                    svg = DUCK_SVG
                            styles = ['float-right']
                            styles.append('recent-comment'
                                          if highlighted else 'comment')
                            if text:
                                lines.append({
                                    'style': styles,
                                    'text': text,
                                    'svg': svg
                                })
                        if not z.comment:
                            lines.append({'style': 'comment'})
                        lines.append({'style': 'strong', 'text': x.title})
                        lines.append({'text': x.authors})
                        if z.comment:
                            lines.append({'text': z.comment, 'style': 'weak'})
                        item['image'] = {
                            'src': x.poster or '/static/noposter_7355.png',
                        }
                        item['link'] = reverse(
                            'show_game', kwargs={'game_id': x.id})

                    else:
                        lines.append({})
                        if z.comment:
                            lines.append({'text': z.comment})
                        else:
                            lines.append({})
                        lines.append({})

                    res.append(item)

    return ItemsSnippet(request, res, age)


def MultipartSnippet(request, parts, default_age=0, force_age=None):
    age = None
    content = ''
    for x in parts:
        method = x['method']
        del x['method']
        v = globals()[method](request, **x)
        if not v:
            continue
        if v.get('age') is not None and (age is None or v['age'] < age):
            age = v['age']
        content += v['content']

    if age is None:
        age = default_age
    if force_age is not None:
        age = force_age
    return {'age': age, 'content': content}


def ItemsSnippet(request, items, age=None):
    for i in items:
        for l in i.get('lines', []):
            if isinstance(l.get('style'), str):
                l['style'] = [l['style']]

    res = {'content': render_to_string('core/snippet.html', {'items': items})}
    if age is not None:
        res['age'] = age
    return res


###############################################################################


def RenderSnippetContent(request, snippet):
    content_json = json.loads(snippet.content_json)

    if 'method' in content_json:
        method = content_json['method']
        del content_json['method']
        return globals()[method](request, **content_json)
    else:
        return {}


def AsyncSnippet(request):
    id = request.GET.get('s')
    snippet = Snippet.objects.get(pk=id)
    if not request.perm(snippet.view_perm):
        raise PermissionDenied()
    x = RenderSnippetContent(request, snippet)
    return HttpResponse(x.get('content', ''))


def SnippetVisible(request, snippet):
    now = timezone.now()
    if not request.perm(snippet.view_perm):
        return False
    if snippet.show_start and snippet.show_start > now:
        return False
    if snippet.show_end and snippet.show_end < now:
        return False
    return True


def RenderSnippets(request):
    snippets = []
    for x in Snippet.objects.order_by('order'):
        if not SnippetVisible(request, x):
            continue

        async_id = None
        style = json.loads(x.style_json)
        if x.is_async:
            async_id = x.id
            data = {
                'content': '',
                'age': style.get('age', 14 * 24 * 60 * 60),
            }
        else:
            data = RenderSnippetContent(request, x)
            if not data:
                continue

        box_style = "grid-box-%s" % style['color'] if 'color' in style else ''

        icons = {}
        snippets.append({
            'id': x.id,
            'title': x.title,
            'url': x.url,
            'style': style,
            'box_style': box_style,
            'async_snippet_id': async_id,
            'content': data.get('content'),
            'age': data.get('age', 365 * 24 * 60 * 60),
            'order': x.order,
            'icons': icons,
        })

    if request.user.is_authenticated:
        hids = set()
        pins = dict()
        for x in SnippetPin.objects.filter(user=request.user):
            if x.is_hidden:
                hids.add(x.snippet_id)
            else:
                pins[x.snippet_id] = x.order
        pref = []
        snip = []
        hid = []
        for x in snippets:
            x['icons']['hide'] = True
            if x['id'] in hids:
                hid.append(x)
            elif x['id'] in pins:
                x['order'] = -pins[x['id']]
                x['icons']['star_on'] = True
                pref.append(x)
            else:
                x['icons']['star_off'] = True
                snip.append(x)

        pref.sort(key=lambda y: y['order'])
        snip.sort(key=lambda y: (y['order'], y['age']))
        snippets = pref + snip
        if hid:
            hid.sort(key=lambda y: (y['order'], y['age']))
            items = []
            for x in hid:
                lines = []
                if x.get('age') is not None and x['style'].get('show_age'):
                    lines.append({
                        'style': ['float-right'],
                        'text': FormatLag(-x['age'])
                    })
                    lines[-1]['style'].append('recent-comment' if x['age'] <=
                                              60 * 60 * 24 else 'comment')
                lines.append({
                    'text': x['title'],
                })
                items.append({
                    'link': reverse('forget_snippet', kwargs={'id': x['id']}),
                    'lines': lines,
                })
            snippets.append({
                'title': ('Скрытые карточки'),
                'box_style': {},
                'content': (ItemsSnippet(request, items)['content']),
                'icons': {},
            })

    else:
        snippets.sort(key=lambda y: (y['order'], y['age']))

    return render_to_string('core/snippets.html', {'snippets': snippets})


@never_cache
def ForgetSnippet(request, id):
    if request.user.is_authenticated:
        SnippetPin.objects.filter(snippet_id=id, user=request.user.id).delete()

    return redirect('/')


@never_cache
def PinSnippet(request, id):
    if request.user.is_authenticated:
        y = Snippet.objects.get(pk=id)
        if not SnippetVisible(request, y):
            raise PermissionDenied()
        x = SnippetPin.objects.filter(
            user=request.user.id, order__isnull=False).order_by('-order')[:1]
        print(x)
        order = (x[0].order + 1) if x else 0
        SnippetPin.objects.update_or_create(
            snippet_id=id,
            user=request.user,
            defaults={
                'is_hidden': False,
                'order': order
            })
    return redirect('/')


@never_cache
def HideSnippet(request, id):
    if request.user.is_authenticated:
        y = Snippet.objects.get(pk=id)
        if not SnippetVisible(request, y):
            raise PermissionDenied()
        SnippetPin.objects.update_or_create(
            snippet_id=id,
            user=request.user,
            defaults={
                'is_hidden': True,
                'order': None
            })
    return redirect('/')
