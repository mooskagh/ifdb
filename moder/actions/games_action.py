from html import escape

from django import forms
from django.urls import reverse

from core.models import Package
from games.models import Game, GameAuthor, GameComment, GameURL, GameVote
from moder.actions.tools import ModerAction, RegisterAction


def GenLinkButton(text, link, new_tab=False):
    return '<a href="%s"%s>%s</a>' % (
        escape(link),
        (' target="_blank"' if new_tab else ""),
        escape(text),
    )


class GameAction(ModerAction):
    PERM = "@gardener"
    MODEL = Game


@RegisterAction
class GameCombineAction(GameAction):
    TITLE = "Объединить"

    class Form(forms.Form):
        other_game = forms.IntegerField(
            label="С какой игрой объединять? (id)",
            min_value=1,
            help_text=(
                "Все данные из указанной игры будут скопированы в эту, "
                "а сама та игра будет удалена"
            ),
        )

    def GetForm(self, var):
        return self.Form(var)

    def DoAction(self, action, form, execute):
        fro = Game.objects.get(pk=form["other_game"])
        if execute:
            to = self.obj
            if not to.release_date:
                to.release_date = fro.release_date

            desc = ""
            for x in [to.description, fro.description]:
                val = x or ""
                if desc and val:
                    desc += "\n\n"
                desc += val
            to.description = desc
            to.save()

            to.tags.add(*fro.tags.all())

            for y in [GameURL, GameAuthor, GameVote, GameComment, Package]:
                for x in y.objects.filter(game=fro):
                    x.game = to
                    x.save()

            fro.delete()

            urls = set()
            for y in GameURL.objects.filter(game=to):
                v = (y.url_id, y.category_id)
                if v in urls:
                    y.delete()
                else:
                    urls.add(v)

            authors = set()
            for y in GameAuthor.objects.filter(game=to).select_related():
                v = (y.role_id, y.author.personality_id)
                if v in authors:
                    y.delete()
                else:
                    authors.add(v)

            return "Done!"
        else:
            return "Будем объединять с: %s" % fro


@RegisterAction
class GameCloneAction(GameAction):
    TITLE = "Клонировать"

    def DoAction(self, action, form, execute):
        if not execute:
            return "Клонировать эту игру?"

        fro = self.obj
        to = Game()
        for field in [
            "title",
            "description",
            "release_date",
            "creation_time",
            "view_perm",
            "edit_perm",
            "comment_perm",
            "delete_perm",
            "vote_perm",
            "added_by",
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

        return GenLinkButton(
            "Ссылка на клон",
            reverse("show_game", kwargs={"game_id": to.id}),
            True,
        )


@RegisterAction
class GameAdminzAction(GameAction):
    PERM = "@admin"
    TITLE = "Админка"

    def GetUrl(self):
        return reverse("admin:games_game_change", args=(self.obj.id,))


@RegisterAction
class GameDeleteAction(GameAction):
    TITLE = "Удалить"

    @classmethod
    def IsAllowed(cls, request, obj):
        return request.perm(obj.delete_perm)

    def DoAction(self, action, form, execute):
        if execute:
            self.obj.delete()
            return "Удалено!"
        else:
            return "Удалить эту игру?"


@RegisterAction
class GameEditAction(GameAction):
    TITLE = "Править"

    @classmethod
    def IsAllowed(cls, request, obj):
        return request.perm(obj.edit_perm)

    def GetUrl(self):
        return reverse("edit_game", kwargs={"game_id": self.obj.id})
