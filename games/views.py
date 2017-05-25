from .models import GameAuthorRole, Author, Game, GameTagCategory, GameTag
from django.contrib.auth.decorators import login_required
from django.http.response import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from dateutil.parser import parse as parse_date
from datetime import datetime
import json


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

    g = Game()
    g.title = j['title']
    if j['description']:
        g.description = j['description']
    if j['release_date']:
        g.release_date = parse_date(j['release_date'])
    g.creation_time = datetime.now()
    g.added_by = request.user
    g.save()
    g.FillAuthors(j['authors'])
    g.FillTags(j['properties'])
    # TODO(crem) Better redirect
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
