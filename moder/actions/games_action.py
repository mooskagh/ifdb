import copy
from html import escape
from typing import Any

from django import forms
from django.urls import reverse
from django.utils.timezone import now

from curation.models import GameCuration
from curation.overrides import build_initial_overrides
from games.gameinfo import parse
from games.models import Game, GameAuthor, GameRevision, GameURL
from games.permissions import can_delete_game, can_edit_game
from moder.actions.tools import ModerAction, RegisterAction
from play.services import transfer_game_playables


def GenLinkButton(text, link, new_tab=False):
    return '<a href="%s"%s>%s</a>' % (
        escape(link),
        (' target="_blank"' if new_tab else ""),
        escape(text),
    )


class GameAction(ModerAction):
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

        fro_curation = getattr(fro, "curation", None)
        to_exc = (
            copy.deepcopy(fro_curation.exclude_overrides)
            if fro_curation and fro_curation.exclude_overrides
            else {}
        )
        info = parse(rev.canonical_text)
        GameCuration.objects.update_or_create(
            game=to,
            defaults={
                "state": GameCuration.State.SETTLED,
                "include_overrides": build_initial_overrides(
                    info, is_rich_source=False
                ),
                "exclude_overrides": to_exc,
            },
        )

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
        return super().IsAllowed(request, obj) and hasattr(obj, "curation")

    def GetUrl(self):
        return reverse("curation_history_detail", args=(self.obj.pk,))


@RegisterAction
class GameAdminzAction(GameAction):
    TITLE = "Админка"

    def GetUrl(self):
        return reverse("admin:games_game_change", args=(self.obj.id,))


@RegisterAction
class GameDeleteAction(GameAction):
    TITLE = "Удалить"

    class Form(forms.Form):
        keep_orphans = forms.BooleanField(
            required=False,
            initial=True,
            label="Оставить источники сиротами",
        )
        redirect_to = forms.IntegerField(
            required=False,
            min_value=1,
            label="Перенаправить на игру (id)",
            help_text="Опциональный ID игры для редиректа.",
        )

        transfer_playables = forms.BooleanField(
            required=False,
            label="Перенести онлайн-версии (Playables) на целевую игру",
        )

        def __init__(
            self,
            *args: Any,
            current_game: Game | None = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(*args, **kwargs)
            self.current_game = current_game

        def clean_redirect_to(self) -> int | None:
            target_id: int | None = self.cleaned_data.get("redirect_to")
            if not target_id:
                return None
            if self.current_game and target_id == self.current_game.pk:
                raise forms.ValidationError(
                    "Нельзя перенаправить игру на саму себя."
                )
            try:
                target_game = Game.objects.get(pk=target_id)
            except Game.DoesNotExist:
                raise forms.ValidationError(f"Игра #{target_id} не найдена.")
            if target_game.state == Game.State.ABANDONED:
                raise forms.ValidationError(
                    f"Целевая игра #{target_id} удалена."
                )

            curr: Game | None = target_game
            visited = {self.current_game.pk} if self.current_game else set()
            while curr:
                if curr.pk in visited:
                    raise forms.ValidationError(
                        "Обнаружен цикл перенаправлений."
                    )
                visited.add(curr.pk)
                if curr.state == Game.State.REDIRECT and curr.redirect_to_id:
                    curr = curr.redirect_to
                else:
                    break

            return target_id

        def clean(self) -> dict[str, Any]:
            cleaned_data = super().clean()
            target_id = cleaned_data.get("redirect_to")
            transfer = cleaned_data.get("transfer_playables")
            if self.current_game and self.current_game.playable_set.exists():
                if not target_id:
                    raise forms.ValidationError(
                        "Игру нельзя удалить, пока у неё есть Playables. "
                        "Сначала удалите или переместите их."
                    )
                if not transfer:
                    raise forms.ValidationError(
                        "У игры есть онлайн-версии (Playables). "
                        "Подтвердите их перенос чекбоксом."
                    )
            return cleaned_data

    def GetForm(self, var: Any) -> Form:
        return self.Form(var, current_game=self.obj)

    @classmethod
    def IsAllowed(cls, request, obj):
        return can_delete_game(request.user, obj)

    def DoAction(self, action, form, execute):
        redirect_id = form.get("redirect_to")
        keep_orphans = bool(form.get("keep_orphans", True))

        target_game = None
        if redirect_id:
            try:
                target_game = Game.objects.get(pk=redirect_id)
            except Game.DoesNotExist:
                pass

        if not execute:
            msg = "Удалить эту игру?"
            details = []
            if target_game:
                details.append(
                    f"Перенаправление на: #{target_game.id} "
                    f"«{target_game.title}»"
                )
            if self.obj.playable_set.exists():
                playables = list(self.obj.playable_set.all())
                slugs = ", ".join(p.slug for p in playables)
                if target_game:
                    details.append(
                        f"Онлайн-версии (Playables) будут перенесены: {slugs}"
                    )
                else:
                    details.append(
                        f"Внимание: у игры есть онлайн-версии: {slugs}"
                    )
            if keep_orphans:
                details.append("Оставить источники сиротами: да")
            else:
                details.append("Оставить источники сиротами: нет")
            return msg + "\n" + "\n".join(details)

        if target_game and self.obj.playable_set.exists():
            transfer_game_playables(self.obj, target_game)

        self.obj.abandon(
            self.request.user,
            keep_orphan=keep_orphans,
            redirect_to=target_game,
        )
        if target_game:
            return (
                f"Удалено! Настроен редирект на #{target_game.id} "
                f"«{target_game.title}»."
            )
        return "Удалено!"


@RegisterAction
class GameEditAction(GameAction):
    TITLE = "Править"

    @classmethod
    def IsAllowed(cls, request, obj):
        return can_edit_game(request.user, obj)

    def GetUrl(self):
        return reverse("edit_game", kwargs={"game_id": self.obj.id})
