import json
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
        return reverse("admin:contest_competition_change",
                       args=(self.obj.competition.id, ))


@RegisterAction
class CompetitionAdminzAction(CompetitionAction):
    TITLE = 'Админка (page)'

    def GetUrl(self):
        return reverse("admin:contest_competitiondocument_change",
                       args=(self.obj.id, ))


@RegisterAction
class CompetitionDocLink(CompetitionAction):
    TITLE = 'Править текст'
    PERM = '@auth'

    def GetUrl(self):
        return reverse("edit_compdoc", args=(self.obj.id, ))

    @classmethod
    def IsAllowed(cls, request, object):
        obj = cls.EnsureObj(object)
        if obj and obj.competition and obj.competition.owner:
            return request.perm(('(o @admin [%d])' % obj.competition.owner.id))
        else:
            return request.perm(cls.PERM)


@RegisterAction
class CompetitionEditorLink(CompetitionAction):
    TITLE = 'Править событие'
    PERM = '@auth'

    def GetUrl(self):
        return reverse("edit_competition", args=(self.obj.competition.id, ))

    @classmethod
    def IsAllowed(cls, request, object):
        obj = cls.EnsureObj(object)
        if obj and obj.competition and obj.competition.owner:
            return request.perm(('(o @admin [%d])' % obj.competition.owner.id))
        else:
            return request.perm(cls.PERM)


@RegisterAction
class CompetitionListLink(CompetitionAction):
    TITLE = 'Править список игр'
    PERM = '@auth'

    def GetUrl(self):
        return reverse("edit_complist", args=(self.obj.competition.id, ))

    @classmethod
    def IsAllowed(cls, request, object):
        obj = cls.EnsureObj(object)
        if obj and obj.competition and obj.competition.owner:
            return request.perm(('(o @admin [%d])' % obj.competition.owner.id))
        else:
            return request.perm(cls.PERM)


@RegisterAction
class VotingLink(CompetitionAction):
    TITLE = 'Голосование'
    PERM = '@auth'

    def GetUrl(self):
        return reverse("view_compvotes", args=(self.obj.competition.id, ))

    @classmethod
    def IsAllowed(cls, request, object):
        obj = cls.EnsureObj(object)
        options = json.loads(obj.competition.options)
        voting = options.get('voting')
        if not voting:
            return False
        if obj and obj.competition and obj.competition.owner:
            return request.perm(('(o @admin [%d])' % obj.competition.owner.id))
        else:
            return request.perm(cls.PERM)