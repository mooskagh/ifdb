import json
from logging import getLogger
import os.path
import timeit
from .game_details import GameDetailsBuilder, StarsFromRating
from .importer import Import
from .models import (GameURL, GameComment, Game, GameVote, InterpretedGameUrl,
                     URL, GameTag, GameAuthorRole, PersonalityAlias,
                     GameTagCategory, GameURLCategory, GameAuthor, Personality,
                     PersonalityURLCategory, PersonalityUrl)
from .search import MakeSearch, MakeAuthorSearch
from .tools import (FormatLag, ExtractYoutubeId, RenderMarkdown)
from .updater import UpdateGame, Importer2Json
from django import forms
from django.db import models
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousOperation
from django.http import Http404
from django.http.response import JsonResponse
from django.shortcuts import render, redirect
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from ifdb.permissioner import perm_required

PERM_ADD_GAME = '@auth'  # Also for file upload, game import, vote
logger = getLogger('web')


def SnippetFromList(games):
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
    return games


def SnippetFromSearchForIndex(request, query, prefetch=[]):
    s = MakeSearch(request.perm)
    s.UpdateFromQuery(query)
    games = s.Search(
        prefetch_related=[
            'gameauthor_set__author', 'gameauthor_set__role', *prefetch
        ],
        start=0,
        limit=20)[:5]
    return SnippetFromList(games)


def LastComments(request):
    games = set()
    # TODO Game permissions!
    comments = GameComment.objects.select_related().order_by(
        '-creation_time')[:100]
    res = []
    for x in comments:
        if x.game.id in games:
            continue
        games.add(x.game.id)
        res.append({
            'lag':
            FormatLag((x.creation_time - timezone.now()).total_seconds()),
            'username':
            x.user,
            'game':
            x.game.title,
            'id':
            x.game.id,
            'subject':
            x.subject or '...',
        })
        if len(res) == 4:
            break
    return res


def LastUrlCat(request, cat, limit):
    games = set()
    urls = GameURL.objects.select_related().filter(
        category__symbolic_id=cat).order_by('-url__creation_date')[:30]

    res = []
    for x in urls:
        if x.game.id in games:
            continue
        games.add(x.game.id)
        res.append({
            'lag':
            FormatLag((x.url.creation_date - timezone.now()).total_seconds()),
            'url':
            x.url.original_url,
            'game':
            x.game.title,
            'id':
            x.game.id,
            'desc':
            x.description,
        })
        if len(res) == limit:
            break
    return res


def index(request):
    res = {}
    res['lastx'] = SnippetFromSearchForIndex(request, '00')
    for x in res['lastx']:
        x.lag = FormatLag((x.creation_time - timezone.now()).total_seconds())
    res['best'] = SnippetFromSearchForIndex(request, '04')
    res['comments'] = LastComments(request)
    res['videos'] = LastUrlCat(request, 'video', 5)
    for x in res['videos']:
        idd = ExtractYoutubeId(x['url'])
        if idd:
            x['thumb'] = 'https://img.youtube.com/vi/%s/default.jpg' % idd
    res['reviews'] = LastUrlCat(request, 'review', 4)

    return render(request, 'games/index.html', res)


@ensure_csrf_cookie
@login_required
@perm_required(PERM_ADD_GAME)
def add_game(request):
    return render(request, 'games/edit.html', {})


@ensure_csrf_cookie
@login_required
def edit_game(request, game_id):
    game = Game.objects.get(id=game_id)
    request.perm.Ensure(game.edit_perm)
    return render(request, 'games/edit.html', {'game_id': game.id})


def store_game(request):
    if request.method != 'POST':
        return render(request, 'games/error.html',
                      {'message': 'Что-то не так!' + ' (1)'})
    j = json.loads(request.POST.get('json'))

    if not j['title']:
        return render(request, 'games/error.html',
                      {'message': 'У игры должно быть название.'})

    id = UpdateGame(request, j)
    return redirect(reverse('show_game', kwargs={'game_id': id}))


