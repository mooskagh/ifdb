from html import unescape
from io import StringIO
from json import loads
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from games.models import (
    URL,
    Game,
    GameAuthor,
    GameAuthorRole,
    GameDescriptionAttribution,
    GameTag,
    GameTagCategory,
    GameURL,
    GameURLCategory,
    PersonalityAlias,
)

from .edit import run_edit
from .gameinfo import GameInfo
from .models import (
    EditPipeline,
    GameEdit,
    GameHistory,
    GameHistoryAuditLog,
    GameHistoryComment,
    GameSource,
    GameSourceFetch,
    LLMModel,
    LlmTrajectory,
    LlmWorkflow,
    SourceDiscoveryStatus,
)


class CurationSmokeTest(TestCase):
    def test_attention_reason_resets_when_state_stops_needing_attention(self):
        history = GameHistory.objects.create(
            creation_time=timezone.now(),
            state=GameHistory.State.NEEDS_ATTENTION,
            attention_reason="Needs manual review",
        )

        history.state = GameHistory.State.SETTLED
        history.save()

        history.refresh_from_db()
        self.assertIsNone(history.attention_reason)

    def test_attention_reason_resets_with_state_update_fields(self):
        history = GameHistory.objects.create(
            creation_time=timezone.now(),
            state=GameHistory.State.NEEDS_ATTENTION,
            attention_reason="Needs manual review",
        )

        history.state = GameHistory.State.SCHEDULED_FOR_UPDATE
        history.save(update_fields=["state"])

        history.refresh_from_db()
        self.assertIsNone(history.attention_reason)

    def test_history_lifecycle(self):
        now = timezone.now()

        # History may exist before any Game row is created.
        history = GameHistory.objects.create(game=None, creation_time=now)
        self.assertIsNone(history.game)
        self.assertEqual(history.state, GameHistory.State.SCHEDULED_FOR_UPDATE)
        self.assertEqual(history.auto_updates, GameHistory.AutoUpdate.ACCEPT)

        source = GameSource.objects.create(
            history=history,
            url="https://example.com/game",
            type=GameSource.SourceType.IFWIKI,
        )
        fetch = GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            canonical_text="filtered",
            canonical_text_hash="abc123",
            first_fetch=now,
            last_fetch=now,
        )

        edit = GameEdit.objects.create(
            history=history,
            proposed_at=now,
            status=GameEdit.EditStatus.PROPOSED,
            origin=GameEdit.Origin.AUTO_IMPORT,
            canonical_text="# Game\n---\ntitle: Game",
        )
        edit.used_sources.add(fetch)
        self.assertEqual(list(edit.used_sources.all()), [fetch])

        other_edit = GameEdit.objects.create(
            history=history,
            proposed_at=now,
            status=GameEdit.EditStatus.PROPOSED,
            origin=GameEdit.Origin.MANUAL_EDIT,
            passes=["ManualPass"],
            canonical_text="Updated game text",
        )
        self.assertEqual(other_edit.passes, ["ManualPass"])

        parent_comment = GameHistoryComment.objects.create(
            history=history,
            type=GameHistoryComment.CommentType.USER_FEEDBACK,
            text="Looks off.",
            creation_time=now,
        )
        reply = GameHistoryComment.objects.create(
            history=history,
            reply_to=parent_comment,
            type=GameHistoryComment.CommentType.MODS_COMMENT,
            text="Fixed.",
            creation_time=now,
        )
        self.assertEqual(reply.reply_to, parent_comment)

        GameHistoryAuditLog.objects.create(
            history=history,
            created_at=now,
            kind="",
            new_id=edit.pk,
        )
        self.assertEqual(history.gamehistoryauditlog_set.count(), 1)


class HistoryListViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="moder", email="moder@example.com"
        )
        self.user.groups.add(Group.objects.create(name="moder"))
        self.client.force_login(self.user)

    def test_history_list_is_compact_and_uses_short_labels(self):
        ts = timezone.now()
        game = Game.objects.create(
            title="Very Long Game Title That Should Be Truncated",
            creation_time=ts,
            added_by=self.user,
        )
        GameHistory.objects.create(
            game=game,
            creation_time=ts,
            state=GameHistory.State.NEEDS_ATTENTION,
            auto_updates=GameHistory.AutoUpdate.PROPOSE,
            attention_reason="Needs manual review",
        )

        response = self.client.get("/curation/")
        self.assertEqual(response.status_code, 200)
        for text in [
            "curation-history-table",
            '<tr class="warning"',
            'class="curation-truncate"',
            'title="Very Long Game Title That Should Be Truncated"',
            "внимание",
            "Needs manual review",
            "предл.",
        ]:
            self.assertContains(response, text)

    def test_history_list_defaults_to_relevance_sort(self):
        ts = timezone.now()
        old_settled = self._create_history(
            "Old settled",
            ts,
            state=GameHistory.State.SETTLED,
        )
        recent_progress = self._create_history(
            "Recent progress",
            ts + timezone.timedelta(days=1),
            state=GameHistory.State.SCHEDULED_FOR_UPDATE,
        )
        older_attention = self._create_history(
            "Older attention",
            ts + timezone.timedelta(days=2),
            state=GameHistory.State.NEEDS_ATTENTION,
        )
        newer_attention = self._create_history(
            "Newer attention",
            ts + timezone.timedelta(days=3),
            state=GameHistory.State.NEEDS_ATTENTION,
        )

        response = self.client.get("/curation/")

        self.assertEqual(
            list(response.context["histories"]),
            [newer_attention, older_attention, recent_progress, old_settled],
        )
        self.assertContains(response, '<option value="relevance" selected>')

    def test_history_list_links_latest_pending_edit(self):
        ts = timezone.now()
        pending_history = self._create_history(
            "Pending", ts, state=GameHistory.State.SETTLED
        )
        old_pending = self._create_edit(
            pending_history,
            ts,
            status=GameEdit.EditStatus.PROPOSED,
        )
        latest_pending = self._create_edit(
            pending_history,
            ts + timezone.timedelta(minutes=1),
            status=GameEdit.EditStatus.PROPOSED,
        )
        done_history = self._create_history(
            "Done", ts, state=GameHistory.State.SETTLED
        )
        done_edit = self._create_edit(
            done_history,
            ts,
            status=GameEdit.EditStatus.APPLIED,
        )

        response = self.client.get("/curation/")

        self.assertContains(response, "правка ждёт")
        self.assertContains(response, "curation-action-link--compact")
        self.assertContains(
            response, f'href="/curation/edits/{latest_pending.pk}/"'
        )
        self.assertNotContains(
            response, f'href="/curation/edits/{old_pending.pk}/"'
        )
        self.assertNotContains(
            response, f'href="/curation/edits/{done_edit.pk}/"'
        )

    def _create_history(self, title, updated, *, state):
        game = Game.objects.create(
            title=title,
            creation_time=updated,
            added_by=self.user,
        )
        return GameHistory.objects.create(
            game=game,
            creation_time=updated,
            edit_time=updated,
            state=state,
        )

    def _create_edit(self, history, proposed_at, *, status):
        return GameEdit.objects.create(
            history=history,
            proposed_at=proposed_at,
            status=status,
            origin=GameEdit.Origin.AUTO_IMPORT,
            previous_canonical_text="old",
            canonical_text="new",
        )


class LlmTrajectoryViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="moder", email="moder@example.com"
        )
        self.user.groups.add(Group.objects.create(name="moder"))
        self.client.force_login(self.user)

        now = timezone.now()
        self.game = Game.objects.create(
            title="Readable Messages", creation_time=now, added_by=self.user
        )
        self.history = GameHistory.objects.create(
            game=self.game, creation_time=now
        )
        self.model = LLMModel.objects.create(
            name="test/model",
            context_length=1000,
            input_cost=1,
            cached_input_cost=0,
            cache_write_cost=0,
            output_cost=1,
        )
        self.workflow = LlmWorkflow.objects.create(
            name="test_workflow",
            runner="test_runner",
            prompt_template="Prompt",
            model=self.model,
        )
        self.trajectory = LlmTrajectory.objects.create(
            history=self.history,
            workflow=self.workflow,
            model=self.model,
            created_at=now,
            messages=[
                {"role": "user", "content": "Describe the game."},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "set_description",
                                "arguments": '{"description":"New text"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": (
                        "Description updated: "
                        "[&quot;download_direct&quot;, 7612] "
                        "https://example.test/"
                        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    ),
                },
            ],
            prompt_tokens=10,
            cached_input_tokens=2,
            cache_write_tokens=3,
            completion_tokens=4,
            cost="0.000014",
        )

    def test_list_links_to_trajectory_detail(self):
        response = self.client.get("/curation/trajectories/")

        self.assertContains(
            response, f"/curation/trajectories/{self.trajectory.pk}/"
        )
        self.assertContains(
            response,
            f'data-href="/curation/trajectories/{self.trajectory.pk}/"',
        )

    def test_detail_renders_messages_readably(self):
        response = self.client.get(
            f"/curation/trajectories/{self.trajectory.pk}/"
        )
        content = unescape(response.content.decode())

        self.assertEqual(response.status_code, 200)
        for text in [
            "Траектория LLM",
            "Readable Messages",
            "test_workflow",
            "test/model",
            "Describe the game.",
            "set_description",
            "New text",
            "call_1",
            "Description updated:",
            '["download_direct", 7612]',
            "curation-message--assistant",
            "curation-message-meta-col",
            "curation-message-body",
        ]:
            self.assertIn(text, content)


