from .models import (GameAuthorRole, Author, Game, GameTagCategory, GameTag,
                     URLCategory, URL, GameVotes)
from .importer import Import
from datetime import datetime
from dateutil.parser import parse as parse_date
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import FileSystemStorage
from django.http import Http404
from django.http.response import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from ifdb.permissioner import perm_required
from statistics import mean, median
import json
import markdown

PERM_ADD_GAME = '@auth'  # Also for file upload, game import, vote


def FormatDate(x):
    if not x:
        return None
    return '%d %s %d' % (x.day, ['января', 'февраля', 'марта', 'апреля', 'мая',
                                 'июня', 'июля', 'августа', 'сентября',
                                 'октября', 'ноября', 'декабря'][x.month],
                         x.year)


def index(request):
    return render(request, 'games/index.html', {})


@ensure_csrf_cookie
@login_required
@perm_required(PERM_ADD_GAME)
def add_game(request):
    return render(request, 'games/add.html', {})


@perm_required(PERM_ADD_GAME)
def store_game(request):
    # TODO !!!!!!!!!! PERMISSIONS TO STORE / EDIT GAME
    if request.method != 'POST':
        return render(request, 'games/error.html',
                      {'message': 'Что-то не так!' + ' (1)'})
    j = json.loads(request.POST.get('json'))
    if not j['title']:
        return render(request, 'games/error.html',
                      {'message': 'У игры должно быть название.'})
    try:
        g = Game()
        g.title = j['title']
        if j['description']:
            g.description = j['description']
        if j['release_date']:
            g.release_date = parse_date(j['release_date'])
        g.creation_time = datetime.now()
        g.added_by = request.user
        g.save()
        g.FillUrls(j['links'], request.user)
        g.StoreTags(j['properties'], request.perm)
        g.StoreAuthors(j['authors'])
    except ObjectDoesNotExist:
        raise Http404()
    return redirect(reverse('show_game', kwargs={'game_id': g.id}))


@perm_required(PERM_ADD_GAME)
def vote_game(request):
    if request.method != 'POST':
        return render(request, 'games/error.html',
                      {'message': 'Что-то не так!' + ' (2)'})
    game = Game.objects.get(id=int(request.POST.get('game_id')))

    try:
        obj = GameVotes.objects.get(game=game, user=request.user)
        obj.edit_time = datetime.now()
    except GameVotes.DoesNotExist:
        obj = GameVotes()
        obj.game = game
        obj.user = request.user
        obj.creation_time = datetime.now()

    obj.game_finished = bool(request.POST.get('finished', None))
    obj.edit_time = datetime.now()
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

    return redirect(reverse('show_game', kwargs={'game_id': game.id}))


def show_game(request, game_id):
    try:
        # TODO permissions!
        game = Game.objects.get(id=game_id)
        release_date = FormatDate(game.release_date)
        last_edit_date = FormatDate(game.edit_time)
        added_date = FormatDate(game.creation_time)
        authors = game.GetAuthors()
        links = game.GetURLs()
        md = markdown.markdown(
            game.description,
            ['markdown.extensions.extra', 'markdown.extensions.meta',
             'markdown.extensions.smarty', 'markdown.extensions.wikilinks'])
        tags = game.GetTagsForDetails(request.perm)
        votes = GetGameScore(game, request.user)
        return render(request, 'games/game.html', {
            'added_date': added_date,
            'authors': authors,
            'game': game,
            'last_edit_date': last_edit_date,
            'markdown': md,
            'release_date': release_date,
            'tags': tags,
            'links': links,
            'votes': votes,
        })
    except Game.DoesNotExist:
        raise Http404()
    return redirect('/')


def list_games(request):
    res = []
    for x in Game.objects.all().order_by('-creation_time'):
        if not request.perm(x.view_perm):
            continue
        res.append({'id': x.id, 'title': x.title})
    return render(request, 'games/list.html', {'games': res})