@perm_required(PERM_ADD_GAME)
def vote_game(request):
    if request.method != 'POST':
        return render(request, 'games/error.html',
                      {'message': 'Что-то не так!' + ' (2)'})
    game = Game.objects.get(id=int(request.POST.get('game_id')))

    try:
        obj = GameVote.objects.get(game=game, user=request.user)
        obj.edit_time = timezone.now()
    except GameVote.DoesNotExist:
        obj = GameVote()
        obj.game = game
        obj.user = request.user
        obj.creation_time = timezone.now()

    obj.game_finished = bool(request.POST.get('finished', None))
    obj.edit_time = timezone.now()
    obj.play_time_mins = (
        int(request.POST.get('hours')) * 60 + int(request.POST.get('minutes')))
    obj.star_rating = int(request.POST.get('score'))
    obj.save()

    return redirect(reverse('show_game', kwargs={'game_id': game.id}))


def comment_game(request):
    if request.method != 'POST':
        return render(request, 'games/error.html',
                      {'message': 'Что-то не так!' + ' (3)'})
    game = Game.objects.get(id=int(request.POST.get('game_id')))
    request.perm.Ensure(game.comment_perm)

    comment = GameComment()
    comment.game = game
    comment.user = request.user
    comment.parent_id = request.POST.get('parent', None)
    comment.creation_time = timezone.now()
    comment.subject = request.POST.get('subject', None) or None
    comment.text = request.POST.get('text', None)
    comment.save()

    return redirect(reverse('show_game', kwargs={'game_id': game.id}))


def show_game(request, game_id):
    try:
        g = GameDetailsBuilder(game_id, request)
        return render(request, 'games/game.html', g.GetGameDict())
    except Game.DoesNotExist:
        raise Http404()


def show_author(request, author_id):
    try:
        a = Personality.objects.get(pk=author_id)
        res = {'name': a.name, 'aliases': [], 'links': []}
        for x in PersonalityAlias.objects.filter(personality=a).annotate(
                games=Count('gameauthor')).order_by('-games'):
            if x.name == a.name:
                continue
            if x.games == 0:
                break
            res['aliases'].append(x.name)
        if a.bio:
            res['bio'] = RenderMarkdown(a.bio)

        urls = {}
        cats = []
        for x in a.personalityurl_set.all():
            category = x.category
            if category in urls:
                urls[category].append(x)
            else:
                cats.append(category)
                urls[category] = [x]
        for r in cats:
            res['links'].append({'category': r, 'items': urls[r]})

        games = dict()

        for g in GameAuthor.objects.filter(
                author__personality=author_id).select_related():
            gs = games.setdefault(g.role, [])
            gs.append(g.game)

        res['games'] = []
        for role in sorted(games.keys(), key=lambda x: x.order):
            res['games'].append({
                'role': (role.title),
                'games': (SnippetFromList(
                    sorted(
                        games[role],
                        key=lambda x: x.creation_time,
                        reverse=True))),
            })

        return render(request, 'games/author.html', res)
    except Personality.DoesNotExist:
        raise Http404


def list_games(request):
    s = MakeSearch(request.perm)
    query = request.GET.get('q', '')
    s.UpdateFromQuery(query)

    return render(request, 'games/search.html', s.ProduceBits())


def list_authors(request):
    s = MakeAuthorSearch(request.perm)
    query = request.GET.get('q', '')
    s.UpdateFromQuery(query)
    return render(request, 'games/authors.html', s.ProduceBits())


class ChoiceField(forms.ChoiceField):
    def bound_data(self, data, initial):
        return data


class NullBooleanField(forms.NullBooleanField):
    def bound_data(self, data, initial):
        return data


class UrqwInterpreterForm(forms.Form):
    does_work = NullBooleanField(label="Работоспособность игры")
    variant = ChoiceField(
        label="Вариант URQ",
        required=False,
        choices=[
            (None, "Без специальных правил"),
            ('ripurq', "Rip URQ 1.4"),
            ('dosurq', "Dos URQ 1.35"),
        ])