class EditDiffViewTest(TestCase):
    def setUp(self):
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())
        self.user = get_user_model().objects.create(
            username="moder", email="moder@example.com"
        )
        self.user.groups.add(Group.objects.create(name="moder"))
        self.client.force_login(self.user)
        self.now = timezone.now()

    def _edit(self, *, auto_updates=GameHistory.AutoUpdate.PROPOSE):
        game = Game.objects.create(
            title="Old Title", creation_time=self.now, added_by=self.user
        )
        history = GameHistory.objects.create(
            game=game,
            creation_time=self.now,
            state=GameHistory.State.NEEDS_ATTENTION,
            auto_updates=auto_updates,
        )
        edit = GameEdit.objects.create(
            history=history,
            proposed_at=self.now,
            proposed_by=self.user,
            status=GameEdit.EditStatus.PROPOSED,
            origin=GameEdit.Origin.AUTO_IMPORT,
            canonical_text=GameInfo(name="New Title").to_canonical(),
        )
        return edit

    def test_proposed_edit_shows_actions_and_auto_accept_checkbox(self):
        edit = self._edit(auto_updates=GameHistory.AutoUpdate.ACCEPT)

        response = self.client.get(f"/curation/edits/{edit.pk}/")

        self.assertContains(response, "Принять")
        self.assertContains(response, "Отклонить")
        self.assertContains(response, "В дальнейшем автоматически принимать")
        self.assertContains(response, 'name="auto_accept" checked')
        self.assertContains(response, 'name="next"')
        self.assertContains(response, "к списку игр")
        self.assertContains(response, "к редактированию игры")
        self.assertContains(response, "к игре")
        self.assertContains(response, "к истории игры")
        self.assertContains(response, "остаться тут")

    def test_edit_page_shows_game_users_passes_and_llm_links(self):
        edit = self._edit()
        edit.passes = [
            "NormalizeText",
            {"name": "LlmWorkflowPass", "workflow": "test_workflow"},
        ]
        edit.save(update_fields=["passes"])
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
        trajectory = LlmTrajectory.objects.create(
            history=edit.history,
            edit=edit,
            workflow=workflow,
            model=model,
            created_at=self.now + timezone.timedelta(minutes=1),
            messages=[],
            cost="0.000000",
        )

        response = self.client.get(f"/curation/edits/{edit.pk}/")
        content = unescape(response.content.decode())

        self.assertContains(response, f'href="/game/{edit.history.game_id}/"')
        self.assertContains(response, "Old Title")
        self.assertContains(response, "Предложил")
        self.assertContains(response, "moder")
        self.assertContains(response, "Passes")
        self.assertContains(response, "<strong>NormalizeText</strong>")
        self.assertContains(response, "<strong>LlmWorkflowPass</strong>")
        self.assertIn('"workflow": "test_workflow"', content)
        self.assertContains(response, "LLM")
        self.assertContains(response, "test_workflow")
        self.assertContains(response, "test/model")
        self.assertContains(
            response, f'href="/curation/trajectories/{trajectory.pk}/"'
        )

    def test_settled_edit_page_shows_approver(self):
        edit = self._edit()
        edit.status = GameEdit.EditStatus.APPLIED
        edit.approved_at = self.now + timezone.timedelta(minutes=5)
        edit.approver = self.user
        edit.save(update_fields=["status", "approved_at", "approver"])

        response = self.client.get(f"/curation/edits/{edit.pk}/")

        self.assertContains(response, "Одобрил")
        self.assertContains(
            response,
            f"moder ({edit.approved_at:%d.%m.%Y %H:%M})",
        )

    def test_edit_redirect_dropdown_hides_game_options_without_game(self):
        edit = self._edit()
        edit.history.game = None
        edit.history.save(update_fields=["game"])

        response = self.client.get(f"/curation/edits/{edit.pk}/")

        self.assertContains(response, 'name="next"')
        self.assertContains(response, "к списку игр")
        self.assertNotContains(response, "к редактированию игры")
        self.assertNotContains(response, "к игре")
        self.assertContains(response, "к истории игры")
        self.assertContains(response, "остаться тут")

    def test_non_proposed_edit_hides_actions(self):
        edit = self._edit()
        edit.status = GameEdit.EditStatus.REJECTED
        edit.save(update_fields=["status"])

        response = self.client.get(f"/curation/edits/{edit.pk}/")

        self.assertNotContains(response, "Принять")
        self.assertNotContains(response, "Отклонить")
        self.assertNotContains(
            response, "В дальнейшем автоматически принимать"
        )

    def test_reject_settles_and_redirects_without_changing_game(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/", {"action": "reject"}
        )

        self.assertRedirects(response, "/curation/")
        edit.refresh_from_db()
        history = edit.history
        history.refresh_from_db()
        history.game.refresh_from_db()
        self.assertEqual(edit.status, GameEdit.EditStatus.REJECTED)
        self.assertEqual(edit.approver, self.user)
        self.assertIn("Old Title", edit.previous_canonical_text)
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(history.game.title, "Old Title")

    def test_accept_applies_and_settles(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/", {"action": "accept"}
        )

        self.assertRedirects(response, "/curation/")
        edit.refresh_from_db()
        history = edit.history
        history.refresh_from_db()
        history.game.refresh_from_db()
        self.assertEqual(edit.status, GameEdit.EditStatus.APPLIED)
        self.assertEqual(edit.approver, self.user)
        self.assertIn("Old Title", edit.previous_canonical_text)
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertEqual(history.game.title, "New Title")

    def test_accept_redirects_to_game_edit_when_requested(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "accept", "next": "edit_game"},
        )

        self.assertRedirects(
            response,
            f"/game/edit/{edit.history.game_id}/",
            fetch_redirect_response=False,
        )

    def test_accept_redirects_to_game_when_requested(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "accept", "next": "game"},
        )

        self.assertRedirects(
            response,
            f"/game/{edit.history.game_id}/",
            fetch_redirect_response=False,
        )

    def test_accept_redirects_to_history_when_requested(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "accept", "next": "history"},
        )

        self.assertRedirects(response, f"/curation/{edit.history_id}/")

    def test_accept_redirects_to_edit_when_stay_requested(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "accept", "next": "stay"},
        )

        self.assertRedirects(response, f"/curation/edits/{edit.pk}/")

    def test_game_redirect_falls_back_to_list_without_game(self):
        edit = self._edit()
        edit.history.game = None
        edit.history.save(update_fields=["game"])

        response = self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "reject", "next": "game"},
        )

        self.assertRedirects(response, "/curation/")

    def test_accept_updates_auto_accept_with_audit(self):
        edit = self._edit(auto_updates=GameHistory.AutoUpdate.PROPOSE)

        self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "accept", "auto_accept": "on"},
        )

        history = edit.history
        history.refresh_from_db()
        self.assertEqual(history.auto_updates, GameHistory.AutoUpdate.ACCEPT)
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                history=history,
                actor=self.user,
                field=GameHistoryAuditLog.AuditField.AUTO_UPDATES,
                old_text=GameHistory.AutoUpdate.PROPOSE,
                new_text=GameHistory.AutoUpdate.ACCEPT,
            ).exists()
        )

    def test_auto_accept_hidden_for_reject_policy(self):
        edit = self._edit(auto_updates=GameHistory.AutoUpdate.REJECT)

        response = self.client.get(f"/curation/edits/{edit.pk}/")

        self.assertContains(response, "Принять")
        self.assertNotContains(
            response, "В дальнейшем автоматически принимать"
        )

    def test_history_page_resolve_button_only_for_proposed_edits(self):
        proposed = self._edit()
        rejected = GameEdit.objects.create(
            history=proposed.history,
            proposed_at=self.now + timezone.timedelta(minutes=5),
            proposed_by=self.user,
            approver=self.user,
            status=GameEdit.EditStatus.REJECTED,
            origin=GameEdit.Origin.AUTO_IMPORT,
            canonical_text=GameInfo(name="Rejected Title").to_canonical(),
        )

        response = self.client.get(f"/curation/{proposed.history.pk}/")

        self.assertContains(
            response,
            '<a class="curation-action-link" '
            f'href="/curation/edits/{proposed.pk}/">посмотреть правку и '
            "решить, что с ней делать</a>",
            html=True,
        )
        self.assertContains(
            response,
            f'<a href="/curation/edits/{rejected.pk}/">посмотреть</a>',
            html=True,
        )
        self.assertContains(response, "Предложил: moder")
        self.assertContains(response, "Отклонил: moder")
        self.assertNotContains(
            response,
            '<a class="curation-action-link" '
            f'href="/curation/edits/{rejected.pk}/">посмотреть правку и '
            "решить, что с ней делать</a>",
            html=True,
        )

    def test_history_page_sorts_settled_edits_by_approval_date(self):
        proposed = self._edit()
        proposed.proposed_at = self.now + timezone.timedelta(minutes=10)
        proposed.save(update_fields=["proposed_at"])
        approved = GameEdit.objects.create(
            history=proposed.history,
            proposed_at=self.now - timezone.timedelta(days=1),
            proposed_by=self.user,
            approved_at=self.now + timezone.timedelta(minutes=20),
            approver=self.user,
            status=GameEdit.EditStatus.APPLIED,
            origin=GameEdit.Origin.AUTO_IMPORT,
            canonical_text=GameInfo(name="Approved Title").to_canonical(),
        )

        response = self.client.get(f"/curation/{proposed.history.pk}/")
        content = response.content.decode()

        self.assertContains(
            response,
            f"Предложил: moder ({proposed.proposed_at:%d.%m.%Y %H:%M})",
        )
        self.assertContains(
            response,
            f"Одобрил: moder ({approved.approved_at:%d.%m.%Y %H:%M})",
        )
        self.assertLess(
            content.index(f"/curation/edits/{proposed.pk}/"),
            content.index(f"/curation/edits/{approved.pk}/"),
        )

    def test_history_page_lists_related_llm_workflows_in_edit_panel(self):
        edit = self._edit()
        edit.passes = [
            "NormalizeText",
            {"name": "LlmWorkflowPass", "workflow": "test_workflow"},
        ]
        edit.save(update_fields=["passes"])
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
        trajectory = LlmTrajectory.objects.create(
            history=edit.history,
            edit=edit,
            workflow=workflow,
            model=model,
            created_at=self.now + timezone.timedelta(minutes=1),
            messages=[],
            cost="0.000000",
        )

        response = self.client.get(f"/curation/{edit.history.pk}/")
        content = unescape(response.content.decode())

        self.assertNotContains(response, "Траектория LLM")
        self.assertContains(response, "LLM:")
        self.assertContains(response, "test_workflow")
        self.assertContains(response, "Passes:")
        self.assertContains(response, "<strong>NormalizeText</strong>")
        self.assertContains(response, "<strong>LlmWorkflowPass</strong>")
        self.assertIn('"workflow": "test_workflow"', content)
        self.assertNotIn('"name": "LlmWorkflowPass"', content)
        self.assertContains(
            response, f'href="/curation/trajectories/{trajectory.pk}/"'
        )

    def test_history_page_shows_orphan_trajectories_separately(self):
        edit = self._edit()
        model = LLMModel.objects.create(
            name="orphan/model",
            context_length=1000,
            input_cost=1,
            cached_input_cost=0,
            cache_write_cost=0,
            output_cost=1,
        )
        workflow = LlmWorkflow.objects.create(
            name="orphan_workflow",
            runner="test_runner",
            prompt_template="Prompt",
            model=model,
        )
        trajectory = LlmTrajectory.objects.create(
            history=edit.history,
            workflow=workflow,
            model=model,
            created_at=self.now + timezone.timedelta(minutes=1),
            messages=[],
            cost="0.000000",
        )

        response = self.client.get(f"/curation/{edit.history.pk}/")

        self.assertContains(response, "Сиротская траектория LLM")
        self.assertContains(
            response, "У этой траектории нет ссылки на GameEdit."
        )
        self.assertContains(response, "orphan_workflow")
        self.assertContains(
            response, f'href="/curation/trajectories/{trajectory.pk}/"'
        )


class DiscoveryViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="moder", email="moder@example.com"
        )
        self.user.groups.add(Group.objects.create(name="moder"))
        self.client.force_login(self.user)

    def test_discovery_status_links_to_detail_with_source_lists(self):
        ts = timezone.now()
        sources = [
            GameSource.objects.create(
                type=GameSource.SourceType.APERO,
                url=f"https://example.com/{kind}",
                created_at=ts,
            )
            for kind in [
                "new",
                "newly-missing",
                "absent",
                "existing",
                "unused",
                "duplicate-a",
                "duplicate-b",
            ]
        ]
        game = Game.objects.create(
            title="Linked Game", creation_time=ts, added_by=self.user
        )
        game_history = GameHistory.objects.create(game=game, creation_time=ts)
        empty_history = GameHistory.objects.create(game=None, creation_time=ts)
        sources[2].history = empty_history
        sources[2].save(update_fields=["history"])
        sources[3].history = game_history
        sources[3].save(update_fields=["history"])
        status = SourceDiscoveryStatus.objects.create(
            source_type=GameSource.SourceType.APERO,
            first_seen=ts,
            last_seen=ts,
            is_error=False,
            new_ids=[sources[0].id],
            newly_missing_ids=[sources[1].id],
            absent_ids=[sources[2].id],
            existing_ids=[sources[3].id],
            unused_ids=[sources[4].id],
            duplicate_id_clusters=[[sources[5].id, sources[6].id]],
        )

        list_response = self.client.get("/curation/discovery/")
        self.assertContains(list_response, f"/curation/discovery/{status.pk}/")

        detail_response = self.client.get(f"/curation/discovery/{status.pk}/")
        self.assertEqual(detail_response.status_code, 200)
        for text in [
            "Новые источники: 1",
            "Существующие: 1",
            "Пропавшие: 1",
            "Отсутствующие: 1",
            "Неиспользуемые: 1",
            "Дубликаты: 1",
            "https://example.com/new",
            "https://example.com/newly-missing",
            "https://example.com/absent",
            "https://example.com/existing",
            "https://example.com/unused",
            "https://example.com/duplicate-a",
            "https://example.com/duplicate-b",
            'href="#new">Новые источники: 1</a>',
            'href="#newly-missing">Пропавшие: 1</a>',
            'href="#absent">Отсутствующие: 1</a>',
            'href="#unused">Неиспользуемые: 1</a>',
            'href="#duplicates">Дубликаты: 1</a>',
            'href="#existing">Существующие: 1</a>',
            'id="new"',
            'id="newly-missing"',
            'id="absent"',
            'id="unused"',
            'id="duplicates"',
            'id="existing"',
        ]:
            self.assertContains(detail_response, text)
        self.assertContains(
            detail_response, f'href="/game/{game.pk}/">Linked Game</a>'
        )
        self.assertContains(
            detail_response, f'href="/curation/sources/{sources[0].pk}/"'
        )
        self.assertContains(
            detail_response,
            f'href="/curation/{game_history.pk}/">история</a>',
        )
        self.assertContains(detail_response, "(none)")
        self.assertContains(
            detail_response,
            f'href="/curation/{empty_history.pk}/">история</a>',
        )
        content = detail_response.content.decode()
        self.assertLess(
            content.index("Неиспользуемые: 1"),
            content.index("Существующие: 1"),
        )
        self.assertLess(
            content.index("Дубликаты: 1"),
            content.index("Существующие: 1"),
        )


class TasksViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="moder", email="moder@example.com"
        )
        self.user.groups.add(Group.objects.create(name="moder"))
        self.client.force_login(self.user)
        self.pipeline, _ = EditPipeline.objects.update_or_create(
            name="Импорт", defaults={"passes": [{"name": "merge_sources"}]}
        )

    def test_page_shows_ready_and_total_orphan_sources(self):
        ts = timezone.now()
        ready = GameSource.objects.create(
            type=GameSource.SourceType.APERO,
            url="https://example.com/ready",
        )
        GameSourceFetch.objects.create(
            source=ready,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash="abc123",
            first_fetch=ts,
            last_fetch=ts,
        )
        GameSource.objects.create(
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/unfetched",
        )

        response = self.client.get("/curation/tasks/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Периодические задания")
        self.assertContains(response, "Обработать новые источники (1/2)")
        self.assertContains(response, "(все сайты)")
        self.assertContains(response, "автоимпорт нового")
        self.assertContains(response, "выкачивать источники")
        self.assertContains(response, "выкачивать всякие там форумы")
        self.assertContains(response, "автоматическая обработка очереди")
        self.assertContains(response, "Импорт")

    @patch("curation.views.discover_sources.delay")
    def test_discover_button_starts_task_for_all_sites(self, delay):
        response = self.client.post(
            "/curation/tasks/",
            {"action": "run_discover_sources"},
        )

        self.assertRedirects(response, "/curation/tasks/")
        delay.assert_called_once_with(types=None)

    @patch("curation.views.fetch_sources.delay")
    def test_fetch_sources_button_starts_task_with_run_limit(self, delay):
        response = self.client.post(
            "/curation/tasks/",
            {"action": "run_fetch_sources", "run_limit": "9"},
        )

        self.assertRedirects(response, "/curation/tasks/")
        delay.assert_called_once_with(limit=9)

    @patch("curation.views.reconcile_sources.delay")
    def test_reconcile_button_starts_task(self, delay):
        response = self.client.post(
            "/curation/tasks/", {"action": "run_reconcile_sources"}
        )

        self.assertRedirects(response, "/curation/tasks/")
        delay.assert_called_once_with()

    @patch("curation.views.fetch_feeds.delay")
    def test_fetch_feeds_button_starts_task(self, delay):
        response = self.client.post(
            "/curation/tasks/", {"action": "run_fetch_feeds"}
        )

        self.assertRedirects(response, "/curation/tasks/")
        delay.assert_called_once_with()

    @patch("curation.views.edit_sources.delay")
    def test_edit_sources_button_starts_task_with_pipeline_and_limit(
        self, delay
    ):
        response = self.client.post(
            "/curation/tasks/",
            {
                "action": "run_edit_sources",
                "pipeline": self.pipeline.pk,
                "run_limit": "9",
            },
        )

        self.assertRedirects(response, "/curation/tasks/")
        delay.assert_called_once_with(limit=9, pipeline_id=self.pipeline.pk)

    def test_save_discover_sources_periodic_task(self):
        response = self.client.post(
            "/curation/tasks/",
            {
                "action": "save_discover_sources",
                "enabled": "on",
                "auto_import_new": "on",
                "pipeline": self.pipeline.pk,
                "every": "3",
                "period": IntervalSchedule.HOURS,
            },
        )

        self.assertRedirects(response, "/curation/tasks/")
        task = PeriodicTask.objects.get(name="Discover sources")
        self.assertTrue(task.enabled)
        self.assertEqual(task.task, "curation.tasks.discover_sources")
        self.assertEqual(
            loads(task.kwargs),
            {
                "types": None,
                "auto_import_new": True,
                "pipeline_id": self.pipeline.pk,
            },
        )
        self.assertEqual(task.interval.every, 3)
        self.assertEqual(task.interval.period, IntervalSchedule.HOURS)

    def test_save_discover_sources_periodic_task_without_auto_import(self):
        response = self.client.post(
            "/curation/tasks/",
            {
                "action": "save_discover_sources",
                "pipeline": self.pipeline.pk,
                "every": "3",
                "period": IntervalSchedule.HOURS,
            },
        )

        self.assertRedirects(response, "/curation/tasks/")
        task = PeriodicTask.objects.get(name="Discover sources")
        self.assertFalse(task.enabled)
        self.assertEqual(
            loads(task.kwargs),
            {
                "types": None,
                "auto_import_new": False,
                "pipeline_id": self.pipeline.pk,
            },
        )

    def test_save_fetch_sources_periodic_task(self):
        response = self.client.post(
            "/curation/tasks/",
            {
                "action": "save_fetch_sources",
                "enabled": "on",
                "periodic_limit": "7",
                "every": "10",
                "period": IntervalSchedule.MINUTES,
            },
        )

        self.assertRedirects(response, "/curation/tasks/")
        task = PeriodicTask.objects.get(name="Fetch sources")
        self.assertTrue(task.enabled)
        self.assertEqual(task.task, "curation.tasks.fetch_sources")
        self.assertEqual(loads(task.kwargs), {"limit": 7})
        self.assertEqual(task.interval.every, 10)
        self.assertEqual(task.interval.period, IntervalSchedule.MINUTES)

    def test_save_reconcile_sources_periodic_task(self):
        response = self.client.post(
            "/curation/tasks/",
            {
                "action": "save_reconcile_sources",
                "enabled": "on",
                "every": "15",
                "period": IntervalSchedule.MINUTES,
            },
        )

        self.assertRedirects(response, "/curation/tasks/")
        task = PeriodicTask.objects.get(name="Reconcile sources")
        self.assertTrue(task.enabled)
        self.assertEqual(task.task, "curation.tasks.reconcile_sources")
        self.assertEqual(loads(task.kwargs), {})
        self.assertEqual(task.interval.every, 15)
        self.assertEqual(task.interval.period, IntervalSchedule.MINUTES)

    def test_save_fetch_feeds_periodic_task_preserves_task(self):
        schedule = IntervalSchedule.objects.create(
            every=1, period=IntervalSchedule.HOURS
        )
        PeriodicTask.objects.update_or_create(
            name="Fetch feeds",
            defaults={
                "task": "core.tasks.fetch_feeds",
                "interval": schedule,
                "args": "[]",
                "kwargs": "{}",
            },
        )

        response = self.client.post(
            "/curation/tasks/",
            {
                "action": "save_fetch_feeds",
                "every": "2",
                "period": IntervalSchedule.HOURS,
            },
        )

        self.assertRedirects(response, "/curation/tasks/")
        task = PeriodicTask.objects.get(name="Fetch feeds")
        self.assertFalse(task.enabled)
        self.assertEqual(task.task, "core.tasks.fetch_feeds")
        self.assertEqual(loads(task.kwargs), {})
        self.assertEqual(task.interval.every, 2)
        self.assertEqual(task.interval.period, IntervalSchedule.HOURS)

    def test_save_edit_sources_periodic_task(self):
        response = self.client.post(
            "/curation/tasks/",
            {
                "action": "save_edit_sources",
                "enabled": "on",
                "pipeline": self.pipeline.pk,
                "periodic_limit": "7",
                "every": "10",
                "period": IntervalSchedule.MINUTES,
            },
        )

        self.assertRedirects(response, "/curation/tasks/")
        task = PeriodicTask.objects.get(name="Edit sources")
        self.assertTrue(task.enabled)
        self.assertEqual(task.task, "curation.tasks.edit_sources")
        self.assertEqual(
            loads(task.kwargs), {"limit": 7, "pipeline_id": self.pipeline.pk}
        )
        self.assertEqual(task.interval.every, 10)
        self.assertEqual(task.interval.period, IntervalSchedule.MINUTES)


class SourceViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="moder", email="moder@example.com"
        )
        self.user.groups.add(Group.objects.create(name="moder"))
        self.client.force_login(self.user)

    def test_source_list_detail_and_fetch_content(self):
        ts = timezone.now()
        game = Game.objects.create(
            title="Source Game", creation_time=ts, added_by=self.user
        )
        history = GameHistory.objects.create(game=game, creation_time=ts)
        source = GameSource.objects.create(
            history=history,
            url="https://example.com/source",
            type=GameSource.SourceType.IFWIKI,
            created_at=ts,
            failing_since=ts,
            last_attempt=ts,
            last_error="Fetch failed",
        )
        fetch = GameSourceFetch.objects.create(
            source=source,
            raw_content="raw text",
            canonical_text="canonical text",
            canonical_text_hash="abc123",
            first_fetch=ts,
            last_fetch=ts,
        )

        list_response = self.client.get("/curation/sources/")
        self.assertEqual(list_response.status_code, 200)
        for text in [
            'href="/curation/sources/"',
            f'href="/curation/sources/{source.pk}/"',
            "curation-source-table",
            '<tr class="error"',
            'title="https://example.com/source"',
            f'href="/game/{game.pk}/">Source Game</a>',
            ts.strftime("%Y-%m-%d %H:%M"),
            f'href="/curation/sources/fetches/{fetch.pk}/raw/"',
            f"/curation/sources/fetches/{fetch.pk}/canonical/",
        ]:
            self.assertContains(list_response, text)

        detail_response = self.client.get(f"/curation/sources/{source.pk}/")
        self.assertEqual(detail_response.status_code, 200)
        for text in [
            "https://example.com/source",
            f'href="/game/{game.pk}/">Source Game</a>',
            f'(<a href="/curation/{history.pk}/">история</a>)',
            "Fetch failed",
            'class="curation-source-error"',
            ts.strftime("%Y-%m-%d %H:%M"),
            f'href="/curation/sources/fetches/{fetch.pk}/raw/"',
            f"/curation/sources/fetches/{fetch.pk}/canonical/",
        ]:
            self.assertContains(detail_response, text)

        raw_response = self.client.get(
            f"/curation/sources/fetches/{fetch.pk}/raw/"
        )
        self.assertEqual(raw_response.status_code, 200)
        self.assertEqual(
            raw_response["Content-Type"], "text/plain; charset=utf-8"
        )
        self.assertEqual(raw_response.content.decode(), "raw text")

        canonical_response = self.client.get(
            f"/curation/sources/fetches/{fetch.pk}/canonical/"
        )
        self.assertEqual(canonical_response.status_code, 200)
        self.assertEqual(
            canonical_response["Content-Type"], "text/plain; charset=utf-8"
        )
        self.assertEqual(canonical_response.content.decode(), "canonical text")

    def test_source_list_search_filter_and_pagination(self):
        ts = timezone.now()
        wanted_game = Game.objects.create(
            title="Wanted Game", creation_time=ts, added_by=self.user
        )
        wanted_history = GameHistory.objects.create(
            game=wanted_game, creation_time=ts
        )
        wanted = GameSource.objects.create(
            history=wanted_history,
            url="https://example.com/wanted",
            type=GameSource.SourceType.APERO,
            failing_since=ts,
            last_error="boom",
        )
        other = GameSource.objects.create(
            url="https://example.com/other",
            type=GameSource.SourceType.IFWIKI,
        )
        for i in range(101):
            GameSource.objects.create(
                url=f"https://example.com/page-{i}",
                type=GameSource.SourceType.QSP,
            )

        response = self.client.get(
            "/curation/sources/", {"q": "wanted", "state": "failed"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="/curation/sources/{wanted.pk}/"')
        self.assertNotContains(
            response, f'href="/curation/sources/{other.pk}/"'
        )

        page_response = self.client.get("/curation/sources/")
        self.assertContains(page_response, "Страница 1 из 2")

    def test_history_links_sources_to_detail(self):
        ts = timezone.now()
        history = GameHistory.objects.create(game=None, creation_time=ts)
        pipeline, _ = EditPipeline.objects.update_or_create(
            name="Импорт", defaults={"passes": [{"name": "merge_sources"}]}
        )
        source = GameSource.objects.create(
            history=history,
            url="https://example.com/source",
            type=GameSource.SourceType.APERO,
            created_at=ts,
        )
        GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash="abc123",
            first_fetch=ts,
            last_fetch=ts,
        )

        response = self.client.get(f"/curation/{history.pk}/")
        self.assertEqual(response.status_code, 200)
        source_url = f"/curation/sources/{source.pk}/"
        self.assertContains(
            response,
            '<div class="curation-source-id">'
            f'<a href="{source_url}">{source.pk}</a></div>',
            html=True,
        )
        self.assertContains(
            response,
            '<div class="curation-source-type">'
            f'<a href="{source_url}">Apero</a></div>',
            html=True,
        )
        self.assertContains(
            response,
            f'action="/curation/{history.pk}/sources/add/"',
        )
        self.assertContains(
            response,
            f'action="/curation/{history.pk}/sources/{source.pk}/delete/"',
        )
        self.assertContains(response, 'data-confirm="Открепить этот источник')
        self.assertContains(response, "Автоматическая обработка")
        self.assertContains(response, pipeline.name)

    @patch("curation.views.edit_sources.delay")
    def test_history_run_edit_starts_task(self, delay):
        ts = timezone.now()
        history = GameHistory.objects.create(game=None, creation_time=ts)
        pipeline, _ = EditPipeline.objects.update_or_create(
            name="Импорт", defaults={"passes": [{"name": "merge_sources"}]}
        )

        response = self.client.post(
            f"/curation/{history.pk}/run-edit/", {"pipeline": pipeline.pk}
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        delay.assert_called_once_with(
            history_id=history.pk, pipeline_id=pipeline.pk
        )

    def test_history_source_add_records_audit(self):
        ts = timezone.now()
        history = GameHistory.objects.create(game=None, creation_time=ts)

        response = self.client.post(
            f"/curation/{history.pk}/sources/add/",
            {
                "type": GameSource.SourceType.IFWIKI,
                "url": " https://example.com/new ",
            },
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        source = GameSource.objects.get(history=history)
        self.assertEqual(source.type, GameSource.SourceType.IFWIKI)
        self.assertEqual(source.url, "https://example.com/new")
        audit = GameHistoryAuditLog.objects.get(history=history)
        self.assertEqual(
            audit.kind, GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED
        )
        self.assertEqual(audit.actor, self.user)
        self.assertEqual(audit.new_id, source.pk)
        self.assertIn("IFWiki", audit.new_text)
        history.refresh_from_db()
        self.assertIsNotNone(history.edit_time)

    def test_history_source_add_reuses_orphan_with_same_type_and_url(self):
        ts = timezone.now()
        history = GameHistory.objects.create(game=None, creation_time=ts)
        orphan = GameSource.objects.create(
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/new",
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/add/",
            {
                "type": GameSource.SourceType.IFWIKI,
                "url": " https://example.com/new ",
            },
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        orphan.refresh_from_db()
        self.assertEqual(orphan.history, history)
        self.assertEqual(GameSource.objects.count(), 1)
        self.assertEqual(GameHistoryAuditLog.objects.get().new_id, orphan.pk)

    def test_history_source_add_rejects_attached_duplicate_url(self):
        ts = timezone.now()
        history = GameHistory.objects.create(game=None, creation_time=ts)
        other = GameHistory.objects.create(game=None, creation_time=ts)
        GameSource.objects.create(
            history=other,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/new",
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/add/",
            {
                "type": GameSource.SourceType.IFWIKI,
                "url": "https://example.com/new",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(GameSource.objects.count(), 1)
        self.assertFalse(GameHistoryAuditLog.objects.exists())

    def test_history_source_add_attaches_orphan_by_id(self):
        ts = timezone.now()
        history = GameHistory.objects.create(game=None, creation_time=ts)
        orphan = GameSource.objects.create(
            type=GameSource.SourceType.APERO,
            url="https://example.com/source",
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/add/",
            {"source_id": str(orphan.pk)},
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        orphan.refresh_from_db()
        self.assertEqual(orphan.history, history)
        self.assertEqual(GameHistoryAuditLog.objects.get().new_id, orphan.pk)

    def test_history_source_add_rejects_attached_source_by_id(self):
        ts = timezone.now()
        history = GameHistory.objects.create(game=None, creation_time=ts)
        other = GameHistory.objects.create(game=None, creation_time=ts)
        source = GameSource.objects.create(
            history=other,
            type=GameSource.SourceType.APERO,
            url="https://example.com/source",
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/add/",
            {"source_id": str(source.pk)},
        )

        self.assertEqual(response.status_code, 400)
        source.refresh_from_db()
        self.assertEqual(source.history, other)
        self.assertFalse(GameHistoryAuditLog.objects.exists())

    def test_history_source_add_rejects_unknown_type(self):
        history = GameHistory.objects.create(
            game=None, creation_time=timezone.now()
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/add/",
            {"type": "NOPE", "url": "https://example.com/new"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(GameSource.objects.exists())
        self.assertFalse(GameHistoryAuditLog.objects.exists())

    def test_history_source_detach_keeps_source_and_records_audit(self):
        ts = timezone.now()
        history = GameHistory.objects.create(game=None, creation_time=ts)
        source = GameSource.objects.create(
            history=history,
            type=GameSource.SourceType.APERO,
            url="https://example.com/source",
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/{source.pk}/delete/"
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        source.refresh_from_db()
        self.assertIsNone(source.history)
        audit = GameHistoryAuditLog.objects.get(history=history)
        self.assertEqual(
            audit.kind, GameHistoryAuditLog.AuditKind.SOURCE_DETACHED
        )
        self.assertEqual(audit.actor, self.user)
        self.assertEqual(audit.old_id, source.pk)
        self.assertIn("Apero", audit.old_text)
        history.refresh_from_db()
        self.assertIsNotNone(history.edit_time)

    @patch("curation.views.fetch_sources.delay")
    def test_source_fetch_now_enqueues_single_source(self, delay):
        source = GameSource.objects.create(
            type=GameSource.SourceType.APERO,
            url="https://example.com/source",
        )

        response = self.client.post(
            f"/curation/sources/{source.pk}/fetch/", follow=True
        )

        self.assertRedirects(response, f"/curation/sources/{source.pk}/")
        delay.assert_called_once_with(limit=None, source_id=source.pk)
        self.assertContains(
            response, f"Источник #{source.pk} поставлен в очередь."
        )

    @patch("curation.views.fetch_sources.delay")
    def test_history_sources_fetch_now_enqueues_each_source(self, delay):
        ts = timezone.now()
        history = GameHistory.objects.create(game=None, creation_time=ts)
        first = GameSource.objects.create(
            history=history,
            type=GameSource.SourceType.APERO,
            url="https://example.com/one",
        )
        second = GameSource.objects.create(
            history=history,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/two",
        )
        GameSource.objects.create(
            type=GameSource.SourceType.QSP,
            url="https://example.com/orphan",
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/fetch/", follow=True
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        self.assertEqual(
            [call.kwargs for call in delay.call_args_list],
            [
                {"limit": None, "source_id": first.pk},
                {"limit": None, "source_id": second.pk},
            ],
        )
        self.assertContains(response, "Источники поставлены в очередь: 2.")


class InitCurationCommandTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        user_model = get_user_model()
        self.bot = user_model.objects.create(
            username=settings.MAINTENANCE_USER, email="robot@db.crem.xyz"
        )
        self.game_page = GameURLCategory.objects.create(
            symbolic_id="game_page", title="Game page"
        )
        self.play_online = GameURLCategory.objects.create(
            symbolic_id="play_online", title="Play online"
        )
        self.video = GameURLCategory.objects.create(
            symbolic_id="video", title="Video"
        )

    def _game(self, title, edit_time=None):
        return Game.objects.create(
            title=title,
            added_by=self.bot,
            creation_time=self.now,
            edit_time=edit_time,
        )

    def _link(self, game, original_url, category):
        url = URL.objects.create(
            original_url=original_url,
            creation_date=self.now,
            creator=self.bot,
        )
        GameURL.objects.create(game=game, url=url, category=category)

    def _run(self):
        call_command("initcuration", stdout=StringIO())

    def test_seeds_histories_sources_and_audit(self):
        bot_game = self._game("Bot game")
        self._link(bot_game, "http://ifwiki.ru/Игра", self.game_page)
        self._link(
            bot_game,
            "https://apero.ru/Текстовые-игры/example",
            self.play_online,
        )
        # Only source categories are sources, even when another category points
        # at a recognized provider.
        self._link(bot_game, "http://ifwiki.ru/Видео", self.video)
        # An unrecognized game_page link is skipped, not turned into a source.
        self._link(bot_game, "https://youtube.com/watch?v=x", self.game_page)

        # Bot-added but human-edited ⇒ PROPOSE rather than ACCEPT.
        edited_game = self._game("Edited game", edit_time=self.now)
        self._link(edited_game, "http://ifwiki.ru/Другая", self.game_page)

        self._run()

        bot_history = GameHistory.objects.get(game=bot_game)
        self.assertEqual(
            bot_history.auto_updates, GameHistory.AutoUpdate.ACCEPT
        )
        self.assertEqual(
            bot_history.state, GameHistory.State.SCHEDULED_FOR_UPDATE
        )
        self.assertEqual(
            list(
                GameSource.objects
                .filter(history=bot_history)
                .order_by("pk")
                .values_list("type", flat=True)
            ),
            [GameSource.SourceType.IFWIKI, GameSource.SourceType.APERO],
        )
        self.assertEqual(
            GameHistoryAuditLog.objects.filter(
                history=bot_history,
                kind=GameHistoryAuditLog.AuditKind.INITIAL_IMPORT,
            ).count(),
            1,
        )

        edited_history = GameHistory.objects.get(game=edited_game)
        self.assertEqual(
            edited_history.auto_updates, GameHistory.AutoUpdate.PROPOSE
        )

    def test_idempotent(self):
        game = self._game("Bot game")
        self._link(game, "http://ifwiki.ru/Игра", self.game_page)

        self._run()
        self._run()

        self.assertEqual(GameHistory.objects.count(), 1)
        self.assertEqual(GameSource.objects.count(), 1)
        self.assertEqual(
            GameHistoryAuditLog.objects.filter(
                kind=GameHistoryAuditLog.AuditKind.INITIAL_IMPORT
            ).count(),
            1,
        )

    def test_deduplicates_sources_by_provider_identity_per_game(self):
        game = self._game("Bot game")
        self._link(
            game,
            "https://forum.ifiction.ru/viewtopic.php?id=42&lid=1",
            self.game_page,
        )
        self._link(
            game,
            "https://forum.ifiction.ru/viewtopic.php?id=42&lid=2",
            self.game_page,
        )

        self._run()

        history = GameHistory.objects.get(game=game)
        self.assertEqual(GameSource.objects.filter(history=history).count(), 1)
        self.assertEqual(
            GameSource.objects.get(history=history).url,
            "https://forum.ifiction.ru/viewtopic.php?id=42&lid=1",
        )


@override_settings(CURATION_EDIT_PASSES=["merge_sources"])
class EditRunnerTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.pipeline = EditPipeline.objects.create(
            name="Test", passes=[{"name": "merge_sources"}]
        )

    def _history(self, **kwargs):
        return GameHistory.objects.create(creation_time=self.now, **kwargs)

    def _source(self, history, type, name, desc):
        source = GameSource.objects.create(
            history=history,
            url=f"https://example.com/{type}",
            type=type,
        )
        canonical = GameInfo(name=name, description=desc).to_canonical()
        fetch = GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            canonical_text=canonical,
            canonical_text_hash=str(hash(canonical)),
            first_fetch=self.now,
            last_fetch=self.now,
        )
        return fetch

    def _canonical_source(
        self, history, canonical, type=GameSource.SourceType.IFWIKI
    ):
        source = GameSource.objects.create(
            history=history,
            url=f"https://example.com/{type}/{GameSource.objects.count()}",
            type=type,
        )
        return GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            canonical_text=canonical,
            canonical_text_hash=str(hash(canonical)),
            first_fetch=self.now,
            last_fetch=self.now,
        )

    def _set_pipeline(self, passes):
        self.pipeline.passes = passes
        self.pipeline.save(update_fields=["passes"])

    def test_merge_applies_in_priority_order(self):
        history = self._history(game=None)
        wiki = self._source(
            history, GameSource.SourceType.IFWIKI, "Wiki Title", "Wiki desc"
        )
        apero = self._source(
            history, GameSource.SourceType.APERO, "Apero Title", "Apero desc"
        )

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
        self.assertIsNotNone(history.game)
        # IFWIKI (priority 100) wins the title over APERO (49).
        self.assertEqual(history.game.title, "Wiki Title")
        # Descriptions concatenate in priority order.
        self.assertEqual(
            history.game.description, "Wiki desc\n\n---\n\nApero desc"
        )

        edit = GameEdit.objects.get(history=history)
        self.assertEqual(edit.status, GameEdit.EditStatus.APPLIED)
        self.assertEqual(edit.passes, [{"name": "merge_sources"}])
        self.assertEqual(set(edit.used_sources.all()), {wiki, apero})

    def test_rerun_is_idempotent(self):
        history = self._history(game=None)
        self._source(
            history, GameSource.SourceType.IFWIKI, "Wiki Title", "Wiki desc"
        )
        self._source(
            history, GameSource.SourceType.APERO, "Apero Title", "Apero desc"
        )
        run_edit(pipeline_id=self.pipeline.pk)

        history.refresh_from_db()
        GameHistory.objects.filter(pk=history.pk).update(
            state=GameHistory.State.SCHEDULED_FOR_UPDATE
        )
        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.unchanged, 1)
        self.assertEqual(GameEdit.objects.filter(history=history).count(), 1)
        history.refresh_from_db()
        # Description was not re-concatenated across runs.
        self.assertEqual(
            history.game.description, "Wiki desc\n\n---\n\nApero desc"
        )

    def test_merge_keeps_existing_related_data_and_scalar_fallbacks(self):
        game = Game.objects.create(
            title="Old Title",
            description="Old desc",
            release_date="2001-02-03",
            creation_time=self.now,
        )
        history = self._history(game=game)
        role = GameAuthorRole.objects.create(
            symbolic_id="author", title="Author"
        )
        old_author = PersonalityAlias.objects.create(name="Old Author")
        source_author = PersonalityAlias.objects.create(name="Source Author")
        GameAuthor.objects.create(game=game, role=role, author=old_author)
        cat = GameTagCategory.objects.create(symbolic_id="tag", name="Tag")
        old_tag = GameTag.objects.create(category=cat, name="old")
        source_tag = GameTag.objects.create(category=cat, name="source")
        game.tags.add(old_tag)
        urlcat = GameURLCategory.objects.create(
            symbolic_id="game", title="Game", allow_cloning=False
        )
        GameURLCategory.objects.create(
            symbolic_id="play_in_interpreter",
            title="Play in interpreter",
            allow_cloning=False,
        )
        old_url = URL.objects.create(
            original_url="https://example.com/old.zip",
            creation_date=self.now,
        )
        GameURL.objects.create(
            game=game, category=urlcat, url=old_url, description="old file"
        )
        old_attr = GameDescriptionAttribution.objects.create(name="old source")
        source_attr = GameDescriptionAttribution.objects.create(name="wiki")
        game.description_attributions.add(old_attr)
        canonical = f"""---
- name: Source Title
- personalities:
    author:
      - {source_author.id}
- tags:
  - ["tag", {source_tag.id}]
- urls:
  - ["game", "source file", "https://example.com/source.zip"]
- attributions:
  - {source_attr.id}
---
Source desc"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.applied, 1)
        game.refresh_from_db()
        self.assertEqual(game.title, "Source Title")
        self.assertEqual(game.release_date.isoformat(), "2001-02-03")
        self.assertEqual(game.description, "Source desc")
        self.assertEqual(
            set(game.gameauthor_set.values_list("author__name", flat=True)),
            {"Old Author", "Source Author"},
        )
        self.assertEqual(
            set(game.tags.values_list("name", flat=True)), {"old", "source"}
        )
        self.assertEqual(
            set(game.gameurl_set.values_list("url__original_url", flat=True)),
            {
                "https://example.com/old.zip",
                "https://example.com/source.zip",
            },
        )
        self.assertEqual(
            set(game.description_attributions.values_list("name", flat=True)),
            {"old source", "wiki"},
        )

    def test_merge_keeps_served_description_when_source_empty(self):
        game = Game.objects.create(
            title="Old Title",
            description="Old desc",
            creation_time=self.now,
        )
        history = self._history(game=game)
        cat = GameTagCategory.objects.create(symbolic_id="tag", name="Tag")
        source_tag = GameTag.objects.create(category=cat, name="source")
        canonical = f"""---
- name: Source Title
- tags:
  - ["tag", {source_tag.id}]
---
"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.applied, 1)
        game.refresh_from_db()
        self.assertEqual(game.title, "Source Title")
        self.assertEqual(game.description, "Old desc")

    def test_cleanup_text_normalizes_description(self):
        self._set_pipeline([
            {"name": "merge_sources"},
            {"name": "cleanup_text"},
        ])
        history = self._history(game=None)
        canonical = """---
- name: Source Title
---


First   paragraph
   
  * * *  



Second    paragraph

"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(
            history.game.description, "First paragraph\n\nSecond paragraph\n"
        )
        edit = GameEdit.objects.get(history=history)
        self.assertEqual(
            edit.passes, [{"name": "merge_sources"}, {"name": "cleanup_text"}]
        )

    def test_cleanup_text_removes_empty_sections(self):
        self._set_pipeline([
            {"name": "merge_sources"},
            {"name": "cleanup_text"},
        ])
        history = self._history(game=None)
        canonical = """---
- name: Source Title
---
# Empty top

## Child has content
Text

## Empty sibling

## Next sibling
Text

### Empty child

## Parent sibling
Text

## Empty tail"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(
            history.game.description,
            (
                "# Empty top\n\n"
                "## Child has content\nText\n\n"
                "## Next sibling\nText\n\n"
                "## Parent sibling\nText\n"
            ),
        )

    def test_cleanup_text_treats_separator_as_section_end(self):
        self._set_pipeline([
            {"name": "merge_sources"},
            {"name": "cleanup_text"},
        ])
        history = self._history(game=None)
        wiki = GameInfo(
            name="Source Title",
            description="# Real section\nText\n\n## Empty before separator",
        ).to_canonical()
        apero = GameInfo(description="Apero text").to_canonical()
        self._canonical_source(history, wiki, GameSource.SourceType.IFWIKI)
        self._canonical_source(history, apero, GameSource.SourceType.APERO)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(
            history.game.description,
            "# Real section\nText\n\n---\n\nApero text\n",
        )

    def test_merge_deduplicates_equivalent_urls(self):
        game = Game.objects.create(title="Tell", creation_time=self.now)
        history = self._history(game=game)
        play_online = GameURLCategory.objects.create(
            symbolic_id="play_online", title="Play online"
        )
        GameURLCategory.objects.create(
            symbolic_id="play_in_interpreter", title="Play in interpreter"
        )
        url = URL.objects.create(
            original_url=(
                "http://iplayif.com/?story="
                "http://rinform.stormway.ru/games/wtell/WTellR.z5"
            ),
            creation_date=self.now,
        )
        GameURL.objects.create(game=game, category=play_online, url=url)
        canonical = """---
- name: Tell
- urls:
  - ["play_online", "Играть онлайн", "http://iplayif.com/?story=http://rinform.org/games/wtell/WTellR.z5"]
---
"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.unchanged, 1)
        self.assertFalse(GameEdit.objects.filter(history=history).exists())

    def test_merge_deduplicates_existing_exact_url(self):
        game = Game.objects.create(title="Tell", creation_time=self.now)
        history = self._history(game=game)
        game_page = GameURLCategory.objects.create(
            symbolic_id="game_page", title="Game page"
        )
        url = URL.objects.create(
            original_url=(
                "https://ifwiki.ru/%D0%92%D0%B8%D0%BB%D1%8C%D0%B3"
                "%D0%B5%D0%BB%D1%8C%D0%BC_%D0%A2%D0%B5%D0%BB"
                "%D0%BB%D1%8C"
            ),
            creation_date=self.now,
        )
        GameURL.objects.create(game=game, category=game_page, url=url)
        canonical = f"""---
- name: Tell
- urls:
  - ["game_page", "{url.original_url}"]
---
"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.unchanged, 1)
        self.assertFalse(GameEdit.objects.filter(history=history).exists())

    def test_merge_can_drop_existing_data(self):
        self._set_pipeline([{"name": "merge_sources", "keep_existing": False}])
        game = Game.objects.create(
            title="Old Title",
            description="Old desc",
            release_date="2001-02-03",
            creation_time=self.now,
        )
        history = self._history(game=game)
        cat = GameTagCategory.objects.create(symbolic_id="tag", name="Tag")
        game.tags.add(GameTag.objects.create(category=cat, name="old"))
        canonical = "---\n- name: Source Title\n---\nSource desc"
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.applied, 1)
        game.refresh_from_db()
        self.assertEqual(game.title, "Source Title")
        self.assertIsNone(game.release_date)
        self.assertEqual(game.description, "Source desc")
        self.assertEqual(game.tags.count(), 0)

    def test_propose_policy_does_not_apply(self):
        history = self._history(
            game=None, auto_updates=GameHistory.AutoUpdate.PROPOSE
        )
        self._source(
            history, GameSource.SourceType.IFWIKI, "Wiki Title", "Wiki desc"
        )

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.proposed, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertIsNone(history.game)
        edit = GameEdit.objects.get(history=history)
        self.assertEqual(edit.status, GameEdit.EditStatus.PROPOSED)
        self.assertEqual(Game.objects.count(), 0)

    def test_proposed_edit_is_canonicalized_before_diff(self):
        history = self._history(
            game=None, auto_updates=GameHistory.AutoUpdate.PROPOSE
        )
        language_cat = GameTagCategory.objects.create(
            symbolic_id="language", name="Language"
        )
        language = GameTag.objects.create(
            category=language_cat, name="русский"
        )
        source = GameSource.objects.create(
            history=history,
            url="https://example.com/source",
            type=GameSource.SourceType.IFWIKI,
        )
        canonical = '---\n- tags:\n  - ["language", "русский"]\n---\n'
        GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            canonical_text=canonical,
            canonical_text_hash=str(hash(canonical)),
            first_fetch=self.now,
            last_fetch=self.now,
        )

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.proposed, 1)
        edit = GameEdit.objects.get(history=history)
        self.assertIn(f'["language", {language.id}]', edit.canonical_text)
        self.assertNotIn('["language", "русский"]', edit.canonical_text)

    @override_settings(CURATION_EDIT_PASSES=["merge_sources", "enrich"])
    def test_enrichment_replaces_canonicalized_tag_genres(self):
        self._set_pipeline(["merge_sources", "enrich"])
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())
        call_command("initenrichment", stdout=StringIO())
        history = self._history(
            game=None, auto_updates=GameHistory.AutoUpdate.PROPOSE
        )
        tag_cat = GameTagCategory.objects.get(symbolic_id="tag")
        GameTag.objects.create(category=tag_cat, name="детское")
        GameTag.objects.create(category=tag_cat, name="сказка")
        canonical = """---
- name: Source Title
- tags:
  - ["tag", "Детское"]
  - ["tag", "Сказка"]
---
"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.proposed, 1)
        edit = GameEdit.objects.get(history=history)
        self.assertEqual(edit.canonical_text.count('"g_fairytale"'), 1)
        self.assertEqual(edit.canonical_text.count('"g_kids"'), 1)
        self.assertNotIn('["tag",', edit.canonical_text)

    def test_enrichment_deduplicates_existing_and_mapped_genre_slug(self):
        self._set_pipeline(["merge_sources", "enrich"])
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())
        call_command("initenrichment", stdout=StringIO())
        game = Game.objects.create(
            title="Old Title",
            description="Old desc",
            creation_time=self.now,
        )
        fantasy = GameTag.objects.get(symbolic_id="g_fantasy")
        game.tags.add(fantasy)
        history = self._history(
            game=game, auto_updates=GameHistory.AutoUpdate.PROPOSE
        )
        tag_cat = GameTagCategory.objects.get(symbolic_id="tag")
        GameTag.objects.create(category=tag_cat, name="фэнтези")
        canonical = """---
- name: Source Title
- tags:
  - ["tag", "Фэнтези"]
---
Source desc"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.proposed, 1)
        edit = GameEdit.objects.get(history=history)
        self.assertEqual(edit.canonical_text.count('"g_fantasy"'), 1)
