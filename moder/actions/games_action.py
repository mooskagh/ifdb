from games.models import Game, GameURL, GameAuthor
from django.urls import reverse
from html import escape

from moder.actions.tools import ModerAction, RegisterAction


def GenLinkButton(text, link, new_tab=False):
    return '<a href="%s"%s>%s</a>' % (escape(link), (' target="_blank"'
                                                     if new_tab else ''),
                                      escape(text))


class GameAction(ModerAction):
    MODEL = Game


@RegisterAction
class GameCloneAction(GameAction):
    TITLE = 'Клонировать'
    LINES = 'Клонировать эту игру?'

    def OnAction(self, action, form):
        fro = self.obj
        to = Game()
        for field in [
                'title', 'description', 'release_date', 'creation_time',
                'view_perm', 'edit_perm', 'comment_perm', 'delete_perm',
                'vote_perm', 'added_by'
        ]:
            setattr(to, field, getattr(fro, field))
        to.save()
        to.tags.add(*fro.tags.all())

        for x in GameURL.objects.filter(game=fro):
            x.pk = None
            x.game = to
            x.save()

            # TODO(crem) Interpreted game url

        for x in GameAuthor.objects.filter(game=fro):
            x.pk = None
            x.game = to
            x.save()

        return GenLinkButton('Ссылка на клон',
                             reverse('show_game', kwargs={
                                 'game_id': to.id
                             }), True)


@RegisterAction
class GameAdminzAction(GameAction):
    TITLE = 'Админка'

    def GetUrl(self):
        return reverse("admin:games_game_change", args=(self.obj.id, ))


@RegisterAction
class GameEditAction(GameAction):
    TITLE = 'Править'
    ICON = 'svg/edit.svg'

    @classmethod
    def IsAllowed(cls, request, obj):
        return request.perm(obj.edit_perm)

    def GetUrl(self):
        return reverse('edit_game', kwargs={'game_id': self.obj.id})


@RegisterAction
class GameDeleteAction(GameAction):
    TITLE = 'Удалить'
    LINES = 'Удалить эту игру?'

    @classmethod
    def IsAllowed(cls, request, obj):
        return request.perm(obj.delete_perm)

    def OnAction(self, action, form):
        self.obj.delete()
        return "Удалено!"
