from datetime import timedelta
from html import unescape
from io import StringIO
from json import dumps, loads
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import cast
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from contest.models import (
    Competition,
    CompetitionQuestion,
    CompetitionVote,
    GameList,
    GameListEntry,
)
from core.models import BlogFeed, FeedCache
from games.gameinfo import GameInfo, GameUrl
from games.models import (
    URL,
    Game,
    GameAuthor,
    GameAuthorRole,
    GameDescriptionAttribution,
    GameRevision,
    GameTag,
    GameTagCategory,
    GameURL,
    GameURLCategory,
    PersonalityAlias,
)
from play.blueprint import (
    BlueprintInfo,
    BlueprintModule,
    BlueprintSpec,
    GenerateSpec,
)

from .edit import run_edit
from .models import (
    EditPipeline,
    GameCuration,
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
    def _history(self, **kwargs):
        if "game" not in kwargs:
            kwargs["game"] = Game.objects.create(
                state=Game.State.PUBLISHED,
                title="Smoke Game",
                creation_time=timezone.now(),
            )
        kwargs.pop("creation_time", None)
        return GameCuration.objects.create(**kwargs)

    def _proposed_edit(self, history):
        return GameRevision.objects.create(
            game=history.game,
            created_at=timezone.now(),
            status=GameRevision.Status.PROPOSED,
            origin=GameRevision.Origin.AUTO_IMPORT,
            canonical_text="# Game\n---\ntitle: Game",
        )

    @override_settings(
        ADMINS=[("Admin", "admin@example.com")],
        CURATION_NOTIFICATION_EMAIL="curation@example.com",
        CURATION_NOTIFICATION_BASE_URL="https://example.com",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_needs_attention_creation_sends_notification(self):
        with self.captureOnCommitCallbacks(execute=True):
            history = self._history(
                state=GameCuration.State.NEEDS_ATTENTION,
                note='Needs "manual" review & more',
            )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["curation@example.com"])
        self.assertNotIn("admin@example.com", message.to)
        self.assertIn("Модерация", message.subject)
        self.assertIn(f"Админка: #{history.pk}", message.body)
        self.assertIn('Needs "manual" review & more', message.body)
        self.assertNotIn("&quot;", message.body)
        self.assertNotIn("&amp;", message.body)
        self.assertIn(
            f"https://example.com/curation/{history.pk}/", message.body
        )

    @override_settings(
        CURATION_NOTIFICATION_EMAIL="curation@example.com",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_transition_to_needs_attention_sends_notification(self):
        history = self._history()

        with self.captureOnCommitCallbacks(execute=True):
            history.state = GameCuration.State.NEEDS_ATTENTION
            history.save(update_fields=["state"])

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["curation@example.com"])

    @override_settings(
        CURATION_NOTIFICATION_EMAIL="curation@example.com",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_repeated_needs_attention_save_does_not_duplicate_notification(
        self,
    ):
        with self.captureOnCommitCallbacks(execute=True):
            history = self._history(
                state=GameCuration.State.NEEDS_ATTENTION,
            )

        with self.captureOnCommitCallbacks(execute=True):
            history.save(update_fields=["state"])

        self.assertEqual(len(mail.outbox), 1)

    @override_settings(
        CURATION_NOTIFICATION_EMAIL=None,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_needs_attention_notification_can_be_disabled(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._history(
                state=GameCuration.State.NEEDS_ATTENTION,
            )

        self.assertEqual(mail.outbox, [])

    def test_note_survives_non_attention_model_save(self):
        history = self._history(
            state=GameCuration.State.NEEDS_ATTENTION,
            note="Needs manual review",
        )

        history.state = GameCuration.State.SETTLED
        history.save()

        history.refresh_from_db()
        self.assertEqual(history.note, "Needs manual review")

    def test_note_survives_non_attention_update_fields_save(self):
        history = self._history(
            state=GameCuration.State.NEEDS_ATTENTION,
            note="Needs manual review",
        )

        history.state = GameCuration.State.SCHEDULED_FOR_UPDATE
        history.save(update_fields=["state"])

        history.refresh_from_db()
        self.assertEqual(history.note, "Needs manual review")

    def test_leaving_needs_attention_rejects_pending_edit(self):
        history = self._history(
            state=GameCuration.State.NEEDS_ATTENTION,
        )
        edit = self._proposed_edit(history)

        history.state = GameCuration.State.SETTLED
        history.save()

        edit.refresh_from_db()
        self.assertEqual(edit.status, GameRevision.Status.REJECTED)

    def test_leaving_needs_attention_with_update_fields_rejects_pending_edit(
        self,
    ):
        history = self._history(
            state=GameCuration.State.NEEDS_ATTENTION,
        )
        edit = self._proposed_edit(history)

        history.state = GameCuration.State.SCHEDULED_FOR_UPDATE
        history.save(update_fields=["state"])

        edit.refresh_from_db()
        self.assertEqual(edit.status, GameRevision.Status.REJECTED)

    def test_needs_attention_save_without_state_change_keeps_pending_edit(
        self,
    ):
        history = self._history(
            state=GameCuration.State.NEEDS_ATTENTION,
            note="Needs manual review",
        )
        edit = self._proposed_edit(history)

        history.note = "Still needs manual review"
        history.save(update_fields=["note"])

        edit.refresh_from_db()
        self.assertEqual(edit.status, GameRevision.Status.PROPOSED)

    def test_applied_edit_survives_history_state_change(self):
        history = self._history(
            state=GameCuration.State.NEEDS_ATTENTION,
        )
        edit = self._proposed_edit(history)

        edit.status = GameRevision.Status.ACCEPTED
        edit.published_at = timezone.now()
        edit.save(update_fields=["status", "published_at"])
        history.state = GameCuration.State.SETTLED
        history.save(update_fields=["state"])

        edit.refresh_from_db()
        self.assertEqual(edit.status, GameRevision.Status.ACCEPTED)

    def test_history_lifecycle(self):
        now = timezone.now()

        # History is created with a draft Game immediately.
        game = Game.objects.create(
            title="Game", state=Game.State.DRAFT, creation_time=now
        )
        history = GameCuration.objects.create(game=game)
        self.assertEqual(history.game, game)
        self.assertEqual(
            history.state, GameCuration.State.SCHEDULED_FOR_UPDATE
        )
        self.assertEqual(history.auto_updates, GameCuration.AutoUpdate.ACCEPT)

        source = GameSource.objects.create(
            game=game,
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

        edit = GameRevision.objects.create(
            game=game,
            created_at=now,
            status=GameRevision.Status.PROPOSED,
            origin=GameRevision.Origin.AUTO_IMPORT,
            canonical_text="# Game\n---\ntitle: Game",
        )
        edit.used_sources.add(fetch)
        self.assertEqual(list(edit.used_sources.all()), [fetch])

        other_edit = GameRevision.objects.create(
            game=game,
            created_at=now,
            status=GameRevision.Status.PROPOSED,
            origin=GameRevision.Origin.MANUAL_EDIT,
            passes=["ManualPass"],
            canonical_text="Updated game text",
        )
        edit.refresh_from_db()
        self.assertEqual(edit.status, GameRevision.Status.REJECTED)
        self.assertEqual(other_edit.status, GameRevision.Status.PROPOSED)
        self.assertEqual(other_edit.passes, ["ManualPass"])

        parent_comment = GameHistoryComment.objects.create(
            game=game,
            type=GameHistoryComment.CommentType.USER_FEEDBACK,
            text="Looks off.",
            creation_time=now,
        )
        reply = GameHistoryComment.objects.create(
            game=game,
            reply_to=parent_comment,
            type=GameHistoryComment.CommentType.MODS_COMMENT,
            text="Fixed.",
            creation_time=now,
        )
        self.assertEqual(reply.reply_to, parent_comment)

        GameHistoryAuditLog.objects.create(
            game=game,
            created_at=now,
            kind="",
            new_id=edit.pk,
        )
        self.assertEqual(game.gamehistoryauditlog_set.count(), 1)


class CurationAccessTest(TestCase):
    def test_regular_user_is_redirected_to_login(self):
        user = get_user_model().objects.create(
            username="user", email="user@example.com"
        )
        self.client.force_login(user)

        response = self.client.get("/curation/")

        self.assertRedirects(
            response,
            f"{settings.LOGIN_URL}?next=/curation/",
            fetch_redirect_response=False,
        )

    def test_moderator_is_redirected_to_login(self):
        user = get_user_model().objects.create(
            username="moder", email="moder@example.com"
        )
        user.groups.add(Group.objects.create(name="moder"))
        self.client.force_login(user)

        response = self.client.get("/curation/")

        self.assertRedirects(
            response,
            f"{settings.LOGIN_URL}?next=/curation/",
            fetch_redirect_response=False,
        )


class HistoryListViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="admin", email="admin@example.com", is_superuser=True
        )
        self.client.force_login(self.user)

    @patch("curation.views.discover_blueprints")
    def test_blueprint_list_shows_discovered_blueprints(self, discover_mock):
        blueprint = ModuleType("play.blueprints.test_blueprint")

        def get_spec() -> BlueprintSpec:
            return BlueprintSpec(name="Test blueprint", versions=["1.0"])

        def generate(_spec: GenerateSpec) -> None:
            pass

        setattr(blueprint, "get_spec", get_spec)
        setattr(blueprint, "generate", generate)
        discover_mock.return_value = [
            BlueprintInfo("test-blueprint", cast(BlueprintModule, blueprint))
        ]

        response = self.client.get("/curation/blueprints/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "curation/blueprint_list.html")
        self.assertEqual(
            response.context["blueprints"],
            [{"display_name": "Test blueprint", "slug": "test-blueprint"}],
        )
        self.assertContains(response, "Проигрыватели")
        self.assertContains(
            response,
            "<title>Проигрыватели - Модерация - db.crem.xyz</title>",
        )
        self.assertContains(response, ">Проигрыватели</a>")
        self.assertContains(response, 'href="/curation/blueprints/"')
        self.assertContains(response, "Test blueprint")
        self.assertContains(response, "test-blueprint")
        discover_mock.assert_called_once_with()

    def test_history_list_is_compact_and_uses_short_labels(self):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Very Long Game Title That Should Be Truncated",
            creation_time=ts,
            added_by=self.user,
        )
        GameCuration.objects.create(
            game=game,
            state=GameCuration.State.NEEDS_ATTENTION,
            auto_updates=GameCuration.AutoUpdate.PROPOSE,
            note="Needs manual review",
        )

        response = self.client.get("/curation/")
        self.assertEqual(response.status_code, 200)
        for text in [
            "curation-history-table",
            '<tr class="curation-history-state--needs_attention"',
            'class="curation-truncate"',
            'title="Very Long Game Title That Should Be Truncated"',
            "внимание",
            "Needs manual review",
            "предл.",
        ]:
            self.assertContains(response, text)

    def test_history_list_links_note_object_refs(self):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Linked Game",
            creation_time=ts,
            added_by=self.user,
        )
        history = GameCuration.objects.create(
            game=game,
            state=GameCuration.State.NEEDS_ATTENTION,
            note="",
        )
        source = GameSource.objects.create(
            game=game,
            type=GameSource.SourceType.QSP,
            url="https://example.com/game",
        )
        history.note = f"See g/{game.pk} and s/{source.pk}"
        history.save(update_fields=["note"])

        response = self.client.get("/curation/")

        self.assertContains(
            response,
            f'<a href="/game/{game.pk}/">g/{game.pk}</a>',
            html=True,
        )
        self.assertContains(
            response,
            f'<a href="/curation/sources/{source.pk}/">s/{source.pk}</a>',
            html=True,
        )

    def test_user_settling_history_clears_note(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Note Game",
            creation_time=timezone.now(),
        )
        history = GameCuration.objects.create(
            game=game,
            state=GameCuration.State.NEEDS_ATTENTION,
            note="Needs manual review",
        )

        response = self.client.post(
            f"/curation/{history.pk}/edit/",
            {"state": GameCuration.State.SETTLED},
        )

        self.assertEqual(response.status_code, 302)
        history.refresh_from_db()
        self.assertEqual(history.state, GameCuration.State.SETTLED)
        self.assertIsNone(history.note)

    def test_history_list_defaults_to_relevance_sort(self):
        ts = timezone.now()
        old_settled = self._create_history(
            "Old settled",
            ts,
            state=GameCuration.State.SETTLED,
        )
        recent_progress = self._create_history(
            "Recent progress",
            ts + timezone.timedelta(days=1),
            state=GameCuration.State.SCHEDULED_FOR_UPDATE,
        )
        older_attention = self._create_history(
            "Older attention",
            ts + timezone.timedelta(days=2),
            state=GameCuration.State.NEEDS_ATTENTION,
        )
        newer_attention = self._create_history(
            "Newer attention",
            ts + timezone.timedelta(days=3),
            state=GameCuration.State.NEEDS_ATTENTION,
        )

        response = self.client.get("/curation/")

        self.assertEqual(
            list(response.context["histories"]),
            [newer_attention, older_attention, recent_progress, old_settled],
        )
        self.assertContains(response, '<option value="relevance" selected>')

    def test_history_list_filters_by_name(self):
        ts = timezone.now()
        self._create_history(
            "Wanted Game", ts, state=GameCuration.State.SETTLED
        )
        self._create_history(
            "Other Game", ts, state=GameCuration.State.SETTLED
        )

        response = self.client.get("/curation/", {"q": "wanted"})

        self.assertContains(response, "Wanted Game")
        self.assertContains(response, 'name="q" value="wanted"')
        self.assertNotContains(response, "Other Game")

    def test_history_list_paginates_and_preserves_filters(self):
        ts = timezone.now()
        games = Game.objects.bulk_create([
            Game(
                state=Game.State.PUBLISHED,
                title=f"Paginated Game {i:03}",
                creation_time=ts,
                added_by=self.user,
            )
            for i in range(501)
        ])
        GameCuration.objects.bulk_create([
            GameCuration(
                game=game,
                state=GameCuration.State.SCHEDULED_FOR_UPDATE,
                auto_updates=GameCuration.AutoUpdate.PROPOSE,
            )
            for game in games
        ])

        response = self.client.get(
            "/curation/",
            {
                "q": "Paginated",
                "state": GameCuration.State.SCHEDULED_FOR_UPDATE,
                "auto": GameCuration.AutoUpdate.PROPOSE,
                "sort": "updated",
            },
        )

        self.assertContains(response, "Страница 1 из 2")
        self.assertEqual(len(response.context["histories"]), 500)
        self.assertContains(
            response,
            "?q=Paginated&state=SCHEDULED_FOR_UPDATE&auto=PROPOSE&sort=updated&page=2",
        )

    def test_history_list_marks_state_rows(self):
        ts = timezone.now()
        self._create_history(
            "Needs attention",
            ts,
            state=GameCuration.State.NEEDS_ATTENTION,
        )
        self._create_history(
            "Scheduled",
            ts,
            state=GameCuration.State.SCHEDULED_FOR_UPDATE,
        )
        self._create_history(
            "Processing",
            ts,
            state=GameCuration.State.PROCESSING,
        )

        response = self.client.get("/curation/")

        for css_class in [
            "curation-history-state--needs_attention",
            "curation-history-state--scheduled_for_update",
            "curation-history-state--processing",
        ]:
            self.assertContains(response, css_class)

    def test_history_list_links_pending_edit(self):
        ts = timezone.now()
        pending_history = self._create_history(
            "Pending", ts, state=GameCuration.State.SETTLED
        )
        old_pending = self._create_edit(
            pending_history,
            ts,
            status=GameRevision.Status.PROPOSED,
        )
        latest_pending = self._create_edit(
            pending_history,
            ts + timezone.timedelta(minutes=1),
            status=GameRevision.Status.PROPOSED,
        )
        old_pending.refresh_from_db()
        self.assertEqual(old_pending.status, GameRevision.Status.REJECTED)
        done_history = self._create_history(
            "Done", ts, state=GameCuration.State.SETTLED
        )
        done_edit = self._create_edit(
            done_history,
            ts,
            status=GameRevision.Status.ACCEPTED,
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
            state=Game.State.PUBLISHED,
            title=title,
            creation_time=updated,
            added_by=self.user,
        )
        game.edit_time = updated
        game.save(update_fields=["edit_time"])
        return GameCuration.objects.create(
            game=game,
            state=state,
        )

    def _create_edit(self, history, created_at, *, status):
        return GameRevision.objects.create(
            game=history.game,
            created_at=created_at,
            status=status,
            origin=GameRevision.Origin.AUTO_IMPORT,
            previous_canonical_text="old",
            canonical_text="new",
        )


class HistoryDetailViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="admin", email="admin@example.com", is_superuser=True
        )
        self.client.force_login(self.user)
        self.now = timezone.now()
        self.game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Commented Game",
            creation_time=self.now,
            added_by=self.user,
        )
        self.history = GameCuration.objects.create(game=self.game)

    def test_history_page_shows_comments_and_comment_form(self):
        GameHistoryComment.objects.create(
            game=self.game,
            user=self.user,
            type=GameHistoryComment.CommentType.MODS_COMMENT,
            text="Existing moderator note.",
            creation_time=self.now,
        )

        response = self.client.get(f"/curation/{self.history.pk}/")

        self.assertContains(response, "Moderator comment")
        self.assertContains(response, "Existing moderator note.")
        self.assertContains(response, "Добавить комментарий")
        self.assertContains(
            response,
            f'action="/curation/{self.history.pk}/comments/add/"',
        )
        self.assertContains(response, 'name="text"')

    def test_history_page_links_note_object_refs_and_escapes_text(self):
        source = GameSource.objects.create(
            game=self.game,
            type=GameSource.SourceType.QSP,
            url="https://example.com/game",
        )
        self.history.note = (
            f"See g/{self.game.pk} and s/{source.pk}\n<script>x</script>"
        )
        self.history.save(update_fields=["note"])

        response = self.client.get(f"/curation/{self.history.pk}/")

        self.assertContains(
            response,
            (
                '<div class="game--info-row-value curation-rich-text">'
                f'See <a href="/game/{self.game.pk}/">g/{self.game.pk}</a> '
                f'and <a href="/curation/sources/{source.pk}/">'
                f"s/{source.pk}</a><br>&lt;script&gt;x&lt;/script&gt;</div>"
            ),
        )
        self.assertContains(
            response,
            f'<a href="/game/{self.game.pk}/">g/{self.game.pk}</a>',
            html=True,
        )
        self.assertContains(
            response,
            f'<a href="/curation/sources/{source.pk}/">s/{source.pk}</a>',
            html=True,
        )
        self.assertContains(response, "<br>&lt;script&gt;x&lt;/script&gt;")
        self.assertNotContains(response, "<script>x</script>")

    def test_post_comment_creates_mods_comment(self):
        response = self.client.post(
            f"/curation/{self.history.pk}/comments/add/",
            {"text": "Please verify the source."},
        )

        self.assertRedirects(response, f"/curation/{self.history.pk}/")
        comment = GameHistoryComment.objects.get(game=self.game)
        self.assertEqual(comment.user, self.user)
        self.assertEqual(
            comment.type, GameHistoryComment.CommentType.MODS_COMMENT
        )
        self.assertEqual(comment.text, "Please verify the source.")

    def test_blank_comment_is_ignored(self):
        response = self.client.post(
            f"/curation/{self.history.pk}/comments/add/",
            {"text": "  "},
        )

        self.assertRedirects(response, f"/curation/{self.history.pk}/")
        self.assertFalse(GameHistoryComment.objects.exists())

    def test_history_page_shows_delete_dialog(self):
        response = self.client.get(f"/curation/{self.history.pk}/")

        self.assertContains(response, "Удаление")
        self.assertContains(response, 'data-dialog="history-delete-dialog"')
        self.assertContains(
            response,
            f'action="/curation/{self.history.pk}/delete/"',
        )
        self.assertContains(response, 'name="keep_orphans"')
        self.assertContains(response, "оставить источники сиротами")

    def test_history_delete_deletes_game_and_keeps_sources_orphan(self):
        source = GameSource.objects.create(
            game=self.game,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/source",
        )

        response = self.client.post(
            f"/curation/{self.history.pk}/delete/",
            {"keep_orphans": "on"},
        )

        self.assertRedirects(response, f"/curation/{self.history.pk}/")
        self.game.refresh_from_db()
        self.assertEqual(self.game.state, Game.State.ABANDONED)
        self.history.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(self.history.game_id, self.game.pk)
        self.assertEqual(self.history.state, GameCuration.State.ABANDONED)
        self.assertIsNone(source.game_id)
        self.assertTrue(source.keep_orphan)
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=self.game,
                kind=GameHistoryAuditLog.AuditKind.SOURCE_DETACHED,
                old_id=source.pk,
            ).exists()
        )
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=self.game,
                field=GameHistoryAuditLog.AuditField.STATE,
                new_text=GameCuration.State.ABANDONED,
            ).exists()
        )

    def test_history_delete_blocks_contest_references(self):
        gamelist = GameList.objects.create(title="Contest games")
        GameListEntry.objects.create(gamelist=gamelist, game=self.game)

        response = self.client.post(f"/curation/{self.history.pk}/delete/")

        self.assertRedirects(response, f"/curation/{self.history.pk}/")
        self.assertTrue(Game.objects.filter(pk=self.game.pk).exists())
        self.history.refresh_from_db()
        self.assertEqual(self.history.game_id, self.game.pk)
        self.assertNotEqual(self.history.state, GameCuration.State.ABANDONED)


class HistoryMergeViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="admin", email="admin@example.com", is_superuser=True
        )
        self.client.force_login(self.user)
        self.now = timezone.now()

    def _history(self, title):
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title=title, creation_time=self.now
        )
        return GameCuration.objects.create(game=game)

    def test_history_page_shows_merge_form(self):
        history = self._history("Target")

        response = self.client.get(f"/curation/{history.pk}/")

        self.assertContains(response, "Объединить с другой игрой")
        self.assertContains(response, 'name="source_game_id"')
        self.assertContains(response, 'name="remap_contests"')

    def test_history_page_shows_controls_in_sidebar(self):
        history = self._history("Target")
        EditPipeline.objects.update_or_create(
            name="Импорт", defaults={"passes": []}
        )

        response = self.client.get(f"/curation/{history.pk}/")
        content = response.content.decode()

        self.assertContains(response, f"Информация ({history.pk})")
        self.assertContains(
            response,
            '<div class="game--info-row"><div class="game--info-row-label">'
            'Игра</div><div class="game--info-row-value">'
            f'<a href="/game/{history.game.pk}/">Target</a></div></div>',
            html=True,
        )
        self.assertContains(
            response,
            '<div class="game--info-row"><div class="game--info-row-label">'
            'GameId</div><div class="game--info-row-value">'
            f"{history.game.pk}</div></div>",
            html=True,
        )
        self.assertNotContains(
            response,
            f'<div class="card--header"><a href="/game/{history.game.pk}/">'
            "Target</a></div>",
            html=True,
        )
        for earlier, later in [
            (
                '<div class="card--header">Модерация</div>',
                f"Информация ({history.pk})",
            ),
            (f"Информация ({history.pk})", "Автоматическая обработка"),
            ("Автоматическая обработка", "Объединить с другой игрой"),
        ]:
            self.assertLess(content.index(earlier), content.index(later))

    def test_merge_blocks_contest_references_without_checkbox(self):
        target = self._history("Target")
        source = self._history("Source")
        gamelist = GameList.objects.create(title="Contest games")
        GameListEntry.objects.create(gamelist=gamelist, game=source.game)

        response = self.client.post(
            f"/curation/{target.pk}/merge/",
            {"source_game_id": source.game_id},
        )

        self.assertRedirects(response, f"/curation/{target.pk}/")
        self.assertTrue(Game.objects.filter(pk=source.game_id).exists())
        self.assertEqual(GameListEntry.objects.get().game, source.game)

    def test_merge_with_checkbox_remaps_contests_and_abandons_source_history(
        self,
    ):
        target = self._history("Target")
        source = self._history("Source")
        source.game.description = "Source description"
        source.game.save(update_fields=["description"])
        GameSource.objects.create(
            game=source.game,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/source",
        )
        gamelist = GameList.objects.create(title="Contest games")
        entry = GameListEntry.objects.create(
            gamelist=gamelist, game=source.game
        )
        competition = Competition.objects.create(
            title="Contest",
            slug="contest",
            end_date=self.now.date(),
            published=True,
        )
        vote = CompetitionVote.objects.create(
            competition=competition,
            user=self.user,
            when=self.now,
            game=source.game,
            field="rating",
        )
        question = CompetitionQuestion.objects.create(
            game=source.game,
            question_id="q1",
            text="Question?",
        )
        source_game_id = source.game_id

        response = self.client.post(
            f"/curation/{target.pk}/merge/",
            {"source_game_id": source_game_id, "remap_contests": "on"},
        )

        self.assertRedirects(response, f"/curation/{target.pk}/")
        self.assertTrue(Game.objects.filter(pk=source_game_id).exists())
        target.refresh_from_db()
        source.refresh_from_db()
        source_game = Game.objects.get(pk=source_game_id)
        self.assertEqual(source_game.state, Game.State.REDIRECT)
        self.assertEqual(source_game.redirect_to_id, target.game_id)
        self.assertEqual(source.state, GameCuration.State.ABANDONED)
        self.assertEqual(source.game_id, source_game_id)
        self.assertEqual(
            list(target.game.gamesource_set.values_list("url", flat=True)),
            ["https://example.com/source"],
        )
        for obj in [entry, vote, question]:
            obj.refresh_from_db()
            self.assertEqual(obj.game_id, target.game_id)
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=target.game,
                kind=GameHistoryAuditLog.AuditKind.GAME_MERGED,
                old_id=source_game_id,
                new_id=target.game_id,
            ).exists()
        )
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=source_game,
                field=GameHistoryAuditLog.AuditField.STATE,
                new_text=GameCuration.State.ABANDONED,
            ).exists()
        )


class HistoryReconcileViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="admin", email="admin@example.com", is_superuser=True
        )
        self.client.force_login(self.user)
        self.now = timezone.now()

    def _history(self, title="Base"):
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title=title,
            description="Base description",
            creation_time=self.now,
        )
        return GameCuration.objects.create(game=game)

    def _source(self, history, url):
        source = GameSource.objects.create(
            game=history.game,
            type=GameSource.SourceType.IFWIKI,
            url=url,
            created_at=self.now,
        )
        GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash=url,
            first_fetch=self.now,
            last_fetch=self.now,
        )
        return source

    def _metadata(self, game):
        role = GameAuthorRole.objects.create(
            symbolic_id="author", title="Author"
        )
        alias = PersonalityAlias.objects.create(name="Author")
        GameAuthor.objects.create(game=game, role=role, author=alias)
        cat = GameTagCategory.objects.create(symbolic_id="genre", name="Genre")
        tag = GameTag.objects.create(category=cat, name="Tag")
        game.tags.add(tag)
        urlcat = GameURLCategory.objects.create(
            symbolic_id="game_page", title="Game page"
        )
        url = URL.objects.create(
            original_url="https://example.com/game",
            creation_date=self.now,
        )
        GameURL.objects.create(
            game=game, category=urlcat, url=url, description="homepage"
        )
        attr = GameDescriptionAttribution.objects.create(name="source")
        game.description_attributions.add(attr)

    def _column(self, history, *, client_id="base", sources=()):
        game = history.game
        return {
            "client_id": client_id,
            "history_id": history.pk,
            "game_id": game.pk if game else None,
            "title": game.title if game else "",
            "release_date": "",
            "tags": [
                [tag.category_id, tag.id]
                for tag in (game.tags.all() if game else [])
            ],
            "authors": [
                [row.role_id, row.author_id]
                for row in (game.gameauthor_set.all() if game else [])
            ],
            "links": [
                [row.category_id, row.description or "", row.url.original_url]
                for row in (
                    game.gameurl_set.select_related("url") if game else []
                )
            ],
            "description_attributions": [
                row.name
                for row in (
                    game.description_attributions.all() if game else []
                )
            ],
            "description": game.description if game else "",
            "delete": False,
            "sources": [{"id": source.pk} for source in sources],
        }

    def _post(
        self,
        history,
        columns,
        *,
        orphan_source_ids=(),
        keep_orphan_source_ids=(),
        pipeline_by_client_id=None,
    ):
        return self.client.post(
            f"/curation/{history.pk}/reconcile/",
            data=dumps({
                "columns": columns,
                "orphan_source_ids": list(orphan_source_ids),
                "keep_orphan_source_ids": list(keep_orphan_source_ids),
                "pipeline_by_client_id": pipeline_by_client_id or {},
            }),
            content_type="application/json",
        )

    def test_history_page_links_to_reconcile_editor(self):
        history = self._history()

        response = self.client.get(f"/curation/{history.pk}/")

        self.assertContains(response, "Сверить игры")
        self.assertContains(
            response, f'href="/curation/{history.pk}/reconcile/"'
        )
        self.assertNotContains(response, "/split/")

    def test_reconcile_page_renders_editor_shell(self):
        history = self._history()
        pipeline, _ = EditPipeline.objects.update_or_create(
            name="Импорт", defaults={"passes": [{"name": "merge_sources"}]}
        )

        response = self.client.get(f"/curation/{history.pk}/reconcile/")

        self.assertContains(response, "Сверка игр")
        self.assertContains(response, "reconcile.js")
        self.assertContains(response, "reconcile-data")
        self.assertContains(response, "edit_pipelines")
        self.assertContains(response, f'"id": {pipeline.pk}')

    @patch("curation.views.edit_sources.delay")
    def test_reconcile_starts_selected_pipeline_for_existing_history(
        self, delay
    ):
        history = self._history()
        pipeline, _ = EditPipeline.objects.update_or_create(
            name="Импорт", defaults={"passes": [{"name": "merge_sources"}]}
        )

        response = self._post(
            history,
            [self._column(history)],
            pipeline_by_client_id={"base": pipeline.pk},
        )

        self.assertEqual(response.status_code, 200)
        delay.assert_called_once_with(
            game_id=history.pk, pipeline_id=pipeline.pk, force=True
        )

    @patch("curation.views.edit_sources.delay")
    def test_reconcile_starts_selected_pipeline_for_new_history(self, delay):
        history = self._history()
        staying = self._source(history, "https://example.com/stay")
        moving = self._source(history, "https://example.com/move")
        pipeline, _ = EditPipeline.objects.update_or_create(
            name="Импорт", defaults={"passes": [{"name": "merge_sources"}]}
        )
        new_col = self._column(history, client_id="new-1", sources=[moving])
        new_col.update({
            "history_id": None,
            "game_id": None,
            "title": "Split",
        })

        response = self._post(
            history,
            [self._column(history, sources=[staying]), new_col],
            pipeline_by_client_id={"new-1": pipeline.pk},
        )

        split = GameCuration.objects.exclude(pk=history.pk).get()
        self.assertEqual(response.status_code, 200)
        delay.assert_called_once_with(
            game_id=split.pk, pipeline_id=pipeline.pk, force=True
        )

    @patch("curation.views.edit_sources.delay")
    def test_reconcile_rejects_unknown_pipeline(self, delay):
        history = self._history()

        response = self._post(
            history,
            [self._column(history)],
            pipeline_by_client_id={"base": 999},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Обработки не найдены", response.json()["error"])
        delay.assert_not_called()

    def test_reconcile_moves_source_to_new_game_and_copies_metadata(self):
        history = self._history()
        self._metadata(history.game)
        staying = self._source(history, "https://example.com/stay")
        moving = self._source(history, "https://example.com/move")
        new_col = self._column(history, client_id="new-1", sources=[moving])
        new_col.update({
            "history_id": None,
            "game_id": None,
            "title": "Split",
        })

        response = self._post(
            history,
            [self._column(history, sources=[staying]), new_col],
        )

        split = GameCuration.objects.exclude(pk=history.pk).get()
        self.assertEqual(response.status_code, 200)
        self.assertIn("redirect", response.json())
        staying.refresh_from_db()
        moving.refresh_from_db()
        history.refresh_from_db()
        self.assertEqual(staying.game, history.game)
        self.assertEqual(moving.game, split.game)
        self.assertEqual(moving.gamesourcefetch_set.count(), 1)
        self.assertEqual(split.game.title, "Split")
        self.assertEqual(split.game.state, Game.State.PUBLISHED)
        self.assertEqual(split.game.description, "Base description")
        self.assertEqual(history.game.description, "Base description")
        self.assertEqual(history.game.tags.count(), 1)
        self.assertEqual(split.game.tags.count(), 1)
        self.assertEqual(history.game.gameauthor_set.count(), 1)
        self.assertEqual(split.game.gameauthor_set.count(), 1)
        self.assertEqual(history.game.gameurl_set.count(), 1)
        self.assertEqual(split.game.gameurl_set.count(), 1)
        self.assertEqual(
            history.state, GameCuration.State.SCHEDULED_FOR_UPDATE
        )
        self.assertEqual(split.state, GameCuration.State.SCHEDULED_FOR_UPDATE)
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=history.game,
                kind=GameHistoryAuditLog.AuditKind.SOURCE_DETACHED,
                old_id=moving.pk,
            ).exists()
        )
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=split.game,
                kind=GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED,
                new_id=moving.pk,
            ).exists()
        )

    def test_reconcile_blocks_deleting_game_with_contest_references(self):
        history = self._history()
        gamelist = GameList.objects.create(title="Contest games")
        GameListEntry.objects.create(gamelist=gamelist, game=history.game)
        col = self._column(history)
        col["delete"] = True

        response = self._post(history, [col])

        self.assertEqual(response.status_code, 400)
        self.assertIn("конкурсные ссылки", response.json()["error"])
        self.assertTrue(Game.objects.filter(pk=history.game_id).exists())

    def test_reconcile_blocks_deleting_game_with_sources(
        self,
    ):
        history = self._history()
        source = self._source(history, "https://example.com/source")
        game_id = history.game_id
        col = self._column(history, sources=[source])
        col["delete"] = True

        response = self._post(history, [col])

        self.assertEqual(response.status_code, 400)
        self.assertIn("источниками", response.json()["error"])
        self.assertTrue(Game.objects.filter(pk=game_id).exists())
        source.refresh_from_db()
        history.refresh_from_db()
        self.assertEqual(source.game_id, game_id)
        self.assertEqual(history.game_id, game_id)

    def test_reconcile_orphan_source_then_deletes_game(self):
        history = self._history()
        source = self._source(history, "https://example.com/source")
        game_id = history.game_id
        col = self._column(history)
        col["delete"] = True

        response = self._post(history, [col], orphan_source_ids=[source.pk])

        self.assertEqual(response.status_code, 200)
        game = Game.objects.get(pk=game_id)
        self.assertEqual(game.state, Game.State.ABANDONED)
        source.refresh_from_db()
        history.refresh_from_db()
        self.assertIsNone(source.game_id)
        self.assertEqual(history.game_id, game_id)
        self.assertEqual(history.state, GameCuration.State.ABANDONED)
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=history.game,
                kind=GameHistoryAuditLog.AuditKind.SOURCE_DETACHED,
                old_id=source.pk,
            ).exists()
        )

    def test_reconcile_orphan_source_can_keep_it_orphan(self):
        history = self._history()
        source = self._source(history, "https://example.com/source")
        col = self._column(history)

        response = self._post(
            history,
            [col],
            orphan_source_ids=[source.pk],
            keep_orphan_source_ids=[source.pk],
        )

        self.assertEqual(response.status_code, 200)
        source.refresh_from_db()
        self.assertIsNone(source.game_id)
        self.assertTrue(source.keep_orphan)

    def test_reconcile_keep_orphan_requires_detaching_source(self):
        history = self._history()
        source = self._source(history, "https://example.com/source")
        col = self._column(history, sources=[source])

        response = self._post(
            history, [col], keep_orphan_source_ids=[source.pk]
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("без открепления", response.json()["error"])
        source.refresh_from_db()
        self.assertEqual(source.game_id, history.game_id)
        self.assertFalse(source.keep_orphan)


class LlmTrajectoryViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="admin", email="admin@example.com", is_superuser=True
        )
        self.client.force_login(self.user)

        now = timezone.now()
        self.game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Readable Messages",
            creation_time=now,
            added_by=self.user,
        )
        self.history = GameCuration.objects.create(game=self.game)
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
            game=self.game,
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

    def test_list_shows_message_count(self):
        self.trajectory.messages = [{"role": "user", "content": "Hi"}] * 7
        self.trajectory.save(update_fields=["messages"])

        response = self.client.get("/curation/trajectories/")

        self.assertContains(response, "Msgs")
        self.assertContains(response, '<td class="num">7</td>', html=True)

    def test_list_shows_average_cents_per_game(self):
        LlmTrajectory.objects.create(
            game=self.game,
            workflow=self.workflow,
            model=self.model,
            created_at=timezone.now(),
            messages=[],
            prompt_tokens=20,
            cached_input_tokens=4,
            cache_write_tokens=6,
            completion_tokens=8,
            cost="0.000026",
        )

        response = self.client.get("/curation/trajectories/")

        self.assertContains(response, "¢/game")
        self.assertContains(response, '0,002<span class="zeros">0</span>')

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

    def test_detail_shows_current_history_status_and_note(self):
        self.history.state = GameCuration.State.NEEDS_ATTENTION
        self.history.note = "Current note\nSecond line"
        self.history.save(update_fields=["state", "note"])

        response = self.client.get(
            f"/curation/trajectories/{self.trajectory.pk}/"
        )

        self.assertContains(response, "Состояние")
        self.assertContains(response, self.history.get_state_display())
        self.assertContains(response, "Заметка")
        self.assertContains(response, "Current note<br>Second line")

    def test_detail_marks_error_tool_results(self):
        self.trajectory.messages.append({
            "role": "tool",
            "tool_call_id": "call_2",
            "content": '{"status":"error","error":"Bad response"}',
        })
        self.trajectory.save(update_fields=["messages"])

        response = self.client.get(
            f"/curation/trajectories/{self.trajectory.pk}/"
        )

        self.assertContains(response, "curation-message--error")
        self.assertContains(response, "Bad response")


