from contest.models import (Competition, CompetitionURLCategory,
                            CompetitionURL, GameList, GameListEntry,
                            CompetitionDocument, CompetitionSchedule)
from django import forms
from django.forms import widgets
from django.shortcuts import render, redirect
from django.utils import timezone
from django.urls import reverse
from games.tools import ConcoreNumeral, CreateUrl

YEARS = range(timezone.now().year + 1, 1990, -1)

EDIT_PERM = '@auth'


class CompetitionForm(forms.Form):
    id = forms.IntegerField(widget=widgets.HiddenInput())
    title = forms.CharField(label='Название события')
    slug = forms.CharField(label='URL: db.crem.xyz/jam/', label_suffix='')
    start_date = forms.DateField(
        label='Дата начала',
        required=False,
        widget=widgets.SelectDateWidget(years=YEARS))
    end_date = forms.DateField(
        label='Дата окончания',
        required=False,
        widget=widgets.SelectDateWidget(years=YEARS))
    published = forms.BooleanField(label='Показывать в списке', required=False)

    def clean(self):
        cleaned_data = super().clean()
        if Competition.objects.filter(slug=cleaned_data['slug']).exclude(
                id=cleaned_data['id'], ).exists():
            self.add_error('slug', 'Событие с таким URL уже есть!')

        return cleaned_data


class UrlForm(forms.Form):
    id = forms.IntegerField(widget=widgets.HiddenInput(), required=False)
    description = forms.CharField(label='Описание')
    url = forms.CharField()
    category = forms.ChoiceField(
        label='Тип ссылки',
        required=True,
        choices=[(None, '(надо выбрать)')] +
        [(x.id, x.title)
         for x in CompetitionURLCategory.objects.order_by('order')])


class NominationsForm(forms.Form):
    id = forms.IntegerField(widget=widgets.HiddenInput(), required=False)
    order = forms.IntegerField(label='#')
    title = forms.CharField(
        required=False,
        label='Название номинации',
        help_text='Может быть пустым, например, если номинация всего одна')

    def GetButtonLabels(self):
        return ['Список игр']

    def GetButtons(self):
        id = self.initial.get('id')
        if id:
            return [{
                'url':
                    reverse('edit_complist', kwargs={'id': id}),
                'text':
                    'Править (%s)' % ConcoreNumeral(
                        GameListEntry.objects.filter(gamelist_id=id).count(),
                        'игра,игры,игр'),
            }]


class ScheduleForm(forms.Form):
    id = forms.IntegerField(widget=widgets.HiddenInput(), required=False)
    title = forms.CharField(label='Текст', required=True)
    when = forms.DateTimeField(
        label='Дата',
        required=True,
        widget=widgets.SelectDateWidget(years=YEARS))
    show = forms.BooleanField(
        label='Показывать?', required=False, initial=True)


class DocumentsForm(forms.Form):
    id = forms.IntegerField(widget=widgets.HiddenInput(), required=False)
    slug = forms.CharField(
        required=False,
        label='Имя в URL',
        help_text='Может быть пустым, для главной страницы',
        label_suffix='')
    title = forms.CharField(label='Заголовок страницы', required=True)

    def GetButtonLabels(self):
        return ['Редактировать']

    def GetButtons(self):
        id = self.initial.get('id')
        if id:
            return [{
                'url': reverse('edit_compdoc', kwargs={'id': id}),
                'text': 'Редактировать',
            }]


class DocumentsFormSet(forms.BaseFormSet):
    def clean(self):
        if any(self.errors):
            return
        slugs = []
        for f in self.forms:
            if f.cleaned_data['DELETE']:
                continue
            if not f.has_changed() and f.empty_permitted:
                continue
            x = f.cleaned_data.get('slug', '')
            if x in slugs:
                raise forms.ValidationError(
                    'Имена в URL должны быть различными.')
            slugs.append(x)


def edit_competition(request, id):
    comp = Competition.objects.get(pk=id)
    if comp.owner:
        request.perm.Ensure('[%d]' % comp.owner_id)
    else:
        request.perm.Ensure(EDIT_PERM)

    main = CompetitionForm(
        request.POST or None,
        prefix='main',
        initial={
            'id': comp.id,
            'title': comp.title,
            'slug': comp.slug,
            'start_date': comp.start_date,
            'end_date': comp.end_date,
            'published': comp.published,
        })
    Urls = forms.formset_factory(UrlForm, extra=0, can_delete=True)
    urls = Urls(
        request.POST or None,
        prefix='urls',
        initial=[{
            'id': x.id,
            'description': x.description,
            'url': x.url,
            'category': x.category_id
        } for x in CompetitionURL.objects.filter(competition=comp)])

    Nominations = forms.formset_factory(
        NominationsForm, extra=0, can_delete=True)
    nominations = Nominations(
        request.POST or None,
        prefix='nominations',
        initial=[{
            'id': x.id,
            'order': x.order,
            'title': x.title,
        } for x in GameList.objects.filter(competition=comp).order_by('order')
                 ])

    Schedule = forms.formset_factory(ScheduleForm, extra=0, can_delete=True)
    schedule = Schedule(
        request.POST or None,
        prefix='schedule',
        initial=[{
            'id': x.id,
            'when': x.when,
            'title': x.title,
        } for x in CompetitionSchedule.objects.filter(
            competition=comp).order_by('when')])

    Documents = forms.formset_factory(
        DocumentsForm, extra=0, can_delete=True, formset=DocumentsFormSet)
    documents = Documents(
        request.POST or None,
        prefix='docs',
        initial=[{
            'id': x.id,
            'slug': x.slug,
            'title': x.title
        } for x in CompetitionDocument.objects.filter(competition=comp)])

    fs = [main, urls, nominations, schedule, documents]

    if request.POST and all(map(lambda x: x.is_valid(), fs)):
        if main.has_changed():
            for x in ['title', 'slug', 'start_date', 'end_date', 'published']:
                field = main.cleaned_data[x]
                setattr(comp, x, field)
            comp.save()

        def ProcessFormset(formset, model, func):
            if not formset.has_changed():
                return None
            for f in formset:
                if not f.has_changed():
                    continue
                cl = f.cleaned_data
                if cl['id']:
                    v = model.objects.get(pk=cl['id'], competition_id=comp.id)
                else:
                    v = model()
                    v.competition_id = comp.id
                if cl['DELETE']:
                    if v.id:
                        v.delete()
                    continue
                func(v, cl)
                v.save()

        def PopulateUrl(v, cl):
            v.category = CompetitionURLCategory.objects.get(pk=cl['category'])
            v.url = CreateUrl(cl['url'], ok_to_clone=v.category.allow_cloning)
            v.description = cl['description']

        ProcessFormset(urls, CompetitionURL, PopulateUrl)

        def PopulateNomination(v, cl):
            v.order = cl['order']
            v.title = cl['title']

        ProcessFormset(nominations, GameList, PopulateNomination)

        def PopulateSchedule(v, cl):
            v.when = cl['when']
            v.show = cl['show']
            v.title = cl['title']
            if v.done is None:
                v.done = False

        ProcessFormset(schedule, CompetitionSchedule, PopulateSchedule)

        def PopulateDocument(v, cl):
            v.slug = cl['slug']
            v.title = cl['title']

        ProcessFormset(documents, CompetitionDocument, PopulateDocument)

        return redirect(request.get_full_path())

    return render(
        request, 'contest/edit.html', {
            'comp': comp,
            'mainform': main,
            'urlform': urls,
            'nomiform': nominations,
            'scheduform': schedule,
            'docuform': documents,
        })


class ListEntryForm(forms.Form):
    def __init__(self, *args, competition=None, **argw):
        super().__init__(*args, **argw)
        if competition:
            choices = [(x.id, x.title or '(основная)')
                       for x in GameList.objects.filter(
                           competition=competition).order_by('order')]
            self.fields['gamelist'].choices = [(None, '(надо выбрать)')
                                               ] + choices

    id = forms.IntegerField(widget=widgets.HiddenInput(), required=False)
    rank = forms.IntegerField(required=False, label='Место')
    gameid = forms.IntegerField(required=False, label='id игры')
    gamename = forms.CharField(
        required=False, disabled=True, label='Название игры')
    comment = forms.CharField(required=False, label='Комментарий')
    date = forms.DateField(
        label='Дата',
        required=False,
        widget=widgets.SelectDateWidget(years=YEARS))
    gamelist = forms.ChoiceField(
        label='Номинация', required=True, choices=[(None, '(нету)')])


def edit_complist(request, id):
    gamelist = GameList.objects.get(pk=id)
    comp = gamelist.competition
    if comp.owner:
        request.perm.Ensure('[%d]' % comp.owner_id)
    else:
        request.perm.Ensure(EDIT_PERM)

    ListEntries = forms.formset_factory(
        ListEntryForm,
        extra=0,
        can_delete=True,
    )
    entries = ListEntries(
        request.POST or None,
        initial=[{
            'id': x.id,
            'rank': x.rank,
            'gameid': x.game_id,
            'gamename': x.game.title if x.game else None,
            'comment': x.comment,
            'date': x.date,
            'gamelist': x.gamelist_id,
        } for x in GameListEntry.objects.filter(
            gamelist=id).order_by('rank', 'date', 'game__title')],
        form_kwargs={
            'competition': comp,
        })

    if request.POST and entries.is_valid():
        if entries.has_changed():
            for f in entries:
                if not f.has_changed():
                    continue
                cl = f.cleaned_data
                if cl['id']:
                    v = GameListEntry.objects.get(
                        pk=cl['id'], gamelist_id=gamelist.id)
                else:
                    v = GameListEntry()
                if cl['DELETE']:
                    if v.id:
                        v.delete()
                    continue
                v.gamelist_id = cl['gamelist']
                v.rank = cl['rank']
                v.game_id = cl['gameid']
                v.comment = cl['comment']
                v.date = cl['date']
                v.save()
        return redirect(request.get_full_path())

    return render(request, 'contest/editlist.html', {
        'gamelist': gamelist,
        'entries': entries,
    })


class DocumentForm(forms.Form):
    id = forms.IntegerField(widget=widgets.HiddenInput(), required=False)
    title = forms.CharField(required=False, label='Заголовок')
    text = forms.CharField(
        required=True, label='Текст', widget=widgets.Textarea())


def edit_compdoc(request, id):
    doc = CompetitionDocument.objects.get(pk=id)
    comp = doc.competition

    if comp.owner:
        request.perm.Ensure('[%d]' % comp.owner_id)
    else:
        request.perm.Ensure(EDIT_PERM)

    form = DocumentForm(
        request.POST or None,
        initial={
            'id': doc.id,
            'title': doc.title,
            'text': doc.text,
        })

    if request.POST and form.is_valid():
        if form.has_changed():
            cl = form.cleaned_data
            doc.title = cl['title']
            doc.text = cl['text']
            doc.save()
        return redirect(
            reverse(
                'show_competition',
                kwargs={
                    'slug': comp.slug,
                    'doc': doc.slug
                }))

    return render(request, 'contest/editdoc.html', {'doc': doc, 'form': form})
