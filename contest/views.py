from django.shortcuts import render
from .models import Competition, CompetitionURL


def list_competitions(request):

    logos = CompetitionURL.objects.filter(category__symbolic_id='logo')
    g2l = {}
    for x in logos:
        g2l[x.competition_id] = x.GetLocalUrl()

    contests = []
    for x in Competition.objects.order_by('-end_date'):
        contests.append({
            'title': x.title,
            'logo': g2l.get(x.id, '/static/default_competition_logo.jpg')
        })
    return render(request, 'contest/index.html', {'contests': contests})
