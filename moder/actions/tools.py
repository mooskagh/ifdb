import json
from django.http.response import JsonResponse
from logging import getLogger
from django.template.loader import render_to_string

logger = getLogger('web')

BUTTON_LABELS = {
    'ok': 'OK',
    'cancel': 'Отменить',
}


class ModerAction:
    TITLE = '(no title)'
    ICON = None
    PERM = '@admin'
    MODEL = None
    BUTTONS = ['ok', 'cancel']
    BUTTONS_NEED_FORM = {'ok'}

    def __init__(self, request, obj):
        self.request = request
        self.obj = obj
        self.state = {}

    def GetForm(self, val):
        return None

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

    def OnAction(self, action, form):
        execute = 'form' in self.state
        buttons = []
        if execute:
            form = self.state['form']
            buttons = [{'id': 'cancel', 'label': 'ОК!'}]
        else:
            self.state['form'] = form
            buttons = [{
                'id': 'ok',
                'label': 'ОК'
            }, {
                'id': 'cancel',
                'label': 'Cancel'
            }]
        return {
            'raw': self.DoAction(action, form, execute),
            'buttons': buttons
        }

    def DoAction(self, action, form, execute):
        return "(no action defined: %s, Execute:%s)" % (action, execute)

    def Handle(self, form, action):
        if (action == 'cancel'):
            return None

        f = self.GetForm(form if action else None)
        buttons = []
        override = {}
        rendered_form = ''
        if 'form' not in self.state and f and not f.is_valid() and (
                not action or action in self.BUTTONS_NEED_FORM):
            for x in self.BUTTONS:
                buttons.append({'id': x, 'label': BUTTON_LABELS[x]})

            if f:
                if hasattr(f, 'as_form'):
                    rendered_form = f.as_form()
                else:
                    rendered_form = (
                        '<table class="moder-form-table">%s</table>' %
                        f.as_table())
        else:
            if f and f.is_valid():
                form_data = f.cleaned_data
            else:
                form_data = {}
            override = self.OnAction(action, form_data)

        return render_to_string('moder/moder.html', {
            'raw': None,
            'form': rendered_form,
            'buttons': buttons,
            **
            override,
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


ACTIONS = []


def RegisterAction(cls):
    ACTIONS.append(cls)
    return cls


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
#     error: (if error)


def HandleAction(request):
    j = json.loads(request.POST.get('request'))
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
    try:
        content = action.Handle(form=j.get('form', {}), action=j.get('action'))
    except Exception as e:
        logger.exception("Error while running moder action")
        return JsonResponse({'error': str(e)})

    return JsonResponse({
        'object': object,
        'state': action.GetState(),
        'content': content,
    })
