from django.shortcuts import render


def index(request):
    return render(request, 'games/index.html', {})


def add_game(request):
    return render(request, 'games/add.html', {})
