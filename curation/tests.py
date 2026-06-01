from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from games.models import (
    URL,
    Game,
    GameTag,
    GameTagCategory,
    GameURL,
    GameURLCategory,
)

from .edit import run_edit
from .gameinfo import GameInfo
from .models import (
    GameEdit,
    GameHistory,
    GameHistoryAuditLog,
    GameHistoryComment,
    GameSource,
    GameSourceFetch,
    SourceDiscoveryStatus,
)


class CurationSmokeTest(TestCase):
    def test_history_lifecycle(self):
        now = timezone.now()

        # History may exist before any Game row is created.
        history = GameHistory.objects.create(game=None, creation_time=now)
        self.assertIsNone(history.game)
        self.assertEqual(history.state, GameHistory.State.IN_PROGRESS)
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
            priority=1,
            state=GameHistory.State.SETTLED,
        )
        recent_progress = self._create_history(
            "Recent progress",
            ts + timezone.timedelta(days=1),
            priority=1,
            state=GameHistory.State.IN_PROGRESS,
        )
        urgent_low = self._create_history(
            "Urgent low",
            ts + timezone.timedelta(days=2),
            priority=20,
            state=GameHistory.State.NEEDS_ATTENTION,
        )
        urgent_high = self._create_history(
            "Urgent high",
            ts + timezone.timedelta(days=3),
            priority=5,
            state=GameHistory.State.NEEDS_ATTENTION,
        )

        response = self.client.get("/curation/")

        self.assertEqual(
            list(response.context["histories"]),
            [urgent_high, urgent_low, recent_progress, old_settled],
        )
        self.assertContains(response, '<option value="relevance" selected>')

    def test_history_list_priority_sort_groups_by_state_first(self):
        ts = timezone.now()
        progress = self._create_history(
            "Progress",
            ts + timezone.timedelta(days=1),
            priority=1,
            state=GameHistory.State.IN_PROGRESS,
        )
        settled = self._create_history(
            "Settled",
            ts + timezone.timedelta(days=2),
            priority=1,
            state=GameHistory.State.SETTLED,
        )
        urgent_low = self._create_history(
            "Urgent low",
            ts + timezone.timedelta(days=3),
            priority=20,
            state=GameHistory.State.NEEDS_ATTENTION,
        )
        urgent_high = self._create_history(
            "Urgent high",
            ts + timezone.timedelta(days=4),
            priority=5,
            state=GameHistory.State.NEEDS_ATTENTION,
        )

        response = self.client.get("/curation/?sort=priority")

        self.assertEqual(
            list(response.context["histories"]),
            [urgent_high, urgent_low, progress, settled],
        )

    def _create_history(self, title, updated, *, priority, state):
        game = Game.objects.create(
            title=title,
            creation_time=updated,
            added_by=self.user,
        )
        return GameHistory.objects.create(
            game=game,
            creation_time=updated,
            edit_time=updated,
            priority=priority,
            state=state,
        )


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

    def test_accept_applies_settles_redirects_and_audits(self):
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
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                history=history,
                actor=self.user,
                field=GameHistoryAuditLog.AuditField.CANONICAL_TEXT,
            ).exists()
        )

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
            status=GameEdit.EditStatus.REJECTED,
            origin=GameEdit.Origin.AUTO_IMPORT,
            canonical_text=GameInfo(name="Rejected Title").to_canonical(),
        )

        response = self.client.get(f"/curation/{proposed.history.pk}/")

        self.assertContains(
            response,
            '<a class="curation-action-link" '
            f'href="/curation/edits/{proposed.pk}/">Resolve</a>',
            html=True,
        )
        self.assertContains(
            response,
            f'<a href="/curation/edits/{rejected.pk}/">посмотреть</a>',
            html=True,
        )
        self.assertNotContains(
            response,
            '<a class="curation-action-link" '
            f'href="/curation/edits/{rejected.pk}/">Resolve</a>',
            html=True,
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
            f'/curation/sources/fetches/{fetch.pk}/raw/" target="_blank"',
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
            f'/curation/sources/fetches/{fetch.pk}/raw/" target="_blank"',
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
        # An unrecognized link is skipped, not turned into a source.
        self._link(bot_game, "https://youtube.com/watch?v=x", self.video)

        # Bot-added but human-edited ⇒ PROPOSE rather than ACCEPT.
        edited_game = self._game("Edited game", edit_time=self.now)
        self._link(edited_game, "http://ifwiki.ru/Другая", self.game_page)

        self._run()

        bot_history = GameHistory.objects.get(game=bot_game)
        self.assertEqual(
            bot_history.auto_updates, GameHistory.AutoUpdate.ACCEPT
        )
        self.assertEqual(bot_history.state, GameHistory.State.IN_PROGRESS)
        self.assertEqual(
            list(
                GameSource.objects.filter(history=bot_history).values_list(
                    "type", flat=True
                )
            ),
            [GameSource.SourceType.IFWIKI],
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

    def test_merge_applies_in_priority_order(self):
        history = self._history(game=None)
        wiki = self._source(
            history, GameSource.SourceType.IFWIKI, "Wiki Title", "Wiki desc"
        )
        apero = self._source(
            history, GameSource.SourceType.APERO, "Apero Title", "Apero desc"
        )

        stats = run_edit()

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
        self.assertEqual(edit.passes, ["merge_sources"])
        self.assertEqual(set(edit.used_sources.all()), {wiki, apero})

    def test_rerun_is_idempotent(self):
        history = self._history(game=None)
        self._source(
            history, GameSource.SourceType.IFWIKI, "Wiki Title", "Wiki desc"
        )
        self._source(
            history, GameSource.SourceType.APERO, "Apero Title", "Apero desc"
        )
        run_edit()

        history.refresh_from_db()
        GameHistory.objects.filter(pk=history.pk).update(
            state=GameHistory.State.IN_PROGRESS
        )
        stats = run_edit()

        self.assertEqual(stats.unchanged, 1)
        self.assertEqual(GameEdit.objects.filter(history=history).count(), 1)
        history.refresh_from_db()
        # Description was not re-concatenated across runs.
        self.assertEqual(
            history.game.description, "Wiki desc\n\n---\n\nApero desc"
        )

    def test_propose_policy_does_not_apply(self):
        history = self._history(
            game=None, auto_updates=GameHistory.AutoUpdate.PROPOSE
        )
        self._source(
            history, GameSource.SourceType.IFWIKI, "Wiki Title", "Wiki desc"
        )

        stats = run_edit()

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

        stats = run_edit()

        self.assertEqual(stats.proposed, 1)
        edit = GameEdit.objects.get(history=history)
        self.assertIn(f'["language", {language.id}]', edit.canonical_text)
        self.assertNotIn('["language", "русский"]', edit.canonical_text)
