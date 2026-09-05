from html import escape

from django.urls import reverse
from django.utils.timezone import now

from games.models import Game, GameAuthor, GameRevision, GameURL
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
class GameCloneAction(GameAction):
    TITLE = "Клонировать"

    def DoAction(self, action, form, execute):
        if not execute:
            return "Клонировать эту игру?"

        fro = self.obj
        to = Game(state=Game.State.PUBLISHED)
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

        canonical_text = (
            fro.published_revision.canonical_text
            if fro.published_revision
            else f'---\n- name: "{to.title}"\n---\n{to.description or ""}'
        )
        rev = GameRevision(
            game=to,
            created_at=now(),
            created_by=self.request.user,
            origin=GameRevision.Origin.CLONE,
            canonical_text=canonical_text,
        )
        to.publish_revision(rev, actor=self.request.user)

        return GenLinkButton(
            "Ссылка на клон",
            reverse("show_game", kwargs={"game_id": to.id}),
            True,
        )


@RegisterAction
class GameCurationAction(GameAction):
    TITLE = "Модерация"

    @classmethod
    def IsAllowed(cls, request, obj):
        return super().IsAllowed(request, obj) and hasattr(obj, "gamehistory")

    def GetUrl(self):
        return reverse(
            "curation_history_detail", args=(self.obj.gamehistory.pk,)
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
            self.obj.abandon(self.request.user)
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
