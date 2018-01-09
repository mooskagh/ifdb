from moder.actions.tools import ModerAction, RegisterAction
from games.models import Personality, PersonalityUrl, PersonalityAlias
from django import forms


class AuthorAction(ModerAction):
    PERM = '@gardener'
    MODEL = Personality


@RegisterAction
class AuthorCombineAction(AuthorAction):
    TITLE = 'Объединить'

    class Form(forms.Form):
        other_pers = forms.IntegerField(
            label='С каким автором объединять? (id)',
            min_value=1,
            help_text='Все псевдонимы и игры того автора будут скопированы '
            'сюда, и тот автор будет удалён.')

    def GetForm(self, var):
        return self.Form(var)

    def DoAction(self, action, form, execute):
        fro = Personality.objects.get(pk=form['other_pers'])
        if not execute:
            return "Будем объединять с %s " % fro
        to = self.obj
        newbio = to.bio or ''
        newbio += fro.bio or ''
        if newbio:
            to.bio = newbio
        to.save()

        for y in [PersonalityUrl, PersonalityAlias]:
            for x in y.objects.filter(personality=fro):
                x.personality = to
                x.save()

        fro.delete()
        return "Done!"


@RegisterAction
class AuthorDeleteAction(AuthorAction):
    TITLE = 'Удалить'

    @classmethod
    def IsAllowed(cls, request, obj):
        return request.perm(obj.edit_perm)

    def DoAction(self, action, form, execute):
        if execute:
            self.obj.delete()
            return "Удалено!"
        else:
            return "Удалить этого автора?"
