import json
from django.urls import reverse
from django.http.response import JsonResponse
from games.models import Game
from django.template.loader import render_to_string

BUTTON_LABELS = {
    'ok': 'OK',
    'cancel': 'Отменить',
}


class ModerAction:
    TITLE = '(no title)'
    ICON = None
    PERM = '@admin'
    MODEL = None
    LINES = []
    FORM = None
    BUTTONS = ['ok', 'cancel']

    def __init__(self, request, obj):
        self.request = request
        self.obj = obj
        self.state = {}

    def GetIcon(self):
        return self.ICON

    def GetUrl(self):
        return None

    def GetTitle(self):
        return self.TITLE

    def GetObjId(self):
        if self.obj:
            return self.obj.id
        else:
            return ''

    def Handle(self, form, action):
        if (action == 'cancel'):
            return None
        buttons = []
        for x in self.BUTTONS:
            buttons.append({'id': x, 'label': BUTTON_LABELS[x]})

        lines = self.LINES
        if isinstance(lines, str):
            lines = [lines]

        return render_to_string('moder/moder.html', {
            'lines': lines,
            'buttons': buttons,
        })

    def SetState(self, state):
        self.state = state

    def GetState(self):
        return self.state

    @classmethod
    def GetClassName(cls):
        return cls.__name__

    @classmethod
    def GetContext(cls):
        return cls.MODEL.__name__

    @classmethod
    def IsAllowed(cls, request, object):
        return request.perm(cls.PERM)

    @classmethod
    def EnsureObj(cls, obj):
        if isinstance(obj, int):
            return cls.MODEL.objects.get(pk=obj)
        else:
            return obj


class GameAction(ModerAction):
    MODEL = Game


class GameEditAction(GameAction):
    TITLE = 'Править'
    ICON = 'svg/edit.svg'

    @classmethod
    def IsAllowed(cls, request, obj):
        return request.perm(obj.edit_perm)

    def GetUrl(self):
        return reverse('edit_game', kwargs={'game_id': self.obj.id})


class GameCloneAction(GameAction):
    TITLE = 'Клонировать'
    LINES = 'Клонировать эту игру?'


class GameAdminzAction(GameAction):
    TITLE = 'Админка'

    def GetUrl(self):
        return reverse("admin:games_game_change", args=(self.obj.id, ))


ACTIONS = [
    GameAdminzAction,
    #GameCloneAction,
    GameEditAction,
]


def GetModerActions(request, context, obj=None):
    res = []
    for x in ACTIONS:
        if x.GetContext() == context and x.IsAllowed(request, obj):
            res.append(x(request, obj))

    return res


# In:
#     object: {ctx, cls, obj}
#     state: {} // the same obj as in IN
#     form: {key: value}
#     action: 'button-name'

# Out:
#     object: {ctx, cls, obj}
#     state: {}  // any obj
#     content: 'lines + form + buttons' or undefined, which means close snippet


def HandleAction(request):
    j = json.loads(request.POST.get('request'))
    print(j)
    object = j['object']

    action = None
    for x in ACTIONS:
        if (x.GetContext() == object['ctx']
                and x.GetClassName() == object['cls']):
            obj = x.EnsureObj(object.get('obj'))
            if not x.IsAllowed(request, obj):
                continue
            action = x
            break
    if not action:
        return JsonResponse({})

    action = action(request, obj)
    action.SetState(j.get('state', {}))
    content = action.Handle(form=j.get('form', {}), action=j.get('action'))

    return JsonResponse({
        'object': object,
        'state': action.GetState(),
        'content': content,
    })
