from moder.actions.tools import ModerAction, RegisterAction
from contest.models import CompetitionDocument
from django.urls import reverse


class CompetitionAction(ModerAction):
    PERM = '@admin'
    MODEL = CompetitionDocument


@RegisterAction
class CompetitionAdminzAction(CompetitionAction):
    TITLE = 'Админка (event)'

    def GetUrl(self):
        return reverse(
            "admin:contest_competition_change",
            args=(self.obj.competition.id, ))


@RegisterAction
class CompetitionAdminzAction(CompetitionAction):
    TITLE = 'Админка (page)'

    def GetUrl(self):
        return reverse(
            "admin:contest_competitiondocument_change", args=(self.obj.id, ))


@RegisterAction
class CompetitionEditorLink(CompetitionAction):
    TITLE = 'Править текст'

    def GetUrl(self):
        return reverse("edit_compdoc", args=(self.obj.id, ))

    @classmethod
    def IsAllowed(cls, request, object):
        if request.perm(cls.PERM):
            return True

        obj = cls.EnsureObj(object)
        if obj and obj.competition and obj.competition.owner == request.user:
            return True
        return False


@RegisterAction
class CompetitionEditorLink(CompetitionAction):
    TITLE = 'Править событие'

    def GetUrl(self):
        return reverse("edit_competition", args=(self.obj.competition.id, ))

    @classmethod
    def IsAllowed(cls, request, object):
        if request.perm(cls.PERM):
            return True

        obj = cls.EnsureObj(object)
        if obj and obj.competition and obj.competition.owner == request.user:
            return True
        return False
