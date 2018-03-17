import json
import datetime
from contest.models import (GameListEntry, CompetitionVote)
from django import forms
from django.template.loader import render_to_string
from django.utils import timezone
from games.tools import FormatDate, GetIpAddr
from moder.userlog import LogAction

# Competition options:
#
# voting:
#   open: bool
#   allow_vote: '@notor'
#   start: timestamp
#   end: timestamp
#   sections:
#     nomination: (id) (id's of nominations. if empty then global)
#     optional: True/false  # if every game is optional
#     fields: []
#        type: CharField
#        label: ""
#        helptext: ""
#        widget: ""
#        format: ""
#        default: ""


class SliderWidget(forms.widgets.NumberInput):
    template_name = 'contest/slider_widget.html'

    def __init__(self, *argv, step=1, **kwargs):
        super().__init__(*argv, **kwargs)
        self.step = step

    def get_context(self, name, value, attrs):
        res = super().get_context(name, value, attrs)
        attrs = res['widget']['attrs']
        res['slider'] = {
            'min': attrs.get('min', 0),
            'max': attrs.get('max', 100),
            'step': self.step,
        }
        return res


WIDGETS = {
    'slider': SliderWidget,
    'textarea': forms.widgets.Textarea,
}


class VotingFormSet(forms.BaseFormSet):
    def __init__(self, *args, fields, games, section, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields = fields
        self.games = games
        self.section_name = section

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['fields'] = self.fields
        if index is not None and index < len(self.games):
            kwargs['game'] = self.games[index]
        return kwargs


class VotingForm(forms.Form):
    def __init__(self, *args, fields, game=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.gameentry = game
        self.game = None
        if game and game.game:
            self.game = game.game
            self.game.authors = [
                x.author for x in game.game.gameauthor_set.all()
                if x.role.symbolic_id == 'author'
            ]

        for x in fields:
            y = x.copy()
            default = y.pop('default', None)
            name = y.pop('name')
            typ = y.pop('type')
            widget_name = y.pop('widget', None)
            widget_kwargs = y.pop('widget_kwargs', {})
            if widget_name:
                widget = WIDGETS[widget_name](**widget_kwargs)
                y['widget'] = widget
            field = getattr(forms, typ)(**y)
            self.fields[name] = field
            self.fields[name].typ = typ
            if default is not None:
                self.fields[name].default = default

    has_vote = forms.BooleanField(required=False)
    game_id = forms.IntegerField(
        widget=forms.widgets.HiddenInput(), disabled=True)


def RenderVotingImpl(request, comp, voting):
    if not voting:
        return {'error': 'В этом соревновании голосование не проводится.'}

    if not voting.get('open'):
        return {'error': 'Голосование закрыто.'}

    now = timezone.now()
    if voting.get('start') and datetime.datetime.fromtimestamp(
            voting['start']) > now:
        start = datetime.datetime.fromtimestamp(voting['start'])
        return {
            'error':
                'Голосование откроется %s в %02d:%02d (по Гринвичу).' %
                (FormatDate(start), start.hour, start.minute)
        }

    if voting.get('end') and datetime.datetime.fromtimestamp(
            voting['end']) <= now:
        end = datetime.datetime.fromtimestamp(voting['end'])
        return {
            'error':
                'Голосование закрылось %s в %02d:%02d (по Гринвичу).' %
                (FormatDate(end), end.hour, end.minute)
        }

    if not request.user.is_authenticated:
        return {'error': 'Для того, чтобы проголосовать, залогиньтесь.'}

    res = {'sections': []}

    fss = []
    before = []
    for i, section in enumerate(voting.get('sections', [])):
        nomination_id = section['nomination']
        section_name = section.get('name')
        gamelist = GameListEntry.objects.filter(
            gamelist__competition=comp,
            gamelist__id=nomination_id).order_by('game__id').select_related()
        Fs = forms.formset_factory(VotingForm, formset=VotingFormSet, extra=0)
        initials = []
        for x in gamelist:
            initial = {}
            initial['game_id'] = x.game.id
            votes = {
                y.field: y
                for y in CompetitionVote.objects.filter(
                    competition=comp,
                    user=request.user,
                    section=section_name,
                    game=x.game)
            }
            if votes:
                initial['has_vote'] = True
            for y in section['fields']:
                if 'default' in y:
                    initial[y['name']] = y['default']
                if y['name'] in votes:
                    initial[y['name']] = votes[y['name']].GetVal(y['type'])

            initials.append(initial)
        fs = Fs(
            request.POST or None,
            prefix='f%d' % i,
            fields=section['fields'],
            games=gamelist,
            section=section_name,
            initial=initials)
        fss.append(fs)
        res['sections'].append(fs)
        before.append(initials)

    if request.POST and all(map(lambda x: x.is_valid(), fss)):
        now = timezone.now()
        after = []
        for fs in fss:
            after.append(fs.cleaned_data)
            if not fs.has_changed():
                continue
            for f in fs:
                if not f.has_changed():
                    continue
                cd = f.cleaned_data
                if not cd['has_vote']:
                    CompetitionVote.objects.filter(
                        competition=comp,
                        user=request.user,
                        section=fs.section_name,
                        game=cd['game_id']).delete()
                    continue

                for field in fs.fields:
                    try:
                        vote = CompetitionVote.objects.get(
                            competition=comp,
                            user=request.user,
                            section=fs.section_name,
                            game=cd['game_id'],
                            field=field['name'])
                    except CompetitionVote.DoesNotExist:
                        vote = CompetitionVote(
                            competition=comp,
                            user=request.user,
                            section=fs.section_name,
                            game_id=cd['game_id'],
                            field=field['name'])
                    vote.when = now
                    vote.SetVal(field['type'], cd[field['name']])
                    vote.ip_addr = GetIpAddr(request)
                    vote.session = request.session.session_key
                    vote.perm = str(request.perm)
                    vote.save()
        LogAction(
            request,
            'comp-vote',
            is_mutation=True,
            obj=comp,
            before=before,
            after=after,
        )
        res['success_text'] = 'Ваш голос принят.'

    return res


def RenderVoting(request, comp):
    options = json.loads(comp.options)
    voting = options.get('voting')
    res = RenderVotingImpl(request, comp, voting)

    return render_to_string('contest/voting.html', res, request=request)
