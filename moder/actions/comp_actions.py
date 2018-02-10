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