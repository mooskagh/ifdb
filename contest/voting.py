import datetime
import json

from django import forms
from django.template.loader import render_to_string
from django.utils import timezone

from contest.models import CompetitionQuestion, CompetitionVote, GameListEntry
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
    template_name = "contest/slider_widget.html"

    def __init__(self, *argv, step=1, **kwargs):
        super().__init__(*argv, **kwargs)
        self.step = step

    def get_context(self, name, value, attrs):
        res = super().get_context(name, value, attrs)
        attrs = res["widget"]["attrs"]
        res["slider"] = {
            "min": attrs.get("min", 0),
            "max": attrs.get("max", 100),
            "step": self.step,
        }
        return res


class QuestionWidget(forms.widgets.TextInput):
    needs_game = True
    template_name = "contest/question_widget.html"

    def __init__(self, *argv, game, question_id, **kwargs):
        self.game = game
        self.question_id = question_id
        super().__init__(*argv, **kwargs)

    def get_context(self, name, value, attrs):
        res = super().get_context(name, value, attrs)
        try:
            res["question"] = CompetitionQuestion.objects.get(
                game=self.game, question_id=self.question_id
            ).text
        except CompetitionQuestion.DoesNotExist:
            res["question"] = "( — — — — — )"
        return res


WIDGETS = {
    "question": QuestionWidget,
    "slider": SliderWidget,
    "text": forms.widgets.TextInput,
    "textarea": forms.widgets.Textarea,
}


