import json
from logging import getLogger
import os.path
import timeit
import random
from .game_details import GameDetailsBuilder, StarsFromRating
from .importer import Importer
from .importer.tools import CategorizeUrl
from .importer.discord import PostNewGameToDiscord
from .models import (GameURL, GameComment, Game, GameVote, InterpretedGameUrl,
                     URL, GameTag, GameAuthorRole, PersonalityAlias,
                     GameTagCategory, GameURLCategory, GameAuthor, Personality)
from .search import MakeSearch, MakeAuthorSearch
from .tools import (RenderMarkdown, ComputeGameRating, ComputeHonors,
                    SnippetFromList)
from .updater import UpdateGame, Importer2Json
from core.snippets import RenderSnippets
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousOperation
from django.db import models
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404
from django.http.response import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from ifdb.permissioner import perm_required
from moder.actions import GetModerActions
from moder.userlog import LogAction

PERM_ADD_GAME = '@auth'  # Also for file upload, game import, vote
logger = getLogger('web')


def index(request):
    LogAction(request, 'nav-index', is_mutation=False, obj=None)
    return render(request, 'games/index.html',
                  {'snippets': RenderSnippets(request)})


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

    before = None
    is_new_game = 'game_id' not in j
    if 'game_id' in j:
        before = BuildJsonGameInfo(request, j['game_id'])
        before['game_id'] = str(j['game_id'])

    id = UpdateGame(request, j)
    LogAction(
        request,
        'gam-store',
        is_mutation=True,
        obj_type='Game',
        obj_id=id,
        before=before,
        after=j)
    print(is_new_game)
    if is_new_game:
        PostNewGameToDiscord(id)
    return redirect(reverse('show_game', kwargs={'game_id': id}))


def vote_game(request):
    if request.method != 'POST':
        return render(request, 'games/error.html',
                      {'message': 'Что-то не так!' + ' (2)'})
    game = Game.objects.get(id=int(request.POST.get('game_id')))
    request.perm.Ensure(game.vote_perm)

    before = None
    try:
        obj = GameVote.objects.get(game=game, user=request.user)
        obj.edit_time = timezone.now()
        before = {'stars': obj.star_rating}
    except GameVote.DoesNotExist:
        obj = GameVote()
        obj.game = game
        obj.user = request.user
        obj.creation_time = timezone.now()

    obj.edit_time = timezone.now()
    obj.star_rating = int(request.POST.get('score'))
    obj.save()

    LogAction(
        request,
        'gam-vote',
        obj=game,
        obj2=obj,
        before=before,
        after={'stars': obj.star_rating},
        is_mutation=True)

    return redirect(reverse('show_game', kwargs={'game_id': game.id}))


ANONYMOUS_ANIMALS = [
    'Анонимный волк', 'Анонимная выдра', 'Анонимная гадюка',
    'Анонимный гепард', 'Анонимная гиена', 'Анонимный гиппопотам',
    'Анонимная гну', 'Анонимная горилла', 'Анонимный гризли', 'Анонимный гусь',
    'Анонимный дикобраз', 'Анонимный динозавр', 'Анонимный енот',
    'Анонимная ехидна', 'Анонимный ёж', 'Анонимная жаба', 'Анонимный жираф',
    'Анонимный заяц', 'Анонимный зебра', 'Анонимная змея', 'Анонимный зубр',
    'Анонимная игуана', 'Анонимная индейка', 'Анонимный кабан',
    'Анонимный кашалот', 'Анонимная квакша', 'Анонимный кенгуру',
    'Анонимный кит', 'Анонимная кобра', 'Анонимная коала', 'Анонимный козёл',
    'Анонимный койот', 'Анонимный конь', 'Анонимная корова', 'Анонимный кот',
    'Анонимная кошка', 'Анонимный крокодил', 'Анонимный кролик',
    'Анонимный крот', 'Анонимная крыса', 'Анонимная кряква',
    'Анонимная куница', 'Анонимная курица', 'Анонимная лама', 'Анонимная лань',
    'Анонимный лев', 'Анонимный лемур', 'Анонимный ленивец',
    'Анонимный леопард', 'Анонимная лисица', 'Анонимный лось',
    'Анонимная лошадь', 'Анонимная лягушка', 'Анонимная макака',
    'Анонимная мартышка', 'Анонимный медведь', 'Анонимный моллюск',
    'Анонимный морж', 'Анонимный муравьед', 'Анонимная мышь',
    'Анонимный носорог', 'Анонимная нутрия', 'Анонимный обезьяна',
    'Анонимная овца', 'Анонимный олень', 'Анонимный омар', 'Анонимная ондатра',
    'Анонимный опоссум', 'Анонимный осёл', 'Анонимный осьминог',
    'Анонимный павиан', 'Анонимная пантера', 'Анонимный петух',
    'Анонимный пингвин', 'Анонимная пума', 'Анонимная рысь',
    'Анонимная саламандра', 'Анонимная свинья', 'Анонимный скунс',
    'Анонимный собака', 'Анонимный соболь', 'Анонимный сурок',
    'Анонимный суслик', 'Анонимный тигр', 'Анонимный тюлень', 'Анонимный удав',
    'Анонимный уж', 'Анонимная утка', 'Анонимный утконос',
    'Анонимный хамелеон', 'Анонимный хомяк', 'Анонимный хорёк',
    'Анонимная черепаха', 'Анонимный шимпанзе', 'Анонимная шиншилла',
    'Анонимный ягуар', 'Анонимный як', 'Анонимная ящерица'
]


