from django.shortcuts import render
from .models import Competition, CompetitionURL, CompetitionDocument
from django.http import Http404
from django.core.exceptions import ObjectDoesNotExist
from games.tools import RenderMarkdown, PartitionItems


def list_competitions(request):
    logos = CompetitionURL.objects.filter(category__symbolic_id='logo')
    g2l = {}
    for x in logos:
        g2l[x.competition_id] = x.GetLocalUrl()

    contests = []
    for x in Competition.objects.order_by('-end_date'):
        contests.append({
            'slug': x.slug,
            'title': x.title,
            'logo': g2l.get(x.id, '/static/default_competition_logo.jpg')
        })
    return render(request, 'contest/index.html', {'contests': contests})


def show_competition(request, slug, doc=''):
    try:
        comp = Competition.objects.get(slug=slug)
        docobj = CompetitionDocument.objects.get(slug=doc, competition=comp)
    except ObjectDoesNotExist:
        raise Http404()

    request.perm.Ensure(docobj.view_perm)

    logos = CompetitionURL.objects.filter(
        category__symbolic_id='logo', competition=comp)
    logo = logos[0].GetLocalUrl() if logos else None

    links = []
    for x in CompetitionDocument.objects.filter(
            competition=comp).order_by('slug'):
        if not request.perm(docobj.view_perm):
            continue
        if x.slug == doc:
            continue
        links.append(x)

    logos, ext_links = PartitionItems(comp.competitionurl_set.all(),
                                      [('logo', )])
    #    for x in CompetitionURL.objects.exclude(category__symbolic_id='logo'):
    #        ext_links.append({'description': x.description

    return render(
        request, 'contest/competition.html', {
            'comp': comp,
            'doc': docobj,
            'markdown': RenderMarkdown(docobj.text),
            'logo': logo,
            'docs': links,
            'links': ext_links,
        })
