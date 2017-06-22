from .models import (GameAuthorRole, Author, Game, GameTagCategory, GameTag,
                     URLCategory, URL, GameURL, GameVote, GameComment,
                     GameAuthor)
from .importer import Import
from .search import MakeSearch
from .tools import FormatDate, FormatTime, StarsFromRating
from datetime import datetime
from dateutil.parser import parse as parse_date
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.storage import FileSystemStorage
from django.http import Http404
from django.http.response import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from ifdb.permissioner import perm_required
from statistics import mean, median
import json
import logging
import markdown
from core.taskqueue import Enqueue
from .uploads import CloneFile, RecodeGame, MarkBroken

PERM_ADD_GAME = '@auth'  # Also for file upload, game import, vote


def index(request):
    return render(request, 'games/index.html', {})


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
        obj.edit_time = datetime.now()
    except GameVote.DoesNotExist:
        obj = GameVote()
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

    comment = GameComment()
    comment.game = game
    comment.user = request.user
    comment.parent_id = request.POST.get('parent', None)
    comment.creation_time = datetime.now()
    comment.subject = request.POST.get('subject', None) or None
    comment.text = request.POST.get('text', None)
    comment.save()

    return redirect(reverse('show_game', kwargs={'game_id': game.id}))


def show_game(request, game_id):
    try:
        game = Game.objects.get(id=game_id)
        request.perm.Ensure(game.view_perm)
        release_date = FormatDate(game.release_date)
        last_edit_date = FormatDate(game.edit_time)
        added_date = FormatDate(game.creation_time)
        authors = game.GetAuthors()
        links = game.GetURLs()
        md = GetMarkdown(game.description)
        tags = game.GetTagsForDetails(request.perm)
        votes = GetGameScore(game, request.user)
        comments = GetGameComments(game, request.user)
        return render(request, 'games/game.html', {
            'edit_perm': request.perm(game.edit_perm),
            'comment_perm': request.perm(game.comment_perm),
            'delete_perm': False,
            'added_date': added_date,
            'authors': authors,
            'game': game,
            'last_edit_date': last_edit_date,
            'markdown': md,
            'release_date': release_date,
            'tags': tags,
            'links': links,
            'votes': votes,
            'comments': comments,
        })
    except Game.DoesNotExist:
        raise Http404()


def list_games(request):
    res = []
    s = MakeSearch(request.perm)
    query = request.GET.get('q', '')
    s.UpdateFromQuery(query)
    if settings.DEBUG and request.GET.get('forcesearch', None):
        s.Search()
    return render(request, 'games/search.html', {'query': query,
                                                 **s.ProduceBits()})


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
        for y in (GameTag.objects.filter(category=x).order_by('order',
                                                              'name')):
            val['tags'].append({
                'id': y.id,
                'name': y.name,
            })
        res['categories'].append(val)
    return res


def linktypes(request):
    res = {'categories': []}
    for x in URLCategory.objects.all():
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


def json_search(request):
    query = request.GET.get('q', '')
    s = MakeSearch(request.perm)
    s.UpdateFromQuery(query)
    games = s.Search()

    posters = (GameURL.objects.filter(category__symbolic_id='poster').filter(
        game__in=games).select_related('url'))

    g2p = {}
    for x in posters:
        g2p[x.game_id] = x.url.local_url or x.url.original_url

    for x in games:
        x.poster = g2p.get(x.id)

    return render(request, 'games/search_snippet.html', {'games': games})


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
                try:
                    tag = GameTag.objects.get(symbolic_id=x['tag_slug'])
                except:
                    logging.error('Cannot fetch tag %s' % x['tag_slug'])
                    raise
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


############################################################################
# Aux functions below
############################################################################


def GetMarkdown(content):
    return markdown.markdown(content, [
        'markdown.extensions.extra', 'markdown.extensions.meta',
        'markdown.extensions.smarty', 'markdown.extensions.wikilinks',
        'del_ins'
    ]) if content else ''


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

    for v in GameVote.objects.filter(game=game):
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
        avg = mean(played_votes)
        res['avg_rating'] = ("%3.1f" % avg).replace('.', ',')
        res['stars'] = StarsFromRating(avg)

        t = round(median(played_times))
        res['played_hours'] = t // 60
        res['played_mins'] = t % 60

    res['finished_count'] = len(finished_votes)
    if finished_votes:
        t = round(median(finished_times))
        res['finished_hours'] = t // 60
        res['finished_mins'] = t % 60

    return res


# Returns repeated:
# user__name
# parent__id
#
def GetGameComments(game, user=None):
    res = []
    for v in GameComment.objects.select_related('user').filter(game=game):
        res.append({
            'id':
                v.id,
            'user_id':
                v.user.id if v.user else None,
            'username':
                v.user.username if v.user else v.foreign_username
                if v.foreign_username else 'Анонимоўс',
            'parent_id':
                v.parent.id if v.parent else None,
            'fusername':
                v.foreign_username,
            'furl':
                v.foreign_username,
            'fsite':
                None,  # TODO
            'created':
                FormatTime(v.creation_time),
            'edited':
                FormatTime(v.edit_time),
            'subj':
                v.subject,
            'text':
                GetMarkdown(v.text),
            # TODO: is_deleted
        })

    swap = []
    parent_to_cluster = {}
    clusters = []

    while res:
        for v in res:
            if not v['parent_id']:
                parent_to_cluster[v['id']] = len(clusters)
                clusters.append([v])
            elif v['parent_id'] in parent_to_cluster:
                clusters[parent_to_cluster[v['parent_id']]].append(v)
                parent_to_cluster[v['id']] = parent_to_cluster[v['parent_id']]
            else:
                swap.append(v)
        res = swap

    clusters.sort(key=lambda x: x[0]['created'])
    for x in clusters:
        x[1:] = sorted(x[1:], key=lambda t: t['created'])

    return [x for y in clusters for x in y]