def comment_game(request):
    if request.method != 'POST':
        return render(request, 'games/error.html',
                      {'message': 'Что-то не так!' + ' (3)'})
    game = Game.objects.get(id=int(request.POST.get('game_id')))
    request.perm.Ensure(game.comment_perm)

    comment = GameComment()
    comment.game = game
    print(request.user)
    comment.user = None if request.user.is_anonymous or request.POST.get(
        'anonymous', False) else request.user
    if comment.user:
        comment.username = comment.user.username
    else:
        comment.username = request.session.setdefault(
            'anonymous_nick', random.choice(ANONYMOUS_ANIMALS))
    comment.parent_id = request.POST.get('parent', None)
    comment.creation_time = timezone.now()
    comment.text = request.POST.get('text', None)
    comment.save()

    LogAction(
        request,
        'gam-comment',
        is_mutation=True,
        obj=game,
        obj2=comment,
        after={
            'username': comment.username,
            'text': comment.text,
        })
    return redirect(reverse('show_game', kwargs={'game_id': game.id}))


def show_game(request, game_id):
    try:
        g = GameDetailsBuilder(game_id, request)
        LogAction(request, 'gam-view', is_mutation=False, obj=g.game)
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

        res['honor'] = ComputeHonors(int(author_id))
        res['honor_stars'] = StarsFromRating(res['honor'])
        res['honor_str'] = "%.1f" % res['honor']
        res['moder_actions'] = GetModerActions(request, 'Personality', a)

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

        act_start = None
        act_end = None
        games = dict()
        existing = set()
        for g in GameAuthor.objects.filter(author__personality=author_id
                                           ).select_related().prefetch_related(
                                               'game__gameauthor_set__role',
                                               'game__gameauthor_set__author',
                                               'game__gamevote_set'):
            y = (g.game.id, g.role.id)
            if y in existing:
                continue
            existing.add(y)
            gs = games.setdefault(g.role, [])
            rating = ComputeGameRating(
                [x.star_rating for x in g.game.gamevote_set.all()])
            g.game.ds = rating
            gs.append(g.game)

            if g.role.symbolic_id != 'author':
                continue
            if not g.game.release_date:
                continue
            if not act_start or g.game.release_date < act_start:
                act_start = g.game.release_date
            if not act_end or g.game.release_date > act_end:
                act_end = g.game.release_date

        if act_start:
            beg = act_start.year
            end = act_end.year
            res['activity_start'] = beg
            if beg != end:
                res['activity_end'] = end

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

        LogAction(request, 'pers-view', is_mutation=False, obj=a)
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


def BuildJsonGameInfo(request, game_id):
    g = {}
    if game_id:
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
    return g


def json_gameinfo(request):
    res = {
        'authortypes':
            authors(request),
        'tagtypes':
            tags(request),
        'linktypes':
            linktypes(request),
        'gamedata':
            BuildJsonGameInfo(request, request.GET.get('game_id', None)),
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


def json_categorizeurl(request):
    url = request.GET.get('url')
    desc = request.GET.get('desc') or ''
    cat = request.GET.get('cat')
    if cat:
        cat = GameURLCategory.objects.get(pk=cat).symbolic_id
    else:
        cat = None

    res = CategorizeUrl(url, desc, cat)
    return JsonResponse({
        'desc': (res['description']),
        'cat': (
            GameURLCategory.objects.get(symbolic_id=res['urlcat_slug']).id),
    })


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
                            author__personality=OuterRef('pk')).
                        values('author__personality').annotate(
                            cnt=Count('game', distinct=True)).values('cnt'),
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

    res = render(
        request, 'games/authors_snippet.html', {
            'authors': authors,
            'start': start,
            'limit': limit,
            'next': start + limit,
            'has_more': len(authors) == limit,
        })

    elapsed_time = timeit.default_timer() - start_time

    if elapsed_time > 2.0:
        logger.error(
            "Time for author search query [%s] was %f" % (query, elapsed_time))
    if start == 0:
        LogAction(
            request, 'pers-search', after={'query': query}, is_mutation=False)
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
    )

    SnippetFromList(games)

    res = render(
        request, 'games/search_snippet.html', {
            'games': games,
            'start': start,
            'limit': limit,
            'next': start + limit,
            'has_more': len(games) == limit,
        })

    elapsed_time = timeit.default_timer() - start_time

    if elapsed_time > 2.0:
        logger.error(
            "Time for search query [%s] was %f" % (query, elapsed_time))

    if start == 0:
        LogAction(
            request, 'gam-search', after={'query': query}, is_mutation=False)
    return res


@perm_required(PERM_ADD_GAME)
def doImport(request):
    importer = Importer()
    (raw_import, _) = importer.Import(request.GET.get('url'))
    if ('error' in raw_import):
        return JsonResponse({'error': raw_import['error']})
    return JsonResponse(Importer2Json(raw_import))
