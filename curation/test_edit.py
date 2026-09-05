from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils.timezone import now

from games.gameinfo import Person, Tag
from games.models import (
    Game,
    GameAuthorRole,
    GameDescriptionAttribution,
    GameRevision,
    GameTag,
    GameTagCategory,
    GameURLCategory,
    PersonalityAlias,
)

from . import edit
from .edit import Approval, GameEditPass, run_edit
from .manual import store_manual_edit
from .models import (
    EditPipeline,
    GameHistory,
    GameHistoryAuditLog,
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
            game=state.history.game,
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


class _AssertPeerScheduled(GameEditPass):
    name = "assert_peer_scheduled"

    def __init__(self, first_id, peer_id):
        self.first_id = first_id
        self.peer_id = peer_id

    def apply(self, state, params):
        if state.history.pk == self.first_id:
            peer = GameHistory.objects.get(pk=self.peer_id)
            assert peer.state == GameHistory.State.SCHEDULED_FOR_UPDATE
        state.current.tags.append(Tag("os", "os_win", None, None))
        state.approval = Approval.CANCELLED


class RunEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def _history(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="A Game", creation_time=now()
        )
        return GameHistory.objects.create(
            game=game,
            state=GameHistory.State.SCHEDULED_FOR_UPDATE,
            creation_time=now(),
        )

    def _run_with(self, passes, history, specs=None, **kwargs):
        registry = {p.name: p for p in passes}
        specs = specs if specs is not None else [p.name for p in passes]
        pipeline = EditPipeline.objects.create(name="Test", passes=specs)
        with mock.patch.object(edit, "PASS_REGISTRY", registry):
            return run_edit(
                history_id=history.pk, pipeline_id=pipeline.pk, **kwargs
            )

    def _has_os_win(self, game):
        return game.tags.filter(symbolic_id="os_win").exists()

    # -- tests ------------------------------------------------------------

    def test_applied_writes_game_and_settles(self):
        history = self._history()

        stats = self._run_with([_TagAndApprove(Approval.APPLIED)], history)

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(history.game.state, Game.State.PUBLISHED)
        edit_row = GameRevision.objects.get(game=history.game)
        self.assertEqual(edit_row.status, GameRevision.Status.ACCEPTED)
        self.assertEqual(edit_row.passes, [{"name": "tag_and_approve"}])
        self.assertIsNotNone(edit_row.previous_canonical_text)
        self.assertEqual(edit_row.previous_canonical_text, "")
        self.assertIsNotNone(edit_row.published_at)
        self.assertEqual(
            edit_row.created_by.username, settings.MAINTENANCE_USER
        )

    def test_applied_with_previous_revision_records_previous_canonical_text(
        self,
    ):
        history = self._history()
        rev = GameRevision.objects.create(
            game=history.game,
            created_at=now(),
            published_at=now(),
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.BACKFILL,
            canonical_text='---\n- name: "A Game"\n---\n',
        )
        history.game.published_revision = rev
        history.game.save(update_fields=["published_revision"])

        stats = self._run_with([_TagAndApprove(Approval.APPLIED)], history)

        self.assertEqual(stats.applied, 1)
        edit_row = (
            GameRevision.objects
            .filter(game=history.game)
            .exclude(pk=rev.pk)
            .get()
        )
        self.assertEqual(edit_row.previous_canonical_text, rev.canonical_text)
        self.assertEqual(
            edit_row.published_by.username, settings.MAINTENANCE_USER
        )
        self.assertTrue(self._has_os_win(history.game))

    @mock.patch("curation.edit.PostNewGameToDiscord")
    def test_applied_existing_game_does_not_post_to_discord(self, post):
        history = self._history()

        self._run_with([_TagAndApprove(Approval.APPLIED)], history)

        post.assert_not_called()

    @mock.patch("curation.edit.PostNewGameToDiscord")
    def test_applied_draft_posts_new_game_to_discord(self, post):
        game = Game.objects.create(
            state=Game.State.DRAFT, title="Candidate", creation_time=now()
        )
        history = GameHistory.objects.create(
            game=game,
            state=GameHistory.State.SCHEDULED_FOR_UPDATE,
            creation_time=now(),
        )
        game_id = game.pk

        stats = self._run_with([_TagAndApprove(Approval.APPLIED)], history)

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        history.game.refresh_from_db()
        self.assertEqual(history.game_id, game_id)
        self.assertEqual(history.game.state, Game.State.PUBLISHED)
        post.assert_called_once_with(game_id)

    def test_proposed_needs_attention_game_untouched(self):
        history = self._history()

        stats = self._run_with([_TagAndApprove(Approval.PROPOSED)], history)

        self.assertEqual(stats.proposed, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(
            (edit_row := GameRevision.objects.get(game=history.game)).status,
            GameRevision.Status.PROPOSED,
        )
        self.assertIsNone(edit_row.previous_canonical_text)
        self.assertEqual(
            edit_row.created_by.username, settings.MAINTENANCE_USER
        )
        self.assertIsNone(edit_row.published_by)
        self.assertFalse(self._has_os_win(history.game))

    def test_rejected_settles_with_edit_game_untouched(self):
        history = self._history()

        stats = self._run_with([_TagAndApprove(Approval.REJECTED)], history)

        self.assertEqual(stats.rejected, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(
            (edit_row := GameRevision.objects.get(game=history.game)).status,
            GameRevision.Status.REJECTED,
        )
        self.assertIsNotNone(edit_row.previous_canonical_text)
        self.assertEqual(edit_row.previous_canonical_text, "")
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
            GameRevision.objects.get(game=history.game).status,
            GameRevision.Status.REJECTED,
        )
        self.assertFalse(self._has_os_win(history.game))

    def test_note_change_records_audit(self):
        history = self._history()

        self._run_with([_Note(), _TagAndApprove(Approval.REJECTED)], history)

        audit = GameHistoryAuditLog.objects.get(
            game=history.game, field=GameHistoryAuditLog.AuditField.NOTE
        )
        self.assertEqual(audit.actor.username, settings.MAINTENANCE_USER)
        self.assertIsNone(audit.old_text)
        self.assertEqual(audit.new_text, "Needs review")

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
            GameRevision.objects.get(game=history.game).status,
            GameRevision.Status.ACCEPTED,
        )

    def test_cancelled_settles_without_edit(self):
        history = self._history()

        stats = self._run_with([_TagAndApprove(Approval.CANCELLED)], history)

        self.assertEqual(stats.cancelled, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertFalse(
            GameRevision.objects.filter(game=history.game).exists()
        )
        self.assertFalse(self._has_os_win(history.game))

    def test_noop_settles_unchanged_without_edit(self):
        history = self._history()

        stats = self._run_with([], history)

        self.assertEqual(stats.unchanged, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertFalse(
            GameRevision.objects.filter(game=history.game).exists()
        )

    def test_processing_history_is_not_claimed_again(self):
        history = self._history()
        history.state = GameHistory.State.PROCESSING
        history.processing_started_at = now()
        history.processing_task_id = "running-task"
        history.save()

        stats = self._run_with([_TagAndApprove(Approval.APPLIED)], history)

        self.assertEqual(stats.processed, 0)
        self.assertFalse(
            GameRevision.objects.filter(game=history.game).exists()
        )
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.PROCESSING)
        self.assertEqual(history.processing_task_id, "running-task")

    def test_force_processes_settled_history(self):
        history = self._history()
        history.state = GameHistory.State.SETTLED
        history.save(update_fields=["state"])

        stats = self._run_with(
            [_TagAndApprove(Approval.APPLIED)], history, force=True
        )

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertTrue(self._has_os_win(history.game))

    def test_force_processes_needs_attention_history(self):
        history = self._history()
        history.state = GameHistory.State.NEEDS_ATTENTION
        history.save(update_fields=["state"])

        stats = self._run_with(
            [_TagAndApprove(Approval.APPLIED)], history, force=True
        )

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertTrue(self._has_os_win(history.game))

    def test_force_does_not_process_abandoned_history(self):
        history = self._history()
        history.state = GameHistory.State.ABANDONED
        history.save(update_fields=["state"])

        stats = self._run_with(
            [_TagAndApprove(Approval.APPLIED)], history, force=True
        )

        self.assertEqual(stats.processed, 0)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.ABANDONED)
        self.assertFalse(self._has_os_win(history.game))

    def test_force_does_not_claim_fresh_processing_history(self):
        history = self._history()
        history.state = GameHistory.State.PROCESSING
        history.processing_started_at = now()
        history.processing_task_id = "running-task"
        history.save()

        stats = self._run_with(
            [_TagAndApprove(Approval.APPLIED)], history, force=True
        )

        self.assertEqual(stats.processed, 0)
        self.assertFalse(
            GameRevision.objects.filter(game=history.game).exists()
        )
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.PROCESSING)
        self.assertEqual(history.processing_task_id, "running-task")

    def test_failed_forced_history_restores_original_state(self):
        history = self._history()
        history.state = GameHistory.State.NEEDS_ATTENTION
        history.save(update_fields=["state"])

        stats = self._run_with([_Fail()], history, force=True)

        self.assertEqual(stats.errors, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertIsNone(history.processing_started_at)
        self.assertIsNone(history.processing_task_id)

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

    def test_draft_histories_are_claimed_before_attached_histories(self):
        attached = self._history()
        candidate_game = Game.objects.create(
            state=Game.State.DRAFT, title="Candidate", creation_time=now()
        )
        candidate = GameHistory.objects.create(
            game=candidate_game,
            state=GameHistory.State.SCHEDULED_FOR_UPDATE,
            creation_time=now(),
        )
        pipeline = EditPipeline.objects.create(
            name="Test", passes=["tag_and_approve"]
        )
        with mock.patch.object(
            edit,
            "PASS_REGISTRY",
            {"tag_and_approve": _TagAndApprove(Approval.CANCELLED)},
        ):
            stats = run_edit(limit=1, pipeline_id=pipeline.pk)

        self.assertEqual(stats.cancelled, 1)
        attached.refresh_from_db()
        candidate.refresh_from_db()
        self.assertEqual(
            attached.state, GameHistory.State.SCHEDULED_FOR_UPDATE
        )
        self.assertEqual(candidate.state, GameHistory.State.ABANDONED)
        candidate_game.refresh_from_db()
        self.assertEqual(candidate_game.state, Game.State.ABANDONED)

    def test_histories_are_claimed_one_at_a_time(self):
        first = self._history()
        second = self._history()
        pipeline = EditPipeline.objects.create(
            name="Test", passes=["assert_peer_scheduled"]
        )
        with mock.patch.object(
            edit,
            "PASS_REGISTRY",
            {
                "assert_peer_scheduled": _AssertPeerScheduled(
                    first.pk, second.pk
                )
            },
        ):
            stats = run_edit(limit=2, pipeline_id=pipeline.pk)

        self.assertEqual(stats.cancelled, 2)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.state, GameHistory.State.SETTLED)
        self.assertEqual(second.state, GameHistory.State.SETTLED)

    def test_final_trailing_newline_only_change_is_noop(self):
        history = self._history()
        rev = GameRevision.objects.create(
            game=history.game,
            created_at=now(),
            published_at=now(),
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.BACKFILL,
            canonical_text="---\n\n---\nText",
        )
        history.game.published_revision = rev
        history.game.save(update_fields=["published_revision"])

        stats = self._run_with(
            [_SetDescription()],
            history,
            [{"name": "set_description", "description": "Text\n"}],
        )

        self.assertEqual(stats.unchanged, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(
            GameRevision.objects.filter(game=history.game).count(), 1
        )

    def test_pass_params_are_applied_and_recorded(self):
        history = self._history()

        self._run_with(
            [_TagAndApprove(Approval.APPLIED)],
            history,
            [{"name": "tag_and_approve", "tag": "os_dos"}],
        )

        edit_row = GameRevision.objects.get(game=history.game)
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

        edit_row = GameRevision.objects.get(game=history.game)
        trajectory = LlmTrajectory.objects.get(game=history.game)
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
            game=game,
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
        applied = GameRevision.objects.create(
            game=game,
            created_at=now(),
            published_at=now(),
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.AUTO_IMPORT,
            canonical_text=fetch.canonical_text,
        )
        applied.used_sources.add(fetch)
        return history, fetch

    def test_apply_updates_game_and_records_edit(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Old Title", creation_time=now()
        )
        history, fetch = self._history_with_source(game)

        edit_row = store_manual_edit(game, self._payload(), None, apply=True)

        game.refresh_from_db()
        history.refresh_from_db()
        self.assertEqual(game.title, "New Title")
        self.assertEqual(game.description, "New description")
        self.assertEqual(game.release_date.isoformat(), "2020-01-02")
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(edit_row.status, GameRevision.Status.ACCEPTED)
        self.assertEqual(edit_row.origin, GameRevision.Origin.MANUAL_EDIT)
        self.assertEqual(list(edit_row.used_sources.all()), [fetch])
        self.assertIn("manual source", edit_row.canonical_text)

    def test_propose_creates_attention_edit_without_changing_game(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Old Title", creation_time=now()
        )
        history, fetch = self._history_with_source(game)

        edit_row = store_manual_edit(game, self._payload(), None, apply=False)

        game.refresh_from_db()
        history.refresh_from_db()
        self.assertEqual(game.title, "Old Title")
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(history.note, "Пользователь предложил правку")
        self.assertEqual(edit_row.status, GameRevision.Status.PROPOSED)
        self.assertEqual(edit_row.origin, GameRevision.Origin.USER_SUGGESTION)
        self.assertIsNone(edit_row.previous_canonical_text)
        self.assertEqual(list(edit_row.used_sources.all()), [fetch])
        self.assertIn("New Title", edit_row.canonical_text)
        self.assertIn("manual source", edit_row.canonical_text)

    def test_propose_records_note_audit(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Old Title", creation_time=now()
        )
        history, _ = self._history_with_source(game)

        store_manual_edit(game, self._payload(), None, apply=False)

        audit = GameHistoryAuditLog.objects.get(
            game=game, field=GameHistoryAuditLog.AuditField.NOTE
        )
        self.assertIsNone(audit.actor)
        self.assertIsNone(audit.old_text)
        self.assertEqual(audit.new_text, "Пользователь предложил правку")