def store_interpreter_params(request, gameurl_id):
    try:
        u = InterpretedGameUrl.objects.get(pk=gameurl_id)
    except GameURL.DoesNotExist:
        raise Http404()

    request.perm.Ensure(u.original.game.edit_perm)
    form = UrqwInterpreterForm(request.POST)

    if form.is_valid():
        u.is_playable = form.cleaned_data['does_work']
        j = json.loads(u.configuration_json)
        j['variant'] = form.cleaned_data['variant']
        u.configuration_json = json.dumps(j)
        u.save()

        return redirect(
            reverse('play_in_interpreter', kwargs={'gameurl_id': gameurl_id}))
    raise SuspiciousOperation


def play_in_interpreter(request, gameurl_id):
    game = None
    try:
        o_u = GameURL.objects.get(pk=gameurl_id)
        game = o_u.game
    except GameURL.DoesNotExist:
        raise Http404()

    if o_u.category.symbolic_id != 'play_in_interpreter':
        raise Http404()

    request.perm.Ensure(o_u.game.view_perm)
    gameinfo = GameDetailsBuilder(o_u.game.id, request).GetGameDict()

    res = {**gameinfo}

    try:
        res['data'] = data = InterpretedGameUrl.objects.get(pk=gameurl_id)
        res['format'] = os.path.splitext(data.recoded_filename
                                         or o_u.url.local_filename)[1].lower()
        res['conf'] = json.loads(data.configuration_json)

        form = UrqwInterpreterForm({
            'does_work': data.is_playable,
            'variant': res['conf']['variant']
        })

        res['can_edit'] = request.perm(game.edit_perm)
        if not res['can_edit']:
            for x in form.fields:
                form.fields[x].disabled = True

        res['form'] = form.as_table()

    except InterpretedGameUrl.DoesNotExist:
        res['format'] = 'error'
        res['data'] = (
            "Сервер ещё не подготовил эту игру к запуску. Попробуйте завтра.")

    return render(request, 'games/interpreter.html', res)


@perm_required(PERM_ADD_GAME)
def upload(request):
    file = request.FILES['file']
    fs = settings.UPLOADS_FS
    filename = fs.save(file.name, file, max_length=64)
    file_url = fs.url(filename)
    url_full = request.build_absolute_uri(file_url)

    url = URL()
    url.local_url = file_url
    url.original_url = url_full
    url.original_filename = file.name
    url.local_filename = filename
    url.content_type = file.content_type
    url.ok_to_clone = False
    url.is_uploaded = True
    url.creation_date = timezone.now()
    url.file_size = fs.size(filename)
    url.creator = request.user
    url.save()

    return JsonResponse({'url': url_full})


########################
# Json handlers below. #
########################


def authors(request):
    res = {'roles': [], 'authors': [], 'value': []}
    for x in GameAuthorRole.objects.order_by('order', 'title').all():
        res['roles'].append({'title': x.title, 'id': x.id})

    for x in PersonalityAlias.objects.order_by('name').all():
        res['authors'].append({'name': x.name, 'id': x.id})

    return res


def tags(request):
    res = {'categories': [], 'value': []}
    for x in (GameTagCategory.objects.order_by('order', 'name')):
        if not request.perm(x.show_in_edit_perm):
            continue
        val = {
            'id': x.id,
            'name': x.name,
            'allow_new_tags': x.allow_new_tags,
            'tags': []
        }
        # TODO(crem) Optimize this.
        for y in (GameTag.objects.filter(category=x).order_by('name')):
            val['tags'].append({
                'id': y.id,
                'name': y.name,
            })
        res['categories'].append(val)
    return res


def linktypes(request):
    res = {'categories': []}
    for x in GameURLCategory.objects.all():
        res['categories'].append({
            'id': x.id,
            'title': x.title,
            'uploadable': x.allow_cloning
        })
    return res


def json_gameinfo(request):
    res = {
        'authortypes': authors(request),
        'tagtypes': tags(request),
        'linktypes': linktypes(request),
    }
    game_id = request.GET.get('game_id', None)
    if game_id:
        g = {}
        res['gamedata'] = g
        game = Game.objects.get(id=game_id)
        request.perm.Ensure(game.view_perm)
        g['title'] = game.title or ''
        g['desc'] = game.description or ''
        g['release_date'] = str(game.release_date or '')

        g['authors'] = []
        for x in game.gameauthor_set.all():
            g['authors'].append((x.role_id, x.author_id))

        g['tags'] = []
        for x in game.tags.select_related('category').all():
            if not request.perm(x.category.show_in_edit_perm):
                continue
            g['tags'].append((x.category_id, x.id))

        g['links'] = []
        for x in game.gameurl_set.select_related('url').all():
            g['links'].append((x.category_id, x.description or '',
                               x.url.original_url))
    return JsonResponse(res)


