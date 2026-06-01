from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from games.models import URL, Game, GameURL, GameURLCategory

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
        )

        response = self.client.get("/curation/")
        self.assertEqual(response.status_code, 200)
        for text in [
            "curation-history-table",
            '<tr class="warning"',
            'class="curation-truncate"',
            'title="Very Long Game Title That Should Be Truncated"',
            "внимание",
            "предл.",
        ]:
            self.assertContains(response, text)


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
        self.assertContains(
            response, f'href="/curation/sources/{source.pk}/">Apero</a>'
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
