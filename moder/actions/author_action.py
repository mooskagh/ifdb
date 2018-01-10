from moder.actions.tools import ModerAction, RegisterAction
from games.models import (Personality, PersonalityUrl, PersonalityAlias,
                          GameAuthor)
from django.db.models import Count
from django.template.loader import render_to_string
from django import forms
from html import escape


class AuthorAction(ModerAction):
    PERM = '@gardener'
    MODEL = Personality


@RegisterAction
class AuthorEditAction(AuthorAction):
    TITLE = 'Изменить имя и описание'

    class Form(forms.Form):
        name = forms.CharField(
            label='Имя автора',
            help_text=('Лучше всего в формате "Фамилия, Имя", тогда будет '
                       'сортировка по алфавиту хороша!'))
        bio = forms.CharField(
            required=False, label='Биография', widget=forms.Textarea)

    def GetForm(self, vars):
        return self.Form(
            vars, initial={
                'name': self.obj.name,
                'bio': self.obj.bio
            })

    def OnAction(self, action, form):
        self.obj.name = form['name']
        self.obj.bio = form['bio']
        self.obj.save()

        return {'raw': "Done!", 'buttons': [{'id': 'cancel', 'label': 'ОК!'}]}


@RegisterAction
class AliasEditAction(AuthorAction):
    TITLE = 'Редактор псевдонимов'

    class Form:
        def __init__(self, obj, var):
            self.person = obj
            self.data = []
            self.has_changes = False
            self.errors = []
            self.var = var
            for x in PersonalityAlias.objects.filter(
                    personality=obj).order_by('pk').annotate(
                        Count('gameauthor')):
                self.data.append({
                    'id': x.id,
                    'gamecount': x.gameauthor__count,
                    'alias': x.name,
                    'personality': obj.id,
                    'moveto': x.id,
                    'move_to': [],
                    'alwaysmove': False,
                    'delete': False,
                    'alwaysdelete': False,
                })

            used_aliases = set()
            if var:
                for x in self.data:
                    FIELDS = [
                        ('alias', str),
                        ('personality', int),
                        ('moveto', int),
                        ('alwaysmove', bool),
                        ('delete', bool),
                        ('alwaysdelete', bool),
                    ]
                    for y, yt in FIELDS:
                        fname = '%s%d' % (y, x['id'])
                        if fname in var:
                            try:
                                val = yt(var[fname])
                                var[fname] = val
                            except ValueError:
                                self.errors.append(
                                    "Непонятное значение [%s] для поля %s" %
                                    (var[fname], fname))
                            if x[y] != val:
                                self.has_changes = True
                                x[y] = val
                    if not x['alias']:
                        self.errors.append('Псевдоним не может быть пустым.')
                    if x['alias'] in used_aliases:
                        self.errors.append(
                            'Псевдоним [%s] используется дважды.' % x['alias'])
                    used_aliases.add(x['alias'])

            for x in self.data:
                for y in self.data:
                    x['move_to'].append({
                        'id': (y['id']),
                        'name': ('(не перемещать)'
                                 if x['id'] == y['id'] else y['alias']),
                    })

        def is_valid(self):
            self.cleaned_data = self.var
            return self.has_changes and not self.errors

        def as_form(self):
            return render_to_string('moder/aliasedit.html', {
                'items': self.data,
                'errors': self.errors,
            })

    def GetForm(self, var):
        return self.Form(self.obj, var)

    def DoAction(self, action, form, execute):
        def F(field, id):
            return form.get('%s%d' % (field, id))

        log = []
        new_pers = None
        for x in PersonalityAlias.objects.filter(personality=self.obj):
            if x.name != F('alias', x.id):
                if execute:
                    x.name = F('alias', x.id)
                    x.save()
                else:
                    log.append('[%s] будет переименован в [%s]' %
                               (x.name, F('alias', x.id)))

            if x.personality_id != F('personality', x.id):
                if F('personality', x.id):
                    if execute:
                        x.personality_id = F('personality', x.id)
                        x.save()
                    else:
                        log.append('[%s] будет присоединён к автору [%s]' %
                                   (x.name,
                                    Personality.objects.get(
                                        pk=F('personality', x.id))))
                else:
                    if execute:
                        if not new_pers:
                            new_pers = Personality()
                            new_pers.name = x.name
                            new_pers.save()
                        x.personality_id = new_pers.id
                        x.save()
                    else:
                        log.append('Для псведонима [%s] будет создана новая '
                                   'свежая страница автора.' % x.name)

            if x.id != F('moveto', x.id):
                if execute:
                    for y in GameAuthor.objects.filter(author=x.id):
                        y.author_id = x.id
                        y.save()
                else:
                    log.append('Псевдоним [%s] подмешается в [%s]' %
                               (x.name,
                                PersonalityAlias.objects.get(
                                    pk=F('moveto', x.id)).name))
                if F('alwaysmove', x.id):
                    if execute:
                        x.personality = None
                        x.hidden_for_id = F('moveto', x.id)
                        x.save()
                    else:
                        log.append('(и это будет автоматически происходить с'
                                   ' этим псевдонимом в будущем)')
                else:
                    if execute:
                        x.delete()
                        continue

            if F('delete', x.id):
                if execute:
                    if F('alwaysdelete', x.id):
                        x.personality = None
                        x.is_blacklisted = True
                        x.save()
                    else:
                        x.delete()
                else:
                    log.append('Псевдоним [%s] будет удалён' % x.name)
                    if F('alwaysdelete', x.id):
                        log.append('(и это будет автоматически происходить с'
                                   ' этим псевдонимом в будущем)')

        if execute:
            return "Done!"
        else:
            return '<br>'.join([escape(x) for x in log])


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
