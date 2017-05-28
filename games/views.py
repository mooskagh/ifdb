from .models import (GameAuthorRole, Author, Game, GameTagCategory, GameTag,
                     URLCategory, URL)
from django.contrib.auth.decorators import login_required
from django.http.response import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from dateutil.parser import parse as parse_date
from datetime import datetime
from django.http import Http404
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import FileSystemStorage
from .importer import Import
import json
import markdown


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
def add_game(request):
    return render(request, 'games/add.html', {})


def store_game(request):
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
        g.FillTags(j['properties'])
        g.FillAuthors(j['authors'])
    except ObjectDoesNotExist:
        raise Http404()
    # TODO(crem) Better redirect
    return redirect('/')


def show_game(request, game_id):
    try:
        game = Game.objects.get(id=game_id)
        release_date = FormatDate(game.release_date)
        last_edit_date = FormatDate(game.edit_time)
        added_date = FormatDate(game.creation_time)
        authors = game.GetAuthors()
        md = markdown.markdown(
            game.description,
            ['markdown.extensions.extra', 'markdown.extensions.meta',
             'markdown.extensions.smarty', 'markdown.extensions.wikilinks'])
        tags = game.GetTags()
        return render(request, 'games/game.html', {
            'added_date': added_date,
            'authors': authors,
            'game': game,
            'last_edit_date': last_edit_date,
            'markdown': md,
            'release_date': release_date,
            'tags': tags,
        })
    except Game.DoesNotExist:
        raise Http404()
    return redirect('/')

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
    for x in (GameTagCategory.objects.filter(show_in_edit=True).order_by(
            'order', 'name')):
        val = {'id': x.id,
               'name': x.name,
               'allow_new_tags': x.allow_new_tags,
               'tags': []}
        for y in (GameTag.objects.filter(
                category=x, show_in_edit=True).order_by('order', 'name')):
            val['tags'].append({
                'id': y.id,
                'name': y.name,
            })
        res['categories'].append(val)
    return JsonResponse(res)


def linktypes(request):
    res = {'categories': []}
    for x in URLCategory.objects.all():
        if not x.allow_in_editor:
            continue
        res['categories'].append({'id': x.id,
                                  'title': x.title,
                                  'uploadable': x.allow_cloning})
    return JsonResponse(res)


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
