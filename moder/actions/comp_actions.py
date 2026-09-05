import json

from django.urls import reverse

from contest.models import CompetitionDocument
from contest.permissions import can_admin_competition
from moder.actions.tools import ModerAction, RegisterAction


class CompetitionAction(ModerAction):
    MODEL = CompetitionDocument


@RegisterAction
class CompetitionAdminzAction(CompetitionAction):
    TITLE = "Админка (event)"

    def GetUrl(self):
        return reverse(
            "admin:contest_competition_change", args=(self.obj.competition.id,)
        )


@RegisterAction
class CompetitionAdminPageAction(CompetitionAction):
    TITLE = "Админка (page)"

    def GetUrl(self):
        return reverse(
            "admin:contest_competitiondocument_change", args=(self.obj.id,)
        )


@RegisterAction
class CompetitionDocLink(CompetitionAction):
    TITLE = "Править текст"

    def GetUrl(self):
        return reverse("edit_compdoc", args=(self.obj.id,))

    @classmethod
    def IsAllowed(cls, request, object):
        obj = cls.EnsureObj(object)
        if obj and obj.competition:
            return can_admin_competition(request.user, obj.competition)
        return False


@RegisterAction
class CompetitionEditorLink(CompetitionAction):
    TITLE = "Править событие"

    def GetUrl(self):
        return reverse("edit_competition", args=(self.obj.competition.id,))

    @classmethod
    def IsAllowed(cls, request, object):
        obj = cls.EnsureObj(object)
        if obj and obj.competition:
            return can_admin_competition(request.user, obj.competition)
        return False


@RegisterAction
class CompetitionListLink(CompetitionAction):
    TITLE = "Править список игр"

    def GetUrl(self):
        return reverse("edit_complist", args=(self.obj.competition.id,))

    @classmethod
    def IsAllowed(cls, request, object):
        obj = cls.EnsureObj(object)
        if obj and obj.competition:
            return can_admin_competition(request.user, obj.competition)
        return False


@RegisterAction
class VotingLink(CompetitionAction):
    TITLE = "Голосование"

    def GetUrl(self):
        return reverse("view_compvotes", args=(self.obj.competition.id,))

    @classmethod
    def IsAllowed(cls, request, object):
        obj = cls.EnsureObj(object)
        if not obj or not obj.competition:
            return False
        options = json.loads(obj.competition.options)
        voting = options.get("voting")
        if not voting:
            return False
        return can_admin_competition(request.user, obj.competition)
