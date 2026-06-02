from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils.timezone import now

from games.models import Game

from . import edit
from .edit import Approval, GameEditPass, run_edit
from .gameinfo import Tag
from .models import GameEdit, GameHistory, GameHistoryAuditLog


class _TagAndApprove(GameEditPass):
    """Throwaway pass: append a known tag and force an approval status."""

    name = "tag_and_approve"

    def __init__(self, approval: Approval):
        self.approval = approval

    def apply(self, state, params):
        state.current.tags.append(
            Tag("os", params.get("tag", "os_win"), None, None)
        )
        state.approval = self.approval


class RunEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def _history(self):
        game = Game.objects.create(title="A Game", creation_time=now())
        return GameHistory.objects.create(
            game=game,
            state=GameHistory.State.IN_PROGRESS,
            creation_time=now(),
        )

    def _run_with(self, passes, history, specs=None):
        registry = {p.name: p for p in passes}
        specs = specs if specs is not None else [p.name for p in passes]
        with (
            mock.patch.object(edit, "PASS_REGISTRY", registry),
            override_settings(CURATION_EDIT_PASSES=specs),
        ):
            return run_edit(history_id=history.pk)

    def _has_os_win(self, game):
        return game.tags.filter(symbolic_id="os_win").exists()

    # -- tests ------------------------------------------------------------

    def test_applied_writes_game_audit_and_settles(self):
        history = self._history()

        stats = self._run_with([_TagAndApprove(Approval.APPLIED)], history)

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        edit_row = GameEdit.objects.get(history=history)
        self.assertEqual(edit_row.status, GameEdit.EditStatus.APPLIED)
        self.assertEqual(edit_row.passes, [{"name": "tag_and_approve"}])
        self.assertIsNotNone(edit_row.previous_canonical_text)
        self.assertIn("A Game", edit_row.previous_canonical_text)
        self.assertIsNotNone(edit_row.approved_at)
        self.assertTrue(self._has_os_win(history.game))
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                history=history,
                field=GameHistoryAuditLog.AuditField.CANONICAL_TEXT,
            ).exists()
        )

    def test_proposed_needs_attention_game_untouched(self):
        history = self._history()

        stats = self._run_with([_TagAndApprove(Approval.PROPOSED)], history)

        self.assertEqual(stats.proposed, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(
            (edit_row := GameEdit.objects.get(history=history)).status,
            GameEdit.EditStatus.PROPOSED,
        )
        self.assertIsNone(edit_row.previous_canonical_text)
        self.assertFalse(self._has_os_win(history.game))

    def test_rejected_settles_with_edit_game_untouched(self):
        history = self._history()

        stats = self._run_with([_TagAndApprove(Approval.REJECTED)], history)

        self.assertEqual(stats.rejected, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(
            (edit_row := GameEdit.objects.get(history=history)).status,
            GameEdit.EditStatus.REJECTED,
        )
        self.assertIsNotNone(edit_row.previous_canonical_text)
        self.assertIn("A Game", edit_row.previous_canonical_text)
        self.assertFalse(self._has_os_win(history.game))

    def test_cancelled_settles_without_edit(self):
        history = self._history()

        stats = self._run_with([_TagAndApprove(Approval.CANCELLED)], history)

        self.assertEqual(stats.cancelled, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertFalse(GameEdit.objects.filter(history=history).exists())
        self.assertFalse(self._has_os_win(history.game))

    def test_noop_settles_unchanged_without_edit(self):
        history = self._history()

        stats = self._run_with([], history)

        self.assertEqual(stats.unchanged, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertFalse(GameEdit.objects.filter(history=history).exists())

    def test_pass_params_are_applied_and_recorded(self):
        history = self._history()

        self._run_with(
            [_TagAndApprove(Approval.APPLIED)],
            history,
            [{"name": "tag_and_approve", "tag": "os_dos"}],
        )

        edit_row = GameEdit.objects.get(history=history)
        self.assertEqual(
            edit_row.passes, [{"name": "tag_and_approve", "tag": "os_dos"}]
        )
        self.assertTrue(
            history.game.tags.filter(symbolic_id="os_dos").exists()
        )
