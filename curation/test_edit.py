from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils.timezone import now

from games.models import (
    Game,
    GameAuthorRole,
    GameDescriptionAttribution,
    GameTag,
    GameTagCategory,
    GameURLCategory,
    PersonalityAlias,
)

from . import edit
from .edit import Approval, GameEditPass, run_edit
from .gameinfo import Person, Tag
from .manual import store_manual_edit
from .models import (
    GameEdit,
    GameHistory,
    GameHistoryAuditLog,
    GameSource,
    GameSourceFetch,
)


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


class _AddNamedPerson(GameEditPass):
    name = "add_named_person"

    def apply(self, state, params):
        state.current.personalities.setdefault("author", []).append(
            Person(None, params["person_name"])
        )


class _AssertResolvedPerson(GameEditPass):
    name = "assert_resolved_person"

    def apply(self, state, params):
        self.seen = state.current.personalities["author"][-1]


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

    def test_canonicalizes_after_each_pass(self):
        history = self._history()
        alias = PersonalityAlias.objects.create(name="Known Author")
        observer = _AssertResolvedPerson()

        self._run_with(
            [_AddNamedPerson(), observer, _TagAndApprove(Approval.CANCELLED)],
            history,
            [
                {"name": "add_named_person", "person_name": "Known Author"},
                {"name": "assert_resolved_person"},
                {"name": "tag_and_approve"},
            ],
        )

        self.assertEqual(observer.seen, Person(alias.id, ""))


class ManualEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def _payload(self):
        role = GameAuthorRole.objects.get(symbolic_id="author")
        alias = PersonalityAlias.objects.create(name="Manual Author")
        cat = GameTagCategory.objects.get(symbolic_id="genre")
        tag = GameTag.objects.filter(category=cat).first()
        urlcat = GameURLCategory.objects.get(symbolic_id="game_page")
        attr = GameDescriptionAttribution.objects.create(name="manual source")
        return {
            "title": "New Title",
            "desc": "New description",
            "release_date": "2020-01-02",
            "authors": [[role.id, alias.id]],
            "tags": [[cat.id, tag.id]],
            "links": [[urlcat.id, "Homepage", "https://example.com/game"]],
            "description_attributions": [attr.name],
        }

    def _history_with_source(self, game):
        history = GameHistory.objects.create(game=game, creation_time=now())
        source = GameSource.objects.create(
            history=history,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/wiki",
        )
        fetch = GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            canonical_text="---\n- name: Old Title\n---\nOld description",
            canonical_text_hash="hash",
            first_fetch=now(),
            last_fetch=now(),
        )
        applied = GameEdit.objects.create(
            history=history,
            proposed_at=now(),
            approved_at=now(),
            status=GameEdit.EditStatus.APPLIED,
            origin=GameEdit.Origin.AUTO_IMPORT,
            canonical_text=fetch.canonical_text,
        )
        applied.used_sources.add(fetch)
        return history, fetch

    def test_apply_updates_game_and_records_history(self):
        game = Game.objects.create(title="Old Title", creation_time=now())
        history, fetch = self._history_with_source(game)

        edit_row = store_manual_edit(game, self._payload(), None, apply=True)

        game.refresh_from_db()
        history.refresh_from_db()
        self.assertEqual(game.title, "New Title")
        self.assertEqual(game.description, "New description")
        self.assertEqual(game.release_date.isoformat(), "2020-01-02")
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(edit_row.status, GameEdit.EditStatus.APPLIED)
        self.assertEqual(edit_row.origin, GameEdit.Origin.MANUAL_EDIT)
        self.assertEqual(list(edit_row.used_sources.all()), [fetch])
        self.assertIn("manual source", edit_row.canonical_text)
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                history=history,
                field=GameHistoryAuditLog.AuditField.CANONICAL_TEXT,
            ).exists()
        )

    def test_propose_creates_attention_edit_without_changing_game(self):
        game = Game.objects.create(title="Old Title", creation_time=now())
        history, fetch = self._history_with_source(game)

        edit_row = store_manual_edit(game, self._payload(), None, apply=False)

        game.refresh_from_db()
        history.refresh_from_db()
        self.assertEqual(game.title, "Old Title")
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(
            history.attention_reason, "Пользователь предложил правку"
        )
        self.assertEqual(edit_row.status, GameEdit.EditStatus.PROPOSED)
        self.assertEqual(edit_row.origin, GameEdit.Origin.USER_SUGGESTION)
        self.assertIsNone(edit_row.previous_canonical_text)
        self.assertEqual(list(edit_row.used_sources.all()), [fetch])
        self.assertIn("New Title", edit_row.canonical_text)
        self.assertIn("manual source", edit_row.canonical_text)