def json_author_search(request):
    query = request.GET.get('q', '')
    start = int(request.GET.get('start', '0'))
    limit = int(request.GET.get('limit', '30'))
    start_time = timeit.default_timer()

    s = MakeAuthorSearch(request.perm)
    s.UpdateFromQuery(query)
    authors = s.Search(
        prefetch_related=['personalityalias_set__gameauthor_set__role'],
        start=start,
        limit=limit,
        annotate={
            'game_count':
            Coalesce(
                Subquery(
                    GameAuthor.objects.filter(
                        role__symbolic_id='author',
                        author__personality=OuterRef(
                            'pk')).values('author__personality').annotate(
                                cnt=Count('pk')).values('cnt'),
                    output_field=models.IntegerField()), 0),
        })

    for x in authors:
        x.aliases = []
        for a in x.personalityalias_set.filter(
                gameauthor__isnull=False).distinct():
            if a.name != x.name:
                x.aliases.append(a.name)
        x.honor_str = "%.1f" % x.honor
        x.stars = StarsFromRating(x.honor)

    res = render(request, 'games/authors_snippet.html', {
        'authors': authors,
        'start': start,
        'limit': limit,
        'next': start + limit,
        'has_more': len(authors) == limit,
    })

    elapsed_time = timeit.default_timer() - start_time

    if elapsed_time > 1.0:
        logger.error("Time for author search query [%s] was %f" %
                     (query, elapsed_time))
    return res


def json_search(request):
    query = request.GET.get('q', '')
    start = int(request.GET.get('start', '0'))
    limit = int(request.GET.get('limit', '80'))

    start_time = timeit.default_timer()
    s = MakeSearch(request.perm)
    s.UpdateFromQuery(query)
    games = s.Search(
        prefetch_related=['gameauthor_set__author', 'gameauthor_set__role'],
        start=start,
        limit=limit,
        annotate={
            'gamecomment__count':
            Count('gamecomment'),
            'hasvideo':
            Exists(
                GameURL.objects.filter(
                    category__symbolic_id='video', game=OuterRef('pk'))),
            'isparser':
            Exists(
                GameTag.objects.filter(
                    symbolic_id='parser', game=OuterRef('pk'))),
            'playonline':
            Exists(
                GameURL.objects.filter(game=OuterRef('pk')).filter(
                    Q(category__symbolic_id='play_online') | Q(
                        interpretedgameurl__is_playable=True))),
            'downloadable':
            Exists(
                GameURL.objects.filter(
                    category__symbolic_id__in=[
                        'download_direct', 'download_landing'
                    ],
                    game=OuterRef('pk'))),
            'loonchator_count':
            Count('package'),
        })

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
        x.icons = {}
        x.icons['hascomments'] = x.gamecomment__count > 0
        x.icons['hasvideo'] = x.hasvideo
        x.icons['isparser'] = x.isparser
        x.icons['playonline'] = x.playonline
        x.icons['downloadable'] = x.downloadable
        x.icons['loonchator'] = x.loonchator_count > 0

    res = render(request, 'games/search_snippet.html', {
        'games': games,
        'start': start,
        'limit': limit,
        'next': start + limit,
        'has_more': len(games) == limit,
    })

    elapsed_time = timeit.default_timer() - start_time

    if elapsed_time > 1.0:
        logger.error("Time for search query [%s] was %f" % (query,
                                                            elapsed_time))
    return res


@perm_required(PERM_ADD_GAME)
def doImport(request):
    raw_import = Import(request.GET.get('url'))
    if ('error' in raw_import):
        return JsonResponse({'error': raw_import['error']})
    return JsonResponse(Importer2Json(raw_import))