@perm_required(PERM_ADD_GAME)
def upload(request):
    file = request.FILES['file']
    fs = FileSystemStorage()
    filename = fs.save(file.name, file, max_length=64)
    file_url = fs.url(filename)
    url_full = request.build_absolute_uri(file_url)

    url = URL()
    url.local_url = file_url
    url.original_url = url_full
    url.original_filename = file.name
    url.content_type = file.content_type
    url.ok_to_clone = False
    url.is_uploaded = True
    url.creation_date = datetime.now()
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

    for x in Author.objects.order_by('name').all():
        res['authors'].append({'name': x.name, 'id': x.id})

    return JsonResponse(res)


def tags(request):
    res = {'categories': [], 'value': []}
    for x in (GameTagCategory.objects.order_by('order', 'name')):
        if not request.perm(x.show_in_edit_perm):
            continue
        val = {'id': x.id,
               'name': x.name,
               'allow_new_tags': x.allow_new_tags,
               'tags': []}
        for y in (GameTag.objects.filter(category=x).order_by('order',
                                                              'name')):
            val['tags'].append({
                'id': y.id,
                'name': y.name,
            })
        res['categories'].append(val)
    return JsonResponse(res)


def linktypes(request):
    res = {'categories': []}
    for x in URLCategory.objects.all():
        res['categories'].append({'id': x.id,
                                  'title': x.title,
                                  'uploadable': x.allow_cloning})
    return JsonResponse(res)


def Importer2Json(r):
    res = {}
    for x in ['title', 'desc', 'release_date']:
        if x in r:
            res[x] = str(r[x])

    if 'authors' in r:
        res['authors'] = []
        for x in r['authors']:
            if 'role_slug' in x:
                role = GameAuthorRole.objects.get(
                    symbolic_id=x['role_slug']).id
            else:
                role = r['role']
            res['authors'].append([role, x['name']])

    if 'tags' in r:
        res['tags'] = []
        for x in r['tags']:
            if 'tag_slug' in x:
                tag = GameTag.objects.get(symbolic_id=x['tag_slug'])
                cat = tag.category.id
                tag = tag.id
            else:
                tag = x['tag']
                cat = GameTagCategory.objects.get(symbolic_id=x['cat_slug']).id
            res['tags'].append([cat, tag])

    if 'urls' in r:
        res['links'] = []
        for x in r['urls']:
            cat = URLCategory.objects.get(symbolic_id=x['urlcat_slug']).id
            desc = x.get('description')
            url = x['url']
            res['links'].append([cat, desc, url])

    return res


@perm_required(PERM_ADD_GAME)
def doImport(request):
    raw_import = Import(request.GET.get('url'))
    if ('error' in raw_import):
        return JsonResponse({'error': raw_import['error']})
    return JsonResponse(Importer2Json(raw_import))
    try:
        return Importer2Json(raw_import)
    except:
        return JsonResponse({'error':
                             'Что-то поломалось, хотя не должно было.'})


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
def GetGameScore(game, user=None):
    res = {'user_played': False}
    if user and not user.is_authenticated:
        user = None
    finished_votes = []
    finished_times = []
    played_votes = []
    played_times = []
    res['user_hours'] = '0'
    res['user_mins'] = ''
    res['user_score'] = ''
    res['user_finished'] = False

    for v in GameVotes.objects.filter(game=game):
        played_votes.append(v.star_rating)
        played_times.append(v.play_time_mins)
        if v.game_finished:
            finished_votes.append(v.star_rating)
            finished_times.append(v.play_time_mins)
        if v.user == user:
            res['user_played'] = True
            res['user_hours'] = v.play_time_mins // 60
            res['user_mins'] = v.play_time_mins % 60
            res['user_score'] = v.star_rating
            res['user_finished'] = v.game_finished

    res['played_count'] = len(played_votes)
    if played_votes:
        avg = round(mean(played_votes) * 10)
        res['avg_rating'] = ("%3.1f" % (avg / 10.0)).replace('.', ',')
        res['stars'] = [10] * (avg // 10)
        if avg % 10 != 0:
            res['stars'].append(avg % 10)
        res['stars'].extend([0] * (5 - len(res['stars'])))

        t = round(median(played_times))
        res['played_hours'] = t // 60
        res['played_mins'] = t % 60

    res['finished_count'] = len(finished_votes)
    if finished_votes:
        t = round(median(finished_times))
        res['finished_hours'] = t // 60
        res['finished_mins'] = t % 60

    return res
