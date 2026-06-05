from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
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
    EditPipeline,
    GameEdit,
    GameHistory,
    GameSource,
    GameSourceFetch,
    LLMModel,
    LlmTrajectory,
    LlmWorkflow,
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


class _Note(GameEditPass):
    name = "note"

    def apply(self, state, params):
        state.add_note(params.get("note", "Needs review"))


class _NeedsAttention(GameEditPass):
    name = "needs_attention"

    def apply(self, state, params):
        state.needs_attention = True


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


class _CreateTrajectory(GameEditPass):
    name = "create_trajectory"

    def apply(self, state, params):
        model = LLMModel.objects.create(
            name="test/model",
            context_length=1000,
            input_cost=1,
            cached_input_cost=0,
            cache_write_cost=0,
            output_cost=1,
        )
        workflow = LlmWorkflow.objects.create(
            name="test_workflow",
            runner="test_runner",
            prompt_template="Prompt",
            model=model,
        )
        LlmTrajectory.objects.create(
            history=state.history,
            workflow=workflow,
            model=model,
            created_at=now(),
            messages=[],
            cost="0.000000",
        )


class _SetDescription(GameEditPass):
    name = "set_description"

    def apply(self, state, params):
        state.current.description = params["description"]


class _Fail(GameEditPass):
    name = "fail"

    def apply(self, state, params):
        raise RuntimeError("boom")


class RunEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def _history(self):
        game = Game.objects.create(title="A Game", creation_time=now())
        return GameHistory.objects.create(
            game=game,
            state=GameHistory.State.SCHEDULED_FOR_UPDATE,
            creation_time=now(),
        )

    def _run_with(self, passes, history, specs=None):
        registry = {p.name: p for p in passes}
        specs = specs if specs is not None else [p.name for p in passes]
        pipeline = EditPipeline.objects.create(name="Test", passes=specs)
        with mock.patch.object(edit, "PASS_REGISTRY", registry):
            return run_edit(history_id=history.pk, pipeline_id=pipeline.pk)

    def _has_os_win(self, game):
        return game.tags.filter(symbolic_id="os_win").exists()

    # -- tests ------------------------------------------------------------

    def test_applied_writes_game_and_settles(self):
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
        self.assertEqual(
            edit_row.proposed_by.username, settings.MAINTENANCE_USER
        )
        self.assertEqual(edit_row.approver.username, settings.MAINTENANCE_USER)
        self.assertTrue(self._has_os_win(history.game))

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
        self.assertEqual(
            edit_row.proposed_by.username, settings.MAINTENANCE_USER
        )
        self.assertIsNone(edit_row.approver)
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

    def test_rejected_with_note_settles_and_preserves_note(self):
        history = self._history()

        stats = self._run_with(
            [_Note(), _TagAndApprove(Approval.REJECTED)], history
        )

        self.assertEqual(stats.rejected, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(history.note, "Needs review")
        self.assertEqual(
            GameEdit.objects.get(history=history).status,
            GameEdit.EditStatus.REJECTED,
        )
        self.assertFalse(self._has_os_win(history.game))

    def test_rejected_with_needs_attention_sets_attention(self):
        history = self._history()

        stats = self._run_with(
            [_Note(), _NeedsAttention(), _TagAndApprove(Approval.REJECTED)],
            history,
        )

        self.assertEqual(stats.rejected, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(history.note, "Needs review")

    def test_applied_with_needs_attention_commits_and_sets_attention(self):
        history = self._history()

        stats = self._run_with(
            [_Note(), _NeedsAttention(), _TagAndApprove(Approval.APPLIED)],
            history,
        )

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(history.note, "Needs review")
        self.assertTrue(self._has_os_win(history.game))
        self.assertEqual(
            GameEdit.objects.get(history=history).status,
            GameEdit.EditStatus.APPLIED,
        )

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

    def test_processing_history_is_not_claimed_again(self):
        history = self._history()
        history.state = GameHistory.State.PROCESSING
        history.processing_started_at = now()
        history.processing_task_id = "running-task"
        history.save()

        stats = self._run_with([_TagAndApprove(Approval.APPLIED)], history)

        self.assertEqual(stats.processed, 0)
        self.assertFalse(GameEdit.objects.filter(history=history).exists())
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.PROCESSING)
        self.assertEqual(history.processing_task_id, "running-task")

    def test_stale_processing_history_is_reclaimed(self):
        history = self._history()
        history.state = GameHistory.State.PROCESSING
        history.processing_started_at = now() - edit.EDIT_LEASE_TIMEOUT * 2
        history.processing_task_id = "dead-task"
        history.save()

        stats = self._run_with([_TagAndApprove(Approval.APPLIED)], history)

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertIsNone(history.processing_started_at)
        self.assertIsNone(history.processing_task_id)

    def test_failed_history_returns_to_schedule(self):
        history = self._history()

        stats = self._run_with([_Fail()], history)

        self.assertEqual(stats.errors, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SCHEDULED_FOR_UPDATE)
        self.assertIsNone(history.processing_started_at)
        self.assertIsNone(history.processing_task_id)

    def test_final_trailing_newline_only_change_is_noop(self):
        history = self._history()
        history.game.description = "Text"
        history.game.save(update_fields=["description"])

        stats = self._run_with(
            [_SetDescription()],
            history,
            [{"name": "set_description", "description": "Text\n"}],
        )

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

    def test_new_llm_trajectories_are_attached_to_created_edit(self):
        history = self._history()

        self._run_with(
            [_TagAndApprove(Approval.APPLIED), _CreateTrajectory()], history
        )

        edit_row = GameEdit.objects.get(history=history)
        trajectory = LlmTrajectory.objects.get(history=history)
        self.assertEqual(trajectory.edit, edit_row)

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

    def test_apply_updates_game_and_records_edit(self):
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

    def test_propose_creates_attention_edit_without_changing_game(self):
        game = Game.objects.create(title="Old Title", creation_time=now())
        history, fetch = self._history_with_source(game)

        edit_row = store_manual_edit(game, self._payload(), None, apply=False)

        game.refresh_from_db()
        history.refresh_from_db()
        self.assertEqual(game.title, "Old Title")
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(history.note, "Пользователь предложил правку")
        self.assertEqual(edit_row.status, GameEdit.EditStatus.PROPOSED)
        self.assertEqual(edit_row.origin, GameEdit.Origin.USER_SUGGESTION)
        self.assertIsNone(edit_row.previous_canonical_text)
        self.assertEqual(list(edit_row.used_sources.all()), [fetch])
        self.assertIn("New Title", edit_row.canonical_text)
        self.assertIn("manual source", edit_row.canonical_text)