class EditDiffViewTest(TestCase):
    def setUp(self):
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())
        self.user = get_user_model().objects.create(
            username="admin", email="admin@example.com", is_superuser=True
        )
        self.client.force_login(self.user)
        self.now = timezone.now()

    def _edit(self, *, auto_updates=GameCuration.AutoUpdate.PROPOSE):
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Old Title",
            creation_time=self.now,
            added_by=self.user,
        )
        rev = GameRevision.objects.create(
            game=game,
            created_at=self.now,
            published_at=self.now,
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.MANUAL_EDIT,
            canonical_text=GameInfo(name="Old Title").to_canonical(),
        )
        game.published_revision = rev
        game.save(update_fields=["published_revision"])
        history = GameCuration.objects.create(
            game=game,
            state=GameCuration.State.NEEDS_ATTENTION,
            auto_updates=auto_updates,
        )
        edit = GameRevision.objects.create(
            game=history.game,
            created_at=self.now,
            created_by=self.user,
            status=GameRevision.Status.PROPOSED,
            origin=GameRevision.Origin.AUTO_IMPORT,
            canonical_text=GameInfo(name="New Title").to_canonical(),
        )
        return edit

    def test_proposed_edit_shows_actions_and_auto_accept_checkbox(self):
        edit = self._edit(auto_updates=GameCuration.AutoUpdate.ACCEPT)

        response = self.client.get(f"/curation/edits/{edit.pk}/")

        self.assertContains(response, "Принять")
        self.assertContains(response, "Отклонить")
        self.assertContains(response, "В дальнейшем автоматически принимать")
        self.assertContains(response, 'name="auto_accept" checked')
        self.assertContains(response, 'name="next"')
        self.assertContains(response, "к списку игр")
        self.assertContains(response, "к редактированию игры")
        self.assertContains(response, "к игре")
        self.assertContains(response, "к админке игры")
        self.assertContains(response, "остаться тут")

    def test_edit_page_shows_game_users_passes_and_llm_links(self):
        edit = self._edit()
        history = edit.game.curation
        history.state = GameCuration.State.NEEDS_ATTENTION
        history.note = "Current note\nSecond line"
        history.save(update_fields=["state", "note"])
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
            game=edit.game,
            edit=edit,
            workflow=workflow,
            model=model,
            created_at=self.now + timezone.timedelta(minutes=1),
            messages=[],
            cost="0.000000",
        )

        response = self.client.get(f"/curation/edits/{edit.pk}/")
        content = unescape(response.content.decode())

        self.assertContains(response, f'href="/game/{edit.game_id}/"')
        self.assertContains(response, "Old Title")
        self.assertContains(response, "Предложил")
        self.assertContains(response, self.user.username)
        self.assertContains(response, "Состояние")
        self.assertContains(response, history.get_state_display())
        self.assertContains(response, "Заметка")
        self.assertContains(response, "Current note<br>Second line")
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
        edit.status = GameRevision.Status.ACCEPTED
        edit.published_at = self.now + timezone.timedelta(minutes=5)
        edit.published_by = self.user
        edit.save(update_fields=["status", "published_at", "published_by"])

        response = self.client.get(f"/curation/edits/{edit.pk}/")

        self.assertContains(response, "Одобрил")
        self.assertContains(
            response,
            f"{self.user.username} ({edit.published_at:%d.%m.%Y %H:%M})",
        )

    def test_edit_redirect_dropdown_hides_game_options_for_draft_game(self):
        edit = self._edit()
        edit.game.state = Game.State.DRAFT
        edit.game.save(update_fields=["state"])

        response = self.client.get(f"/curation/edits/{edit.pk}/")

        self.assertContains(response, 'name="next"')
        self.assertContains(response, "к списку игр")
        self.assertNotContains(response, "к редактированию игры")
        self.assertNotContains(response, "к игре")
        self.assertContains(response, "к админке игры")
        self.assertContains(response, "остаться тут")

    def test_non_proposed_edit_hides_actions(self):
        edit = self._edit()
        edit.status = GameRevision.Status.REJECTED
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
        history = edit.game.curation
        history.refresh_from_db()
        edit.game.refresh_from_db()
        self.assertEqual(edit.status, GameRevision.Status.REJECTED)
        self.assertEqual(edit.published_by, self.user)
        self.assertIn("Old Title", edit.previous_canonical_text)
        self.assertEqual(history.state, GameCuration.State.SETTLED)
        self.assertEqual(edit.game.title, "Old Title")

    def test_accept_applies_and_settles(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/", {"action": "accept"}
        )

        self.assertRedirects(response, "/curation/")
        edit.refresh_from_db()
        history = edit.game.curation
        history.refresh_from_db()
        edit.game.refresh_from_db()
        self.assertEqual(edit.status, GameRevision.Status.ACCEPTED)
        self.assertEqual(edit.published_by, self.user)
        self.assertIn("Old Title", edit.previous_canonical_text)
        self.assertEqual(history.state, GameCuration.State.SETTLED)
        self.assertEqual(edit.game.title, "New Title")

    def test_accept_preserves_proposed_description_for_bare_url_id(self):
        edit = self._edit()
        category = GameURLCategory.objects.get(symbolic_id="video")
        url = URL.objects.create(
            original_url="https://vkvideo.ru/video-1_2",
            creation_date=self.now,
        )
        info = GameInfo(
            name="New Title",
            urls=[
                GameUrl(category.symbolic_id, url.id, "Proposed video", None)
            ],
        )
        edit.canonical_text = info.to_canonical()
        edit.save(update_fields=["canonical_text"])

        self.client.post(f"/curation/edits/{edit.pk}/", {"action": "accept"})

        game_url = GameURL.objects.get(game=edit.game, url=url)
        self.assertEqual(game_url.description, "Proposed video")

    def test_accept_keeps_current_description_for_existing_game_url(self):
        edit = self._edit()
        category = GameURLCategory.objects.get(symbolic_id="video")
        url = URL.objects.create(
            original_url="https://vkvideo.ru/video-1_2",
            creation_date=self.now,
        )
        GameURL.objects.create(
            game=edit.game,
            category=category,
            url=url,
            description="Current video",
        )
        info = GameInfo(
            name="New Title",
            urls=[
                GameUrl(category.symbolic_id, url.id, "Current video", None)
            ],
        )
        edit.canonical_text = info.to_canonical()
        edit.save(update_fields=["canonical_text"])

        self.client.post(f"/curation/edits/{edit.pk}/", {"action": "accept"})

        game_url = GameURL.objects.get(game=edit.game, url=url)
        self.assertEqual(game_url.description, "Current video")

    def test_accept_redirects_to_game_edit_when_requested(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "accept", "next": "edit_game"},
        )

        self.assertRedirects(
            response,
            f"/game/edit/{edit.game_id}/",
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
            f"/game/{edit.game_id}/",
            fetch_redirect_response=False,
        )

    def test_accept_redirects_to_history_when_requested(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "accept", "next": "history"},
        )

        self.assertRedirects(response, f"/curation/{edit.game.pk}/")

    def test_accept_redirects_to_edit_when_stay_requested(self):
        edit = self._edit()

        response = self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "accept", "next": "stay"},
        )

        self.assertRedirects(response, f"/curation/edits/{edit.pk}/")

    def test_game_redirect_falls_back_to_list_for_draft_game(self):
        edit = self._edit()
        edit.game.state = Game.State.DRAFT
        edit.game.save(update_fields=["state"])

        response = self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "reject", "next": "game"},
        )

        self.assertRedirects(response, "/curation/")

    def test_accept_updates_auto_accept_with_audit(self):
        edit = self._edit(auto_updates=GameCuration.AutoUpdate.PROPOSE)

        self.client.post(
            f"/curation/edits/{edit.pk}/",
            {"action": "accept", "auto_accept": "on"},
        )

        history = edit.game.curation
        history.refresh_from_db()
        self.assertEqual(history.auto_updates, GameCuration.AutoUpdate.ACCEPT)
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=edit.game,
                actor=self.user,
                field=GameHistoryAuditLog.AuditField.AUTO_UPDATES,
                old_text=GameCuration.AutoUpdate.PROPOSE,
                new_text=GameCuration.AutoUpdate.ACCEPT,
            ).exists()
        )

    def test_accept_clears_note_with_audit(self):
        edit = self._edit()
        history = edit.game.curation
        history.note = "Needs manual review"
        history.save(update_fields=["note"])

        self.client.post(f"/curation/edits/{edit.pk}/", {"action": "accept"})

        history.refresh_from_db()
        self.assertIsNone(history.note)
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                game=edit.game,
                actor=self.user,
                field=GameHistoryAuditLog.AuditField.NOTE,
                old_text="Needs manual review",
                new_text=None,
            ).exists()
        )

    def test_auto_accept_hidden_for_reject_policy(self):
        edit = self._edit(auto_updates=GameCuration.AutoUpdate.REJECT)

        response = self.client.get(f"/curation/edits/{edit.pk}/")

        self.assertContains(response, "Принять")
        self.assertNotContains(
            response, "В дальнейшем автоматически принимать"
        )

    def test_history_page_resolve_button_only_for_proposed_edits(self):
        proposed = self._edit()
        rejected = GameRevision.objects.create(
            game=proposed.game,
            created_at=self.now + timezone.timedelta(minutes=5),
            created_by=self.user,
            published_by=self.user,
            status=GameRevision.Status.REJECTED,
            origin=GameRevision.Origin.AUTO_IMPORT,
            canonical_text=GameInfo(name="Rejected Title").to_canonical(),
        )

        response = self.client.get(f"/curation/{proposed.game.pk}/")

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
        self.assertContains(response, f"Предложил: {self.user.username}")
        self.assertContains(response, f"Отклонил: {self.user.username}")
        self.assertNotContains(
            response,
            '<a class="curation-action-link" '
            f'href="/curation/edits/{rejected.pk}/">посмотреть правку и '
            "решить, что с ней делать</a>",
            html=True,
        )

    def test_history_page_sorts_settled_edits_by_approval_date(self):
        proposed = self._edit()
        proposed.created_at = self.now + timezone.timedelta(minutes=10)
        proposed.save(update_fields=["created_at"])
        approved = GameRevision.objects.create(
            game=proposed.game,
            created_at=self.now - timezone.timedelta(days=1),
            created_by=self.user,
            published_at=self.now + timezone.timedelta(minutes=20),
            published_by=self.user,
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.AUTO_IMPORT,
            canonical_text=GameInfo(name="Approved Title").to_canonical(),
        )

        response = self.client.get(f"/curation/{proposed.game.pk}/")
        content = response.content.decode()

        self.assertContains(
            response,
            "Предложил: "
            f"{self.user.username} ({proposed.created_at:%d.%m.%Y %H:%M})",
        )
        self.assertContains(
            response,
            "Одобрил: "
            f"{self.user.username} ({approved.published_at:%d.%m.%Y %H:%M})",
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
            game=edit.game,
            edit=edit,
            workflow=workflow,
            model=model,
            created_at=self.now + timezone.timedelta(minutes=1),
            messages=[],
            cost="0.000000",
        )

        response = self.client.get(f"/curation/{edit.game.pk}/")
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
            game=edit.game,
            workflow=workflow,
            model=model,
            created_at=self.now + timezone.timedelta(minutes=1),
            messages=[],
            cost="0.000000",
        )

        response = self.client.get(f"/curation/{edit.game.pk}/")

        self.assertContains(response, "Сиротская траектория LLM")
        self.assertContains(
            response, "У этой траектории нет ссылки на GameRevision."
        )
        self.assertContains(response, "orphan_workflow")
        self.assertContains(
            response, f'href="/curation/trajectories/{trajectory.pk}/"'
        )


class DiscoveryViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="admin", email="admin@example.com", is_superuser=True
        )
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
            state=Game.State.PUBLISHED,
            title="Linked Game",
            creation_time=ts,
            added_by=self.user,
        )
        game_history = GameCuration.objects.create(game=game)
        draft_game = Game.objects.create(
            state=Game.State.DRAFT,
            title="Draft Game",
            creation_time=ts,
            added_by=self.user,
        )
        empty_history = GameCuration.objects.create(
            game=draft_game,
        )
        sources[2].game = draft_game
        sources[2].save(update_fields=["game"])
        sources[3].game = game
        sources[3].save(update_fields=["game"])
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
            f'href="/curation/{game_history.pk}/">админка</a>',
        )
        self.assertContains(detail_response, "Draft Game (Draft)")
        self.assertContains(
            detail_response,
            f'href="/curation/{empty_history.pk}/">админка</a>',
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
            username="admin", email="admin@example.com", is_superuser=True
        )
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
        g1 = Game.objects.create(title="G1", creation_time=ts)
        GameCuration.objects.create(
            game=g1,
            state=GameCuration.State.SCHEDULED_FOR_UPDATE,
        )
        g2 = Game.objects.create(title="G2", creation_time=ts)
        GameCuration.objects.create(
            game=g2,
            state=GameCuration.State.NEEDS_ATTENTION,
        )

        response = self.client.get("/curation/tasks/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Периодические задания")
        self.assertContains(response, "Обработать новые источники (1/2)")
        self.assertContains(response, "(все сайты)")
        self.assertContains(response, "автоимпорт нового")
        self.assertContains(response, "выкачивать источники")
        self.assertContains(response, "выкачивать всякие там форумы")
        self.assertContains(response, "автоматическая обработка очереди (1)")
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
            "/curation/tasks/",
            {"action": "run_fetch_feeds", "run_limit": "9"},
        )

        self.assertRedirects(response, "/curation/tasks/")
        delay.assert_called_once_with(limit=9)

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
                "periodic_limit": "7",
                "every": "2",
                "period": IntervalSchedule.HOURS,
            },
        )

        self.assertRedirects(response, "/curation/tasks/")
        task = PeriodicTask.objects.get(name="Fetch feeds")
        self.assertFalse(task.enabled)
        self.assertEqual(task.task, "core.tasks.fetch_feeds")
        self.assertEqual(loads(task.kwargs), {"limit": 7})
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
            username="admin", email="admin@example.com", is_superuser=True
        )
        self.client.force_login(self.user)

    def _history(self, title="Game", **kwargs):
        if "game" not in kwargs:
            kwargs["game"] = Game.objects.create(
                state=Game.State.DRAFT,
                title=title,
                creation_time=timezone.now(),
            )
        kwargs.pop("creation_time", None)
        return GameCuration.objects.create(**kwargs)

    def _url_category(self, symbolic_id):
        return GameURLCategory.objects.get_or_create(
            symbolic_id=symbolic_id,
            defaults={"title": symbolic_id},
        )[0]

    def _download_link(
        self,
        game,
        original_url,
        *,
        original_filename=None,
        local_filename=None,
        local_url=None,
        is_uploaded=False,
        category=None,
    ):
        url = URL.objects.create(
            original_url=original_url,
            original_filename=original_filename,
            local_filename=local_filename,
            local_url=local_url,
            is_uploaded=is_uploaded,
            creation_date=timezone.now(),
        )
        return GameURL.objects.create(
            game=game,
            url=url,
            category=category or self._url_category("download_direct"),
        )

    def _fake_blueprint(self, slug, name, accepted, paths, spec_calls):
        blueprint = ModuleType(f"play.blueprints.{slug}")

        def get_spec() -> BlueprintSpec:
            spec_calls.append(slug)
            return BlueprintSpec(name=name, versions=[])

        def accepts(filename: Path) -> bool:
            paths.append(filename)
            return accepted

        def generate(_spec: GenerateSpec) -> None:
            pass

        setattr(blueprint, "get_spec", get_spec)
        setattr(blueprint, "accepts", accepts)
        setattr(blueprint, "generate", generate)
        return BlueprintInfo(slug, cast(BlueprintModule, blueprint))

    def test_history_playable_card_requires_direct_download(self):
        ts = timezone.now()
        game_without_links = Game.objects.create(
            state=Game.State.PUBLISHED, title="No downloads", creation_time=ts
        )
        no_downloads = GameCuration.objects.create(game=game_without_links)
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Other link", creation_time=ts
        )
        other_category = self._url_category("play_online")
        self._download_link(
            game,
            "https://example.com/play",
            category=other_category,
        )
        other_links = GameCuration.objects.create(game=game)

        for history in [no_downloads, other_links]:
            response = self.client.get(f"/curation/{history.pk}/")

            self.assertEqual(response.context["playable_files"], [])
            self.assertNotContains(
                response,
                '<div class="card--header">Проигрыватель</div>',
                html=True,
            )

    @patch("curation.views.discover_blueprints")
    def test_history_playable_card_lists_direct_downloads_in_order(
        self, discover_mock
    ):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Downloads", creation_time=ts
        )
        history = GameCuration.objects.create(game=game)
        source = GameSource.objects.create(
            game=game,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.com/source",
            created_at=ts,
        )
        first = self._download_link(
            game,
            "https://example.com/first.zip",
            original_filename="first.zip",
        )
        self._download_link(
            game,
            "https://example.com/online",
            category=self._url_category("play_online"),
        )
        second = self._download_link(
            game,
            "https://example.com/second.zip",
        )

        response = self.client.get(f"/curation/{history.pk}/")
        rows = response.context["playable_files"]
        content = response.content.decode()

        self.assertEqual(
            [row.game_url.pk for row in rows], [first.pk, second.pk]
        )
        self.assertTrue(all(row.compatibility is None for row in rows))
        self.assertContains(response, "Проигрыватель")
        self.assertContains(
            response,
            '<table class="curation-table curation-table--compact '
            'curation-playable-table">',
        )
        self.assertContains(response, ">Файл</th>")
        self.assertContains(response, ">Локальная копия</th>")
        self.assertContains(response, ">Совместимость</th>")
        self.assertContains(response, "first.zip")
        self.assertContains(response, "https://example.com/second.zip")
        self.assertContains(response, "Проверить совместимость")
        self.assertContains(response, "Нет", count=2)
        self.assertNotContains(response, "https://example.com/online")
        self.assertNotContains(response, "data-blueprint-slug")
        self.assertLess(
            content.index('<div class="card--header">Источники</div>'),
            content.index('<div class="card--header">Проигрыватель</div>'),
        )
        self.assertLess(
            content.index('<div class="card--header">Проигрыватель</div>'),
            content.index("Добавлен источник"),
        )
        discover_mock.assert_not_called()
        self.assertTrue(GameSource.objects.filter(pk=source.pk).exists())

    @patch.object(FileSystemStorage, "exists")
    @patch("curation.views.discover_blueprints")
    def test_history_playable_local_copy_uses_database_marker(
        self, discover_mock, exists_mock
    ):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Local files", creation_time=ts
        )
        history = GameCuration.objects.create(game=game)
        backup = self._download_link(
            game,
            "https://example.com/backup.zip",
            local_filename="backup.zip",
        )
        upload = self._download_link(
            game,
            "https://example.com/upload.zip",
            local_filename="upload.zip",
            is_uploaded=True,
        )
        remote = self._download_link(
            game,
            "https://example.com/remote.zip",
            local_url="/f/backups/remote.zip",
        )

        response = self.client.get(f"/curation/{history.pk}/")
        rows = response.context["playable_files"]

        self.assertEqual(
            [row.game_url.pk for row in rows],
            [backup.pk, upload.pk, remote.pk],
        )
        self.assertEqual(
            [row.has_local_copy for row in rows], [True, True, False]
        )
        self.assertContains(response, "Есть", count=2)
        self.assertContains(response, "Нет")
        discover_mock.assert_not_called()
        exists_mock.assert_not_called()

    @patch("curation.views.discover_blueprints")
    def test_history_playable_compatibility_checks_all_local_files(
        self, discover_mock
    ):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Compatibility", creation_time=ts
        )
        history = GameCuration.objects.create(game=game)
        with (
            TemporaryDirectory() as upload_root,
            TemporaryDirectory() as backup_root,
        ):
            self._download_link(
                game,
                "https://example.com/backup.zip",
                local_filename="games/backup.zip",
            )
            self._download_link(
                game,
                "https://example.com/remote.zip",
                local_url="/f/backups/remote.zip",
            )
            self._download_link(
                game,
                "https://example.com/upload.zip",
                local_filename="games/upload.zip",
                is_uploaded=True,
            )
            accepting_paths = []
            rejecting_paths = []
            spec_calls = []
            discover_mock.return_value = [
                self._fake_blueprint(
                    "accepting",
                    "Accepting playable",
                    True,
                    accepting_paths,
                    spec_calls,
                ),
                self._fake_blueprint(
                    "rejecting",
                    "Rejecting playable",
                    False,
                    rejecting_paths,
                    spec_calls,
                ),
            ]
            for file_path in [
                Path(backup_root) / "games/backup.zip",
                Path(upload_root) / "games/upload.zip",
            ]:
                file_path.parent.mkdir(parents=True)
                file_path.touch()

            with override_settings(
                UPLOADS_FS=FileSystemStorage(upload_root),
                BACKUPS_FS=FileSystemStorage(backup_root),
            ):
                response = self.client.get(
                    f"/curation/{history.pk}/",
                    {"check_compatibility": "1"},
                )

            expected_paths = [
                Path(backup_root) / "games/backup.zip",
                Path(upload_root) / "games/upload.zip",
            ]

        self.assertEqual(accepting_paths, expected_paths)
        self.assertEqual(rejecting_paths, expected_paths)
        self.assertEqual(spec_calls, ["accepting", "rejecting"])
        discover_mock.assert_called_once_with()
        self.assertContains(
            response,
            'data-blueprint-slug="accepting"',
            count=2,
        )
        self.assertContains(
            response,
            "curation-playable-result--accepted",
            count=2,
        )
        self.assertContains(response, "✓", count=2)
        self.assertContains(
            response,
            'data-blueprint-slug="rejecting"',
            count=2,
        )
        self.assertContains(
            response,
            "curation-playable-result--rejected",
            count=2,
        )
        self.assertContains(response, "✕", count=2)
        self.assertNotContains(
            response, '<input type="checkbox" data-blueprint-slug'
        )
        self.assertContains(response, ">Accepting playable</span>", count=2)
        self.assertContains(response, ">Rejecting playable</span>", count=2)
        self.assertIsNone(response.context["playable_files"][1].compatibility)
        self.assertContains(response, "Нет")

    @patch("curation.views.discover_blueprints")
    def test_history_playable_missing_file_is_reported(self, discover_mock):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Missing file", creation_time=ts
        )
        history = GameCuration.objects.create(game=game)
        self._download_link(
            game,
            "https://example.com/missing.zip",
            local_filename="missing.zip",
        )
        accepting_paths = []
        spec_calls = []
        discover_mock.return_value = [
            self._fake_blueprint(
                "accepting",
                "Accepting playable",
                True,
                accepting_paths,
                spec_calls,
            )
        ]

        with TemporaryDirectory() as backup_root:
            with override_settings(
                BACKUPS_FS=FileSystemStorage(backup_root),
            ):
                response = self.client.get(
                    f"/curation/{history.pk}/",
                    {"check_compatibility": "1"},
                )

        row = response.context["playable_files"][0]
        self.assertEqual(response.status_code, 200)
        self.assertTrue(row.file_missing)
        self.assertIsNone(row.compatibility)
        self.assertEqual(accepting_paths, [])
        self.assertEqual(spec_calls, ["accepting"])
        discover_mock.assert_called_once_with()
        self.assertContains(response, "Файл не найден.")
        self.assertNotContains(response, "data-blueprint-slug")

    @patch.object(FileSystemStorage, "exists", return_value=True)
    @patch("curation.views.discover_blueprints")
    def test_history_playable_compatibility_requires_exact_query_value(
        self, discover_mock, exists_mock
    ):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Compatibility", creation_time=ts
        )
        history = GameCuration.objects.create(game=game)
        self._download_link(
            game,
            "https://example.com/game.zip",
            local_filename="game.zip",
        )
        path = f"/curation/{history.pk}/"

        for query in [
            {},
            {"check_compatibility": ""},
            {"check_compatibility": "0"},
        ]:
            response = self.client.get(path, query)
            self.assertIsNone(
                response.context["playable_files"][0].compatibility
            )
            self.assertNotContains(response, "data-blueprint-slug")
        discover_mock.assert_not_called()

        discover_mock.return_value = []
        response = self.client.get(path, {"check_compatibility": "1"})

        discover_mock.assert_called_once_with()
        exists_mock.assert_called_once_with("game.zip")
        self.assertEqual(
            response.context["playable_files"][0].compatibility, ()
        )
        self.assertContains(response, "Проигрывателей нет.")

    def test_source_list_detail_and_fetch_content(self):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Source Game",
            creation_time=ts,
            added_by=self.user,
        )
        history = GameCuration.objects.create(game=game)
        source = GameSource.objects.create(
            game=game,
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
            f'(<a href="/curation/{history.pk}/">админка</a>)',
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

    def test_source_detail_toggles_keep_orphan(self):
        source = GameSource.objects.create(
            url="https://example.com/source",
            type=GameSource.SourceType.IFWIKI,
        )

        detail_response = self.client.get(f"/curation/sources/{source.pk}/")
        self.assertContains(detail_response, "оставить сиротой")

        response = self.client.post(
            f"/curation/sources/{source.pk}/", {"keep_orphan": "on"}
        )
        self.assertRedirects(response, f"/curation/sources/{source.pk}/")
        source.refresh_from_db()
        self.assertTrue(source.keep_orphan)

        self.client.post(f"/curation/sources/{source.pk}/", {})
        source.refresh_from_db()
        self.assertFalse(source.keep_orphan)

    def test_source_list_search_filter_and_pagination(self):
        ts = timezone.now()
        wanted_game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Wanted Game",
            creation_time=ts,
            added_by=self.user,
        )
        GameCuration.objects.create(game=wanted_game)
        wanted = GameSource.objects.create(
            game=wanted_game,
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
        self.assertContains(
            page_response,
            "?q=&type=&state=&attached=&sort=last_attempt&page=2",
        )

    def test_source_list_orphan_filter_and_sorting(self):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Attached Game",
            creation_time=ts,
            added_by=self.user,
        )
        GameCuration.objects.create(game=game)
        older = GameSource.objects.create(
            game=game,
            url="https://example.com/older",
            type=GameSource.SourceType.APERO,
            created_at=ts - timedelta(days=3),
            last_attempt=ts - timedelta(days=1),
        )
        orphan = GameSource.objects.create(
            url="https://example.com/orphan",
            type=GameSource.SourceType.IFWIKI,
            created_at=ts - timedelta(days=2),
            last_attempt=ts,
        )
        newest_fetch = GameSource.objects.create(
            url="https://example.com/fetched",
            type=GameSource.SourceType.QSP,
            created_at=ts - timedelta(days=1),
            last_attempt=ts - timedelta(days=2),
        )
        GameSourceFetch.objects.create(
            source=older,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash="old",
            first_fetch=ts - timedelta(days=3),
            last_fetch=ts - timedelta(days=3),
        )
        GameSourceFetch.objects.create(
            source=newest_fetch,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash="new",
            first_fetch=ts - timedelta(hours=1),
            last_fetch=ts - timedelta(hours=1),
        )

        response = self.client.get(
            "/curation/sources/", {"attached": "orphan"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="/curation/sources/{orphan.pk}/"')
        self.assertNotContains(
            response, f'href="/curation/sources/{older.pk}/"'
        )

        response = self.client.get("/curation/sources/")
        self.assertEqual(
            [source.pk for source in response.context["sources"]],
            [orphan.pk, older.pk, newest_fetch.pk],
        )

        response = self.client.get(
            "/curation/sources/", {"sort": "last_fetch"}
        )
        self.assertEqual(
            [source.pk for source in response.context["sources"]],
            [newest_fetch.pk, older.pk, orphan.pk],
        )

        response = self.client.get("/curation/sources/", {"sort": "created"})
        self.assertEqual(
            [source.pk for source in response.context["sources"]],
            [newest_fetch.pk, orphan.pk, older.pk],
        )

    def test_source_list_pending_orphans_and_last_new_fetch(self):
        ts = timezone.now()
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Attached Game",
            creation_time=ts,
            added_by=self.user,
        )
        GameCuration.objects.create(game=game)
        attached = GameSource.objects.create(
            game=game,
            url="https://example.com/attached",
            type=GameSource.SourceType.APERO,
            created_at=ts,
        )
        kept_orphan = GameSource.objects.create(
            url="https://example.com/kept-orphan",
            type=GameSource.SourceType.IFWIKI,
            created_at=ts,
            keep_orphan=True,
        )
        unchanged_refetch = GameSource.objects.create(
            url="https://example.com/unchanged-refetch",
            type=GameSource.SourceType.QSP,
            created_at=ts,
            last_attempt=ts,
        )
        older_new_fetch = GameSource.objects.create(
            url="https://example.com/older-new-fetch",
            type=GameSource.SourceType.QSP,
            created_at=ts,
            last_attempt=ts - timedelta(days=1),
        )
        newest_new_fetch = GameSource.objects.create(
            url="https://example.com/newest-new-fetch",
            type=GameSource.SourceType.QSP,
            created_at=ts,
            last_attempt=ts - timedelta(hours=1),
        )
        GameSourceFetch.objects.create(
            source=unchanged_refetch,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash="same",
            first_fetch=ts - timedelta(days=3),
            last_fetch=ts,
        )
        GameSourceFetch.objects.create(
            source=older_new_fetch,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash="old-new",
            first_fetch=ts - timedelta(days=1),
            last_fetch=ts - timedelta(days=1),
        )
        GameSourceFetch.objects.create(
            source=newest_new_fetch,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash="new-new",
            first_fetch=ts - timedelta(hours=1),
            last_fetch=ts - timedelta(hours=1),
        )

        response = self.client.get(
            "/curation/sources/", {"attached": "pending_orphan"}
        )
        self.assertContains(
            response, f'href="/curation/sources/{unchanged_refetch.pk}/"'
        )
        self.assertNotContains(
            response, f'href="/curation/sources/{attached.pk}/"'
        )
        self.assertNotContains(
            response, f'href="/curation/sources/{kept_orphan.pk}/"'
        )

        response = self.client.get(
            "/curation/sources/", {"sort": "last_new_fetch"}
        )
        self.assertEqual(
            [source.pk for source in response.context["sources"][:3]],
            [newest_new_fetch.pk, older_new_fetch.pk, unchanged_refetch.pk],
        )
        new_fetch_flags = {
            source.pk: source.latest_fetch_is_new
            for source in response.context["sources"]
        }
        self.assertFalse(new_fetch_flags[unchanged_refetch.pk])
        self.assertTrue(new_fetch_flags[newest_new_fetch.pk])
        self.assertContains(response, 'class="success"', count=2)

    def test_source_list_ok_state_filter(self):
        ts = timezone.now()
        ok_source = GameSource.objects.create(
            url="https://example.com/ok",
            type=GameSource.SourceType.APERO,
            created_at=ts,
        )
        failed_source = GameSource.objects.create(
            url="https://example.com/failed",
            type=GameSource.SourceType.APERO,
            created_at=ts,
            last_error="boom",
        )
        missing_source = GameSource.objects.create(
            url="https://example.com/missing",
            type=GameSource.SourceType.APERO,
            created_at=ts,
            missing_since=ts,
        )

        response = self.client.get("/curation/sources/", {"state": "ok"})

        self.assertContains(
            response, f'href="/curation/sources/{ok_source.pk}/"'
        )
        self.assertNotContains(
            response, f'href="/curation/sources/{failed_source.pk}/"'
        )
        self.assertNotContains(
            response, f'href="/curation/sources/{missing_source.pk}/"'
        )
        self.assertContains(response, '<option value="ok" selected>')

    def test_history_links_sources_to_detail(self):
        ts = timezone.now()
        history = self._history(creation_time=ts)
        pipeline, _ = EditPipeline.objects.update_or_create(
            name="Импорт", defaults={"passes": [{"name": "merge_sources"}]}
        )
        source = GameSource.objects.create(
            game=history.game,
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
        self.assertContains(
            response, f'data-dialog="source-detach-dialog-{source.pk}"'
        )
        self.assertContains(response, 'name="keep_orphan"')
        self.assertContains(response, "оставить сиротой")
        self.assertContains(response, "Автоматическая обработка")
        self.assertContains(response, pipeline.name)

    @patch("curation.views.edit_sources.delay")
    def test_history_run_edit_starts_task(self, delay):
        ts = timezone.now()
        history = self._history(creation_time=ts)
        pipeline, _ = EditPipeline.objects.update_or_create(
            name="Импорт", defaults={"passes": [{"name": "merge_sources"}]}
        )

        response = self.client.post(
            f"/curation/{history.pk}/run-edit/", {"pipeline": pipeline.pk}
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        delay.assert_called_once_with(
            game_id=history.pk, pipeline_id=pipeline.pk, force=True
        )

    def test_history_source_add_records_audit(self):
        ts = timezone.now()
        history = self._history(creation_time=ts)

        response = self.client.post(
            f"/curation/{history.pk}/sources/add/",
            {
                "type": GameSource.SourceType.IFWIKI,
                "url": " https://example.com/new ",
            },
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        source = GameSource.objects.get(game=history.game)
        self.assertEqual(source.type, GameSource.SourceType.IFWIKI)
        self.assertEqual(source.url, "https://example.com/new")
        audit = GameHistoryAuditLog.objects.get(game=history.game)
        self.assertEqual(
            audit.kind, GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED
        )
        self.assertEqual(audit.actor, self.user)
        self.assertEqual(audit.new_id, source.pk)
        self.assertIn("IFWiki", audit.new_text)

    def test_history_source_add_reuses_orphan_with_same_type_and_url(self):
        ts = timezone.now()
        history = self._history(creation_time=ts)
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
        self.assertEqual(orphan.game, history.game)
        self.assertEqual(GameSource.objects.count(), 1)
        self.assertEqual(GameHistoryAuditLog.objects.get().new_id, orphan.pk)

    def test_history_source_add_rejects_attached_duplicate_url(self):
        ts = timezone.now()
        history = self._history(title="H1", creation_time=ts)
        other = self._history(title="H2", creation_time=ts)
        GameSource.objects.create(
            game=other.game,
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
        history = self._history(creation_time=ts)
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
        self.assertEqual(orphan.game, history.game)
        self.assertEqual(GameHistoryAuditLog.objects.get().new_id, orphan.pk)

    def test_history_source_add_rejects_attached_source_by_id(self):
        ts = timezone.now()
        history = self._history(title="H1", creation_time=ts)
        other = self._history(title="H2", creation_time=ts)
        source = GameSource.objects.create(
            game=other.game,
            type=GameSource.SourceType.APERO,
            url="https://example.com/source",
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/add/",
            {"source_id": str(source.pk)},
        )

        self.assertEqual(response.status_code, 400)
        source.refresh_from_db()
        self.assertEqual(source.game, other.game)
        self.assertFalse(GameHistoryAuditLog.objects.exists())

    def test_history_source_add_rejects_unknown_type(self):
        history = self._history()

        response = self.client.post(
            f"/curation/{history.pk}/sources/add/",
            {"type": "NOPE", "url": "https://example.com/new"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(GameSource.objects.exists())
        self.assertFalse(GameHistoryAuditLog.objects.exists())

    def test_history_source_detach_keeps_source_and_records_audit(self):
        ts = timezone.now()
        history = self._history(creation_time=ts)
        source = GameSource.objects.create(
            game=history.game,
            type=GameSource.SourceType.APERO,
            url="https://example.com/source",
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/{source.pk}/delete/"
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        source.refresh_from_db()
        self.assertIsNone(source.game)
        self.assertFalse(source.keep_orphan)
        audit = GameHistoryAuditLog.objects.get(game=history.game)
        self.assertEqual(
            audit.kind, GameHistoryAuditLog.AuditKind.SOURCE_DETACHED
        )
        self.assertEqual(audit.actor, self.user)
        self.assertEqual(audit.old_id, source.pk)
        self.assertIn("Apero", audit.old_text)

    def test_history_source_detach_can_keep_source_orphan(self):
        ts = timezone.now()
        history = self._history(creation_time=ts)
        source = GameSource.objects.create(
            game=history.game,
            type=GameSource.SourceType.APERO,
            url="https://example.com/source",
        )

        response = self.client.post(
            f"/curation/{history.pk}/sources/{source.pk}/delete/",
            {"keep_orphan": "on"},
        )

        self.assertRedirects(response, f"/curation/{history.pk}/")
        source.refresh_from_db()
        self.assertIsNone(source.game)
        self.assertTrue(source.keep_orphan)

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
        history = self._history(creation_time=ts)
        first = GameSource.objects.create(
            game=history.game,
            type=GameSource.SourceType.APERO,
            url="https://example.com/one",
        )
        second = GameSource.objects.create(
            game=history.game,
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


class FeedViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="admin", email="admin@example.com", is_superuser=True
        )
        self.client.force_login(self.user)
        BlogFeed.objects.all().delete()
        FeedCache.objects.all().delete()

    def _feed(self, feed_id, **kwargs):
        defaults = {
            "title": feed_id.title(),
            "url": f"https://example.com/{feed_id}",
            "rss": f"https://example.com/{feed_id}.rss",
            "show_author": True,
        }
        defaults.update(kwargs)
        return BlogFeed.objects.create(feed_id=feed_id, **defaults)

    def test_feed_list_shows_health_and_cached_activity(self):
        ts = timezone.now()
        feed = self._feed(
            "ifhub",
            title="IF Hub",
            last_attempt=ts,
            last_success=ts - timedelta(hours=1),
        )
        self._feed(
            "vk-news",
            title="VK News",
            rss="https://vk.com/if_news",
            last_attempt=ts,
            failing_since=ts - timedelta(days=1),
            last_error="VK feeds need a service access token",
        )
        self._feed("disabled", title="Disabled Feed", is_enabled=False)
        FeedCache.objects.create(
            feed_id=feed.feed_id,
            item_id="old",
            date_published=ts - timedelta(days=2),
            date_discovered=ts - timedelta(days=2),
            title="Old post",
            authors="Alice",
            url="https://example.com/old",
        )
        FeedCache.objects.create(
            feed_id=feed.feed_id,
            item_id="new",
            date_published=ts - timedelta(hours=2),
            date_discovered=ts - timedelta(hours=1),
            title="Fresh post",
            authors="Alice",
            url="https://example.com/fresh",
        )

        response = self.client.get("/curation/feeds/")

        self.assertEqual(response.status_code, 200)
        for text in [
            'href="/curation/feeds/"',
            'href="/curation/feeds/ifhub/"',
            'data-href="/curation/feeds/ifhub/"',
            "curation-feed-table",
            "IF Hub",
            "https://example.com/ifhub.rss",
            ts.strftime("%Y-%m-%d %H:%M"),
            "Fresh post",
            "https://example.com/fresh",
            "VK feeds need a service access token",
            '<tr class="error"',
            '<tr class="warning"',
        ]:
            self.assertContains(response, text)
        cached_counts = {
            feed.feed_id: feed.cached_count
            for feed in response.context["feeds"]
        }
        self.assertEqual(cached_counts["ifhub"], 2)
        self.assertEqual(cached_counts["vk-news"], 0)

        detail_response = self.client.get("/curation/feeds/ifhub/")
        self.assertEqual(detail_response.status_code, 200)
        for text in [
            "IF Hub",
            "https://example.com/ifhub.rss",
            "Fresh post",
            "Old post",
            "https://example.com/fresh",
            "Alice",
            ts.strftime("%Y-%m-%d %H:%M"),
        ]:
            self.assertContains(detail_response, text)
        self.assertEqual(
            [post.item_id for post in detail_response.context["posts"]],
            ["new", "old"],
        )

    def test_feed_list_filters_sorts_and_paginates(self):
        ts = timezone.now()
        older = self._feed(
            "older", title="Older Feed", last_success=ts - timedelta(days=1)
        )
        newer = self._feed("newer", title="Newer Feed", last_success=ts)
        failed = self._feed(
            "failed",
            title="Failed Feed",
            failing_since=ts,
            last_error="boom",
        )
        for i in range(101):
            self._feed(f"page-{i:03d}", title=f"Page Feed {i:03d}")
        FeedCache.objects.create(
            feed_id=older.feed_id,
            item_id="older-post",
            date_published=ts - timedelta(days=2),
            date_discovered=ts - timedelta(days=2),
            title="Older cached post",
            authors="",
            url="https://example.com/older-post",
        )
        FeedCache.objects.create(
            feed_id=newer.feed_id,
            item_id="newer-post",
            date_published=ts - timedelta(hours=1),
            date_discovered=ts - timedelta(hours=1),
            title="Newer cached post",
            authors="",
            url="https://example.com/newer-post",
        )

        response = self.client.get(
            "/curation/feeds/", {"q": "failed", "state": "failed"}
        )
        self.assertContains(response, "Failed Feed")
        self.assertNotContains(response, "Older Feed")

        response = self.client.get(
            "/curation/feeds/", {"sort": "last_success"}
        )
        self.assertEqual(
            [feed.feed_id for feed in response.context["feeds"][:3]],
            [newer.feed_id, older.feed_id, failed.feed_id],
        )

        response = self.client.get("/curation/feeds/", {"sort": "latest_post"})
        self.assertEqual(
            [feed.feed_id for feed in response.context["feeds"][:2]],
            [newer.feed_id, older.feed_id],
        )

        page_response = self.client.get("/curation/feeds/")
        self.assertContains(page_response, "Страница 1 из 2")
        self.assertContains(
            page_response,
            "?q=&state=&sort=last_attempt&page=2",
        )

        for i in range(101):
            FeedCache.objects.create(
                feed_id=failed.feed_id,
                item_id=f"post-{i:03d}",
                date_published=ts - timedelta(minutes=i),
                date_discovered=ts - timedelta(minutes=i),
                title=f"Failed post {i:03d}",
                authors="",
                url=f"https://example.com/failed-{i:03d}",
            )
        detail_response = self.client.get("/curation/feeds/failed/")
        self.assertContains(detail_response, "Страница 1 из 2")
        self.assertContains(detail_response, "?page=2")


@override_settings(CURATION_EDIT_PASSES=["merge_sources"])
@override_settings(CURATION_EDIT_PASSES=["merge_sources"])
class EditRunnerTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.pipeline = EditPipeline.objects.create(
            name="Test", passes=[{"name": "merge_sources"}]
        )

    def _history(self, **kwargs):
        if "game" not in kwargs:
            kwargs["game"] = Game.objects.create(
                state=Game.State.DRAFT,
                title="Runner Game",
                creation_time=self.now,
            )
        kwargs.pop("creation_time", None)
        return GameCuration.objects.create(**kwargs)

    def _source(self, history, type, name, desc):
        source = GameSource.objects.create(
            game=history.game,
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
            game=history.game,
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
        history = self._history()
        wiki = self._source(
            history, GameSource.SourceType.IFWIKI, "Wiki Title", "Wiki desc"
        )
        apero = self._source(
            history, GameSource.SourceType.APERO, "Apero Title", "Apero desc"
        )

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.applied, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameCuration.State.SETTLED)
        self.assertIsNotNone(history.game)
        # IFWIKI (priority 100) wins the title over APERO (49).
        self.assertEqual(history.game.title, "Wiki Title")
        # Descriptions concatenate in priority order.
        self.assertEqual(
            history.game.description, "Wiki desc\n\n---\n\nApero desc"
        )

        edit = GameRevision.objects.get(game=history.game)
        self.assertEqual(edit.status, GameRevision.Status.ACCEPTED)
        self.assertEqual(edit.passes, [{"name": "merge_sources"}])
        self.assertEqual(set(edit.used_sources.all()), {wiki, apero})

    def test_rerun_is_idempotent(self):
        history = self._history()
        self._source(
            history, GameSource.SourceType.IFWIKI, "Wiki Title", "Wiki desc"
        )
        self._source(
            history, GameSource.SourceType.APERO, "Apero Title", "Apero desc"
        )
        run_edit(pipeline_id=self.pipeline.pk)

        history.refresh_from_db()
        GameCuration.objects.filter(pk=history.pk).update(
            state=GameCuration.State.SCHEDULED_FOR_UPDATE
        )
        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.unchanged, 1)
        self.assertEqual(
            GameRevision.objects.filter(game=history.game).count(), 1
        )
        history.refresh_from_db()
        # Description was not re-concatenated across runs.
        self.assertEqual(
            history.game.description, "Wiki desc\n\n---\n\nApero desc"
        )

    def test_merge_keeps_existing_related_data_and_scalar_fallbacks(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
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
        rev = GameRevision.objects.create(
            game=game,
            created_at=self.now,
            published_at=self.now,
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.BACKFILL,
            canonical_text=f"""---
- name: Old Title
- release_date: "2001-02-03"
- personalities:
    author:
      - {old_author.id}
- tags:
  - ["tag", {old_tag.id}]
- urls:
  - ["game", "old file", "{old_url.original_url}"]
- attributions:
  - {old_attr.id}
---
Old desc""",
        )
        game.published_revision = rev
        game.save(update_fields=["published_revision"])
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

    def test_merge_fills_empty_current_url_description_from_source(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Old Title",
            creation_time=self.now,
        )
        history = self._history(
            game=game, auto_updates=GameCuration.AutoUpdate.PROPOSE
        )
        category = GameURLCategory.objects.create(
            symbolic_id="download_landing", title="Download"
        )
        url = URL.objects.create(
            original_url="https://disk.yandex.ru/d/nWeL7Vv4CrhGdA",
            creation_date=self.now,
        )
        GameURL.objects.create(
            game=game, category=category, url=url, description=""
        )
        canonical = f"""---
- name: Old Title
- urls:
  - ["download_landing", "Скачать игру", "{url.original_url}"]
---
"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.proposed, 1)
        edit = GameRevision.objects.get(game=history.game)
        self.assertIn(
            f'["download_landing", "Скачать игру", {url.id}]',
            edit.canonical_text,
        )

    def test_merge_keeps_non_empty_current_url_description(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Old Title",
            creation_time=self.now,
        )
        history = self._history(
            game=game, auto_updates=GameCuration.AutoUpdate.PROPOSE
        )
        category = GameURLCategory.objects.create(
            symbolic_id="download_landing", title="Download"
        )
        url = URL.objects.create(
            original_url="https://disk.yandex.ru/d/nWeL7Vv4CrhGdA",
            creation_date=self.now,
        )
        GameURL.objects.create(
            game=game,
            category=category,
            url=url,
            description="Текущее описание",
        )
        rev = GameRevision.objects.create(
            game=game,
            created_at=self.now,
            published_at=self.now,
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.BACKFILL,
            canonical_text=f"""---
- name: Old Title
- urls:
  - ["download_landing", "Текущее описание", {url.id}]
---
""",
        )
        game.published_revision = rev
        game.save(update_fields=["published_revision"])
        canonical = f"""---
- name: Old Title
- urls:
  - ["download_landing", "Скачать игру", "{url.original_url}"]
---
"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.proposed, 1)
        edit = GameRevision.objects.get(
            game=history.game, status=GameRevision.Status.PROPOSED
        )
        self.assertIn(
            f'["download_landing", "Текущее описание", {url.id}]'
            f'  # "Скачать игру" "{url.original_url}"',
            edit.canonical_text,
        )

    def test_merge_keeps_served_description_when_source_empty(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Old Title",
            description="Old desc",
            creation_time=self.now,
        )
        rev = GameRevision.objects.create(
            game=game,
            created_at=self.now,
            published_at=self.now,
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.BACKFILL,
            canonical_text="""---
- name: Old Title
---
Old desc""",
        )
        game.published_revision = rev
        game.save(update_fields=["published_revision"])
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
        history = self._history()
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
        edit = GameRevision.objects.get(game=history.game)
        self.assertEqual(
            edit.passes, [{"name": "merge_sources"}, {"name": "cleanup_text"}]
        )

    def test_cleanup_text_removes_empty_sections(self):
        self._set_pipeline([
            {"name": "merge_sources"},
            {"name": "cleanup_text"},
        ])
        history = self._history()
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
        history = self._history()
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
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Tell", creation_time=self.now
        )
        history = self._history(game=game)
        play_online = GameURLCategory.objects.create(
            symbolic_id="play_online", title="Play online"
        )
        url = URL.objects.create(
            original_url=(
                "http://iplayif.com/?story="
                "http://rinform.stormway.ru/games/wtell/WTellR.z5"
            ),
            creation_date=self.now,
        )
        GameURL.objects.create(game=game, category=play_online, url=url)
        rev = GameRevision.objects.create(
            game=game,
            created_at=self.now,
            published_at=self.now,
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.BACKFILL,
            canonical_text=f"""---
- name: Tell
- urls:
  - ["play_online", {url.id}]
---
""",
        )
        game.published_revision = rev
        game.save(update_fields=["published_revision"])
        canonical = """---
- name: Tell
- urls:
  - ["play_online", "Играть онлайн", "http://iplayif.com/?story=http://rinform.org/games/wtell/WTellR.z5"]
---
"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.applied, 1)
        game_url = GameURL.objects.get(game=game, url=url)
        self.assertEqual(game_url.description, "Играть онлайн")

    def test_merge_deduplicates_existing_exact_url(self):
        game = Game.objects.create(
            state=Game.State.PUBLISHED, title="Tell", creation_time=self.now
        )
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
        rev = GameRevision.objects.create(
            game=game,
            created_at=self.now,
            published_at=self.now,
            status=GameRevision.Status.ACCEPTED,
            origin=GameRevision.Origin.BACKFILL,
            canonical_text=f"""---
- name: Tell
- urls:
  - ["game_page", {url.id}]
---
""",
        )
        game.published_revision = rev
        game.save(update_fields=["published_revision"])
        canonical = f"""---
- name: Tell
- urls:
  - ["game_page", "{url.original_url}"]
---
"""
        self._canonical_source(history, canonical)

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.unchanged, 1)
        self.assertEqual(
            GameRevision.objects.filter(game=history.game).count(), 1
        )

    def test_merge_can_drop_existing_data(self):
        self._set_pipeline([{"name": "merge_sources", "keep_existing": False}])
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
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
        history = self._history(auto_updates=GameCuration.AutoUpdate.PROPOSE)
        self._source(
            history, GameSource.SourceType.IFWIKI, "Wiki Title", "Wiki desc"
        )

        stats = run_edit(pipeline_id=self.pipeline.pk)

        self.assertEqual(stats.proposed, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameCuration.State.NEEDS_ATTENTION)
        self.assertIsNotNone(history.game)
        self.assertEqual(history.game.state, Game.State.DRAFT)
        edit = GameRevision.objects.get(game=history.game)
        self.assertEqual(edit.status, GameRevision.Status.PROPOSED)
        self.assertEqual(Game.objects.published().count(), 0)

    def test_proposed_edit_is_canonicalized_before_diff(self):
        history = self._history(auto_updates=GameCuration.AutoUpdate.PROPOSE)
        language_cat = GameTagCategory.objects.create(
            symbolic_id="language", name="Language"
        )
        language = GameTag.objects.create(
            category=language_cat, name="русский"
        )
        source = GameSource.objects.create(
            game=history.game,
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
        edit = GameRevision.objects.get(game=history.game)
        self.assertIn(f'["language", {language.id}]', edit.canonical_text)
        self.assertNotIn('["language", "русский"]', edit.canonical_text)

    @override_settings(CURATION_EDIT_PASSES=["merge_sources", "enrich"])
    def test_enrichment_replaces_canonicalized_tag_genres(self):
        self._set_pipeline(["merge_sources", "enrich"])
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())
        call_command("initenrichment", stdout=StringIO())
        history = self._history(auto_updates=GameCuration.AutoUpdate.PROPOSE)
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
        edit = GameRevision.objects.get(game=history.game)
        self.assertEqual(edit.canonical_text.count('"g_fairytale"'), 1)
        self.assertEqual(edit.canonical_text.count('"g_kids"'), 1)
        self.assertNotIn('["tag",', edit.canonical_text)

    def test_enrichment_deduplicates_existing_and_mapped_genre_slug(self):
        self._set_pipeline(["merge_sources", "enrich"])
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())
        call_command("initenrichment", stdout=StringIO())
        game = Game.objects.create(
            state=Game.State.PUBLISHED,
            title="Old Title",
            description="Old desc",
            creation_time=self.now,
        )
        fantasy = GameTag.objects.get(symbolic_id="g_fantasy")
        game.tags.add(fantasy)
        history = self._history(
            game=game, auto_updates=GameCuration.AutoUpdate.PROPOSE
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
        edit = GameRevision.objects.get(game=history.game)
        self.assertEqual(edit.canonical_text.count('"g_fantasy"'), 1)
