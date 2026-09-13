import json
from typing import Any

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils.timezone import now

from core.models import User
from curation.models import GameCuration, GameHistoryAuditLog, GameSource
from games.models import Game, GameRevision
from moder.actions.games_action import GameDeleteAction


class GameDeleteActionTest(TestCase):
    def setUp(self) -> None:
        self.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secretpassword",
        )
        self.game = self._create_game("Source Game")
        self.target_game = self._create_game("Target Game")
        self.factory = RequestFactory()

    def _create_game(
        self,
        title: str,
        state: Game.State = Game.State.PUBLISHED,
        redirect_to: Game | None = None,
    ) -> Game:
        game = Game.objects.create(
            title=title,
            creation_time=now(),
            state=state,
            redirect_to=redirect_to,
        )
        if state == Game.State.PUBLISHED:
            rev = GameRevision.objects.create(
                game=game,
                created_at=now(),
                published_at=now(),
                status=GameRevision.Status.ACCEPTED,
                origin=GameRevision.Origin.MANUAL_EDIT,
                canonical_text=f'---\n- name: "{title}"\n---\n',
            )
            game.published_revision = rev
            game.save(update_fields=["published_revision"])
        GameCuration.objects.create(
            game=game, state=GameCuration.State.SETTLED
        )
        return game

    def test_form_initial_and_validation(self) -> None:
        form = GameDeleteAction.Form(current_game=self.game)
        self.assertTrue(form.fields["keep_orphans"].initial)
        self.assertFalse(form.fields["keep_orphans"].required)
        self.assertFalse(form.fields["redirect_to"].required)

        # Unchecked checkbox and empty redirect
        bound_empty = GameDeleteAction.Form({}, current_game=self.game)
        self.assertTrue(bound_empty.is_valid())
        self.assertFalse(bound_empty.cleaned_data["keep_orphans"])
        self.assertIsNone(bound_empty.cleaned_data["redirect_to"])

        # Checked checkbox and valid redirect
        bound_valid = GameDeleteAction.Form(
            {"keep_orphans": "on", "redirect_to": str(self.target_game.id)},
            current_game=self.game,
        )
        self.assertTrue(bound_valid.is_valid())
        self.assertTrue(bound_valid.cleaned_data["keep_orphans"])
        self.assertEqual(
            bound_valid.cleaned_data["redirect_to"], self.target_game.id
        )

        # Self redirect rejected
        self_bound = GameDeleteAction.Form(
            {"redirect_to": str(self.game.id)},
            current_game=self.game,
        )
        self.assertFalse(self_bound.is_valid())
        self.assertIn("redirect_to", self_bound.errors)
        self.assertIn("на саму себя", self_bound.errors["redirect_to"][0])

        # Non-existent redirect rejected
        missing_bound = GameDeleteAction.Form(
            {"redirect_to": "999999"},
            current_game=self.game,
        )
        self.assertFalse(missing_bound.is_valid())
        self.assertIn("redirect_to", missing_bound.errors)
        self.assertIn("не найдена", missing_bound.errors["redirect_to"][0])

        # Abandoned redirect target rejected
        abandoned_target = self._create_game(
            "Abandoned Target", state=Game.State.ABANDONED
        )
        abandoned_bound = GameDeleteAction.Form(
            {"redirect_to": str(abandoned_target.id)},
            current_game=self.game,
        )
        self.assertFalse(abandoned_bound.is_valid())
        self.assertIn("redirect_to", abandoned_bound.errors)
        self.assertIn("удалена", abandoned_bound.errors["redirect_to"][0])

        # Cycle redirect rejected
        cycle_game = self._create_game(
            "Cycle Game",
            state=Game.State.REDIRECT,
            redirect_to=self.game,
        )
        cycle_bound = GameDeleteAction.Form(
            {"redirect_to": str(cycle_game.id)},
            current_game=self.game,
        )
        self.assertFalse(cycle_bound.is_valid())
        self.assertIn("redirect_to", cycle_bound.errors)
        self.assertIn("цикл", cycle_bound.errors["redirect_to"][0])

    def test_do_action_delete_without_redirect_keeps_orphans(self) -> None:
        source = GameSource.objects.create(
            game=self.game,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/source",
        )
        request = self.factory.post("/")
        request.user = self.superuser

        action = GameDeleteAction(request, self.game)
        preview = action.DoAction(
            "ok", {"keep_orphans": True, "redirect_to": None}, execute=False
        )
        self.assertIn("Удалить эту игру?", preview)
        self.assertIn("Оставить источники сиротами: да", preview)

        result = action.DoAction(
            "ok", {"keep_orphans": True, "redirect_to": None}, execute=True
        )
        self.assertEqual(result, "Удалено!")

        self.game.refresh_from_db()
        self.assertEqual(self.game.state, Game.State.ABANDONED)
        self.assertIsNone(self.game.redirect_to)

        source.refresh_from_db()
        self.assertIsNone(source.game)
        self.assertTrue(source.keep_orphan)

    def test_do_action_delete_without_redirect_discards_orphans(self) -> None:
        source = GameSource.objects.create(
            game=self.game,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/source",
        )
        request = self.factory.post("/")
        request.user = self.superuser

        action = GameDeleteAction(request, self.game)
        result = action.DoAction(
            "ok", {"keep_orphans": False, "redirect_to": None}, execute=True
        )
        self.assertEqual(result, "Удалено!")

        self.game.refresh_from_db()
        self.assertEqual(self.game.state, Game.State.ABANDONED)

        source.refresh_from_db()
        self.assertIsNone(source.game)
        self.assertFalse(source.keep_orphan)

    def test_do_action_delete_with_redirect(self) -> None:
        source = GameSource.objects.create(
            game=self.game,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/source",
        )
        request = self.factory.post("/")
        request.user = self.superuser

        action = GameDeleteAction(request, self.game)
        preview = action.DoAction(
            "ok",
            {"keep_orphans": True, "redirect_to": self.target_game.id},
            execute=False,
        )
        self.assertIn(f"Перенаправление на: #{self.target_game.id}", preview)

        result = action.DoAction(
            "ok",
            {"keep_orphans": True, "redirect_to": self.target_game.id},
            execute=True,
        )
        self.assertIn(f"редирект на #{self.target_game.id}", result)

        self.game.refresh_from_db()
        self.assertEqual(self.game.state, Game.State.REDIRECT)
        self.assertEqual(self.game.redirect_to, self.target_game)

        source.refresh_from_db()
        self.assertIsNone(source.game)
        self.assertTrue(source.keep_orphan)

        # GameHistoryAuditLog recorded merge/redirect
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=self.game,
                kind=GameHistoryAuditLog.AuditKind.GAME_MERGED,
                old_id=self.game.id,
                new_id=self.target_game.id,
            ).exists()
        )

        # Public show_game redirects to target game
        response = self.client.get(reverse("show_game", args=[self.game.id]))
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            reverse("show_game", args=[self.target_game.id]),
        )

    def test_json_action_full_flow(self) -> None:
        self.client.force_login(self.superuser)

        # 1. Initial click returns form
        payload: dict[str, Any] = {
            "object": {
                "ctx": "Game",
                "cls": "GameDeleteAction",
                "obj": self.game.id,
            },
            "state": {},
            "form": {},
            "action": {},
        }
        resp = self.client.post(
            reverse("handle_action"),
            {"request": json.dumps(payload)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("content", data)
        self.assertIn("Оставить источники сиротами", data["content"])
        self.assertIn('name="keep_orphans"', data["content"])
        self.assertIn('name="redirect_to"', data["content"])

        # 2. Submit form with invalid target game -> returns form with error
        payload = {
            "object": data["object"],
            "state": data["state"],
            "form": {
                "keep_orphans": "on",
                "redirect_to": "999999",
            },
            "action": "ok",
        }
        resp = self.client.post(
            reverse("handle_action"),
            {"request": json.dumps(payload)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("не найдена", data["content"])

        # 3. Submit form with valid target game -> returns confirmation preview
        payload["form"]["redirect_to"] = str(self.target_game.id)
        resp = self.client.post(
            reverse("handle_action"),
            {"request": json.dumps(payload)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("Удалить эту игру?", data["content"])
        self.assertIn(
            f"Перенаправление на: #{self.target_game.id}", data["content"]
        )

        # 4. Confirm deletion
        payload = {
            "object": data["object"],
            "state": data["state"],
            "form": {},
            "action": "ok",
        }
        resp = self.client.post(
            reverse("handle_action"),
            {"request": json.dumps(payload)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("Удалено!", data["content"])

        self.game.refresh_from_db()
        self.assertEqual(self.game.state, Game.State.REDIRECT)
        self.assertEqual(self.game.redirect_to, self.target_game)