def UpdateGameAuthors(request, game, authors, update):
    existing_authors = {}  # (role_id, author_id) -> GameAuthor_id
    if update:
        for x in game.gameauthor_set.all():
            existing_authors[(x.role_id, x.author_id)] = x.id

    authors_to_add = []  # (role_id, author_id)
    for (role, author) in authors:
        if not isinstance(role, int):
            role = GameAuthorRole.objects.get_or_create(title=role)[0].id
        if not isinstance(author, int):
            author = Author.objects.get_or_create(name=author)[0].id
        t = (role, author)
        if t in existing_authors:
            del existing_authors[t]
        else:
            authors_to_add.append(t)

    if authors_to_add:
        objs = []
        for role, author in authors_to_add:
            obj = GameAuthor()
            obj.game = game
            obj.author_id = author
            obj.role_id = role
            objs.append(obj)
        GameAuthor.objects.bulk_create(objs)

    if existing_authors:
        GameAuthor.objects.filter(
            id__in=list(existing_authors.values())).delete()


def UpdateGameTags(request, game, tags, update):
    existing_tags = set()  # tag_id
    if update:
        for x in game.tags.select_related('category').all():
            if not request.perm(x.category.show_in_edit_perm):
                continue
            existing_tags.add(x.id)

    if tags:
        id_to_cat = {}
        name_to_cat = {}
        for x in GameTagCategory.objects.all():
            id_to_cat[x.id] = x
            name_to_cat[x.name] = x

        tags_to_add = []  # (tag_id)
        for x in tags:
            if not isinstance(x[0], int):
                x[0] = name_to_cat[x[0]]

            if not isinstance(x[1], int):
                cat = id_to_cat[x[0]]
                if cat.allow_new_tags:
                    x[1] = GameTag.objects.get_or_create(
                        name=x[1], category=cat)[0].id
                else:
                    x[1] = GameTag.objects.get(name=x[1], category=cat)

            if x[1] in existing_tags:
                existing_tags.remove(x[1])
            else:
                tags_to_add.append(x[1])

        if tags_to_add:
            game.tags.add(*tags_to_add)

    if existing_tags:
        game.tags.filter(id__in=existing_tags).delete()


def UpdateGameUrls(request, game, data, update):
    existing_urls = {}  # (cat_id, gameurl_desc, url_text) -> gameurl_id
    if update:
        for x in game.gameurl_set.select_related('url').all():
            existing_urls[(x.category_id, x.description or '',
                           x.url.original_url)] = x.id

    records_to_add = []  # (cat_id, gameurl_desc, url_text)
    urls_to_add = []  # (url_text, cat_id)
    for x in data:
        t = tuple(x)
        if t in existing_urls:
            del existing_urls[t]
        else:
            records_to_add.append(t)
            urls_to_add.append((t[2], int(t[0])))

    if records_to_add:
        url_to_id = {}
        for u in URL.objects.filter(original_url__in=next(zip(*urls_to_add))):
            url_to_id[u.original_url] = u.id

        cats_to_check = set()
        for u, c in urls_to_add:
            if u not in url_to_id:
                cats_to_check.add(c)

        cat_to_cloneable = {}
        for c in URLCategory.objects.filter(id__in=cats_to_check):
            cat_to_cloneable[c.id] = c.allow_cloning

        game_to_task = {}
        for u, c in urls_to_add:
            if u not in url_to_id:
                url = URL()
                url.original_url = u
                url.creation_date = datetime.now()
                url.creator = request.user
                url.ok_to_clone = cat_to_cloneable[c]
                url.save()
                if url.ok_to_clone:
                    game_to_task[url.id] = Enqueue(
                        CloneFile,
                        url.id,
                        name='CloneGame(%d)' % url.id,
                        onfail=MarkBroken)
                url_to_id[u] = url.id

        objs = []
        for (cat, desc, url) in records_to_add:
            obj = GameURL()
            obj.category_id = cat
            obj.url_id = url_to_id[url]
            obj.game = game
            obj.description = desc or None
            if URLCategory.IsRecodable(cat):
                obj.save()
                Enqueue(
                    RecodeGame,
                    obj.id,
                    name='RecodeGame(%d)' % obj.id,
                    dependency=game_to_task.get(url_to_id[url]))
            else:
                objs.append(obj)
        GameURL.objects.bulk_create(objs)

    if existing_urls:
        GameURL.objects.filter(id__in=list(existing_urls.values())).delete()


def UpdateGame(request, j):
    if ('game_id' in j):
        g = Game.objects.get(id=j['game_id'])
        request.perm.Ensure(g.edit_perm)
        g.edit_time = datetime.now()
    else:
        request.perm.Ensure(PERM_ADD_GAME)
        g = Game()
        g.creation_time = datetime.now()
        g.added_by = request.user

    g.title = j['title']
    g.description = j['desc'] or None
    g.release_date = (parse_date(j['release_date'])
                      if j.get('release_date', None) else None)

    g.save()
    UpdateGameUrls(request, g, j['links'], 'game_id' in j)
    UpdateGameTags(request, g, j['tags'], 'game_id' in j)
    UpdateGameAuthors(request, g, j['authors'], 'game_id' in j)

    return g.id