class VotingFormSet(forms.BaseFormSet):
    def __init__(
        self,
        *args,
        fields,
        games,
        nomination_id,
        additional_label=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields = fields
        self.games = games
        self.nomination_id = nomination_id
        self.additional_label = additional_label

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["fields"] = self.fields
        if index is not None and index < len(self.games):
            kwargs["game"] = self.games[index]
        if self.additional_label:
            try:
                kwargs["additional_label"] = CompetitionQuestion.objects.get(
                    game=kwargs["game"].game, question_id=self.additional_label
                ).text
            except CompetitionQuestion.DoesNotExist:
                pass
        return kwargs


class VotingForm(forms.Form):
    def __init__(
        self, *args, fields, game=None, additional_label=None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.gameentry = game
        self.game = None
        self.additional_label = additional_label
        if game and game.game:
            self.game = game.game
            self.game.authors = [
                x.author
                for x in game.game.gameauthor_set.all()
                if x.role.symbolic_id == "author"
            ]

        for x in fields:
            y = x.copy()
            default = y.pop("default", None)
            name = y.pop("name")
            typ = y.pop("type")
            widget_name = y.pop("widget", None)
            widget_kwargs = y.pop("widget_kwargs", {})
            if widget_name:
                widget_class = widget = WIDGETS[widget_name]
                if getattr(widget_class, "needs_game", False):
                    widget = WIDGETS[widget_name](
                        game=self.game, **widget_kwargs
                    )
                else:
                    widget = WIDGETS[widget_name](**widget_kwargs)
                y["widget"] = widget
            field = getattr(forms, typ)(**y)
            self.fields[name] = field
            self.fields[name].typ = typ
            if default is not None:
                self.fields[name].default = default

    has_vote = forms.BooleanField(required=False)
    game_id = forms.IntegerField(
        widget=forms.widgets.HiddenInput(), disabled=True
    )


def RenderVotingImpl(request, comp, voting, group, preview):
    if not preview:
        if not voting.get("open"):
            return {"error": "Голосование закрыто."}

    now = timezone.now()
    if (
        not preview
        and voting.get("start")
        and datetime.datetime.fromtimestamp(voting["start"]) > now
    ):
        start = datetime.datetime.fromtimestamp(voting["start"])
        return {
            "error": (
                "Голосование откроется %s в %02d:%02d (по Гринвичу)."
                % (FormatDate(start), start.hour, start.minute)
            )
        }

    if (
        not preview
        and voting.get("end")
        and datetime.datetime.fromtimestamp(voting["end"]) <= now
    ):
        end = datetime.datetime.fromtimestamp(voting["end"])
        return {
            "error": (
                "Голосование закрылось %s в %02d:%02d (по Гринвичу)."
                % (FormatDate(end), end.hour, end.minute)
            )
        }

    if not request.user.is_authenticated:
        return {
            "error": "Для того, чтобы проголосовать, залогиньтесь.",
            "show_signin": True,
        }

    res = {"sections": []}

    fss = []
    before = []
    for i, section in enumerate(voting.get("sections", [])):
        if group:
            fieldlist = section["groups"][group]
        else:
            fieldlist = map(lambda x: x["name"], section["fields"])

        nomination_id = section["nomination"]
        gamelist = (
            GameListEntry.objects
            .filter(gamelist__competition=comp, gamelist__id=nomination_id)
            .order_by("game__id")
            .select_related()
        )
        Fs = forms.formset_factory(VotingForm, formset=VotingFormSet, extra=0)
        initials = []
        for x in gamelist:
            initial = {}
            initial["game_id"] = x.game.id
            votes = {
                y.field: y
                for y in CompetitionVote.objects.filter(
                    competition=comp,
                    user=request.user,
                    nomination_id=nomination_id,
                    game=x.game,
                )
            }
            if votes:
                initial["has_vote"] = True
            for y in section["fields"]:
                if "default" in y:
                    initial[y["name"]] = y["default"]
                if y["name"] in votes:
                    initial[y["name"]] = votes[y["name"]].GetVal(y["type"])

            initials.append(initial)
        fs = Fs(
            request.POST or None,
            prefix="f%d" % i,
            fields=list(
                filter(lambda x: x["name"] in fieldlist, section["fields"])
            ),
            games=gamelist,
            nomination_id=nomination_id,
            initial=initials,
        )
        fss.append(fs)
        res["sections"].append(fs)
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
                if not cd["has_vote"]:
                    CompetitionVote.objects.filter(
                        competition=comp,
                        user=request.user,
                        nomination_id=fs.nomination_id,
                        field__in=fieldlist,
                        game=cd["game_id"],
                    ).delete()
                    continue

                for field in filter(
                    lambda x: x["name"] in fieldlist, fs.fields
                ):
                    try:
                        vote = CompetitionVote.objects.get(
                            competition=comp,
                            user=request.user,
                            nomination_id=fs.nomination_id,
                            game=cd["game_id"],
                            field=field["name"],
                        )
                        if vote.GetVal(field["type"]) == cd[field["name"]]:
                            continue
                    except CompetitionVote.DoesNotExist:
                        vote = CompetitionVote(
                            competition=comp,
                            user=request.user,
                            nomination_id=fs.nomination_id,
                            game_id=cd["game_id"],
                            field=field["name"],
                        )
                    vote.when = now
                    vote.SetVal(field["type"], cd[field["name"]])
                    vote.ip_addr = GetIpAddr(request)
                    vote.session = request.session.session_key
                    vote.perm = str(request.perm)
                    vote.save()
        LogAction(
            request,
            "comp-vote",
            is_mutation=True,
            obj=comp,
            before=before,
            after=after,
        )
        res["success_text"] = "Ваш голос принят."

    res["captions"] = section.get("captions", {}).get(group, {})
    return res


def DecodeTime(x):
    if x is None:
        return x
    return datetime.datetime.fromtimestamp(x)


def RenderVotingImplV2(request, comp, voting, section_name, preview):
    section = voting["sections"].get(section_name)
    if section is None:
        return {"error": "Что-то не так!"}

    captions = section.get("captions", {})

    now = timezone.now()
    if not preview:
        if not voting.get("open"):
            return {
                "error": captions.get("voting-closed", "Голосование закрыто.")
            }

        start = DecodeTime(voting.get("start"))
        if start and start > now:
            return {
                "error": (
                    captions.get(
                        "vote-will-open",
                        "Голосование откроется %s в %02d:%02d (по Гринвичу).",
                    )
                    % (FormatDate(start), start.hour, start.minute)
                )
            }

        end = DecodeTime(voting.get("end"))
        if end and end <= now:
            return {
                "error": (
                    captions.get(
                        "vote-has-closed",
                        "Голосование закрылось %s в %02d:%02d (по Гринвичу).",
                    )
                    % (FormatDate(end), end.hour, end.minute)
                )
            }

    if not request.user.is_authenticated:
        return {
            "error": captions.get(
                "login-to-vote", "Для того, чтобы проголосовать, залогиньтесь."
            ),
            "show_signin": True,
        }

    fieldlist = section["fields"]
    nomination_id = section["nomination"]
    gamelist = (
        GameListEntry.objects
        .filter(gamelist__competition=comp, gamelist__id=nomination_id)
        .order_by("game__id")
        .select_related()
    )

    initials = []
    for x in gamelist:
        initial = {}
        initial["game_id"] = x.game.id
        votes = {
            y.field: y
            for y in CompetitionVote.objects.filter(
                competition=comp,
                user=request.user,
                nomination_id=nomination_id,
                game=x.game,
                field__in=fieldlist,
            )
        }
        if votes or section.get("always_expanded"):
            initial["has_vote"] = True
        for y in voting["fields"]:
            if "default" in y:
                initial[y["name"]] = y["default"]
            if y["name"] in votes:
                initial[y["name"]] = votes[y["name"]].GetVal(y["type"])
        initials.append(initial)

    Fs = forms.formset_factory(VotingForm, formset=VotingFormSet, extra=0)
    fs = Fs(
        request.POST or None,
        prefix="voting_%d" % 0,
        fields=[x for x in voting["fields"] if x["name"] in fieldlist],
        games=gamelist,
        nomination_id=nomination_id,
        additional_label=section.get("additional_label"),
        initial=initials,
    )
    res = {}
    res["section"] = section
    res["formset"] = fs

    if request.POST and fs.is_valid():
        for f in fs:
            if not f.has_changed():
                continue
            cd = f.cleaned_data
            if not section.get("always_expanded") and not cd["has_vote"]:
                CompetitionVote.objects.filter(
                    competition=comp,
                    user=request.user,
                    nomination_id=fs.nomination_id,
                    field__in=fieldlist,
                    game=cd["game_id"],
                ).delete()
                continue
            for field in filter(lambda x: x["name"] in fieldlist, fs.fields):
                if section.get("always_expanded") and not cd[field["name"]]:
                    try:
                        CompetitionVote.objects.get(
                            competition=comp,
                            user=request.user,
                            nomination_id=fs.nomination_id,
                            game=cd["game_id"],
                            field=field["name"],
                        ).delete()
                    except CompetitionVote.DoesNotExist:
                        pass
                    continue
                try:
                    vote = CompetitionVote.objects.get(
                        competition=comp,
                        user=request.user,
                        nomination_id=fs.nomination_id,
                        game=cd["game_id"],
                        field=field["name"],
                    )
                    if vote.GetVal(field["type"]) == cd[field["name"]]:
                        continue
                except CompetitionVote.DoesNotExist:
                    vote = CompetitionVote(
                        competition=comp,
                        user=request.user,
                        nomination_id=fs.nomination_id,
                        game_id=cd["game_id"],
                        field=field["name"],
                    )
                vote.when = now
                vote.SetVal(field["type"], cd[field["name"]])
                vote.ip_addr = GetIpAddr(request)
                vote.session = request.session.session_key
                vote.perm = str(request.perm)
                vote.save()

        LogAction(
            request,
            "comp-vote",
            is_mutation=True,
            obj=comp,
            before=initials,
            after=fs.cleaned_data,
        )
        res["success_text"] = captions.get(
            "vote-accepted", "Ваш голос принят."
        )

    return res


def RenderVoting(request, comp, group, preview=False):
    options = json.loads(comp.options)
    voting = options.get("voting")
    if not voting:
        res = {"error": "В этом соревновании голосование не проводится."}
        return render_to_string("contest/voting.html", res, request=request)
    elif voting.get("version") == 2:
        res = RenderVotingImplV2(request, comp, voting, group, preview=preview)
        # import html
        # return "%s" % html.escape(repr(res))
        return render_to_string("contest/votingv2.html", res, request=request)
    else:
        res = RenderVotingImpl(request, comp, voting, group, preview=preview)
        return render_to_string("contest/voting.html", res, request=request)
