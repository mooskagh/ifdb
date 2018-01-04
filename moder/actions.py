from django.urls import reverse


class ModerAction:
    TITLE = '(no title)'
    ICON = None
    PERM = '@admin'

    def __init__(self, request, obj):
        self.request = request
        self.obj = obj

    def GetIcon(self):
        return self.ICON

    def GetUrl(self):
        return None

    def GetTitle(self):
        return self.TITLE

    @classmethod
    def IsAllowed(cls, request, object):
        return request.perm(cls.PERM)


class GameEditAction(ModerAction):
    TITLE = 'Править'
    ICON = 'svg/edit.svg'

    @classmethod
    def IsAllowed(cls, request, obj):
        return request.perm(obj.edit_perm)

    def GetUrl(self):
        return reverse('edit_game', kwargs={'game_id': self.obj.id})


class GameCloneAction(ModerAction):
    TITLE = 'Клонировать'


GAMES_ACTIONS = [
    #    GameCloneAction,
    GameEditAction,
]

CONTEXTS = {
    'Game': GAMES_ACTIONS,
}


def GetModerActions(request, context, obj=None):
    res = []
    for x in CONTEXTS[context]:
        if x.IsAllowed(request, obj):
            res.append(x(request, obj))

    return res
