from django.test import TestCase
from django.utils import timezone
from django.utils.timezone import now

from games.models import URL, Game, GameURL, GameURLCategory

from .gameinfo import GameInfo, GameUrl
from .models import (
    GameHistory,
    GameHistoryAuditLog,
    GameSource,
    GameSourceFetch,
)
from .providers import PROVIDER_BY_TYPE
from .reconcile import run_reconcile


def _provider_type():
    return next(iter(PROVIDER_BY_TYPE))


class RunReconcileTests(TestCase):
    def setUp(self):
        self.stype = _provider_type()

    # -- fixtures ---------------------------------------------------------

    def _category(self):
        cat, _ = GameURLCategory.objects.get_or_create(
            symbolic_id="game_page", defaults={"title": "Game page"}
        )
        return cat

    def _existing(self, title, url=None):
        game = Game.objects.create(title=title, creation_time=now())
        if url:
            GameURL.objects.create(
                game=game,
                url=URL.objects.create(original_url=url, creation_date=now()),
                category=self._category(),
            )
        return GameHistory.objects.create(
            game=game,
            state=GameHistory.State.SETTLED,
            creation_time=now(),
        )

    def _canon(self, name, urls=()):
        info = GameInfo(
            name=name, urls=[GameUrl(cat, None, None, u) for cat, u in urls]
        )
        return info.to_canonical()

    def _orphan(self, source_url, canonical):
        source = GameSource.objects.create(type=self.stype, url=source_url)
        ts = now()
        GameSourceFetch.objects.create(
            source=source,
            raw_content="",
            canonical_text=canonical,
            canonical_text_hash="",
            first_fetch=ts,
            last_fetch=ts,
        )
        return source

    def _source_fetch(self, source, canonical, ts):
        return GameSourceFetch.objects.create(
            source=source,
            raw_content="",
            canonical_text=canonical,
            canonical_text_hash="",
            first_fetch=ts,
            last_fetch=ts,
        )

    # -- tests ------------------------------------------------------------

    def test_attaches_on_shared_identity_url(self):
        history = self._existing(
            "Shared Game", url="http://ifwiki.ru/SharedGame"
        )
        source = self._orphan(
            "http://apero.ru/orphan-a",
            self._canon(
                "Shared Game", [("game_page", "http://ifwiki.ru/SharedGame")]
            ),
        )

        stats = run_reconcile()

        self.assertEqual(stats[0].attached, 1)
        source.refresh_from_db()
        self.assertEqual(source.history_id, history.pk)
        self.assertEqual(
            GameHistoryAuditLog.objects.filter(
                history=history,
                kind=GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED,
                new_id=source.pk,
            ).count(),
            1,
        )

    def test_attaches_on_high_title_similarity(self):
        history = self._existing(
            "Bright Banshee Castle", url="http://x.ru/page"
        )
        source = self._orphan(
            "http://apero.ru/orphan-b", self._canon("Bright Banshee Castle")
        )

        stats = run_reconcile()

        self.assertEqual(stats[0].attached, 1)
        source.refresh_from_db()
        self.assertEqual(source.history_id, history.pk)

    def test_spawns_when_title_below_floor_despite_shared_url(self):
        self._existing("Alpha", url="http://ifwiki.ru/Shared")
        source = self._orphan(
            "http://apero.ru/orphan-c",
            self._canon(
                "Zeta Omega Entirely Different",
                [("game_page", "http://ifwiki.ru/Shared")],
            ),
        )

        stats = run_reconcile()

        self.assertEqual(stats[0].spawned, 1)
        self.assertEqual(stats[0].attached, 0)
        source.refresh_from_db()
        self.assertIsNotNone(source.history_id)
        self.assertIsNone(source.history.game_id)
        self.assertEqual(
            GameHistoryAuditLog.objects.filter(
                history=source.history,
                kind=GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED,
                new_id=source.pk,
            ).count(),
            1,
        )

    def test_two_orphans_sharing_url_cluster_into_one_history(self):
        shared = ("game_page", "http://newsite.ru/g")
        a = self._orphan(
            "http://apero.ru/a", self._canon("Common Game", [shared])
        )
        b = self._orphan(
            "http://apero.ru/b", self._canon("Common Game", [shared])
        )

        stats = run_reconcile()

        self.assertEqual(stats[0].spawned, 1)
        self.assertEqual(stats[0].attached, 1)
        self.assertEqual(
            GameHistory.objects.filter(game__isnull=True).count(), 1
        )
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertIsNotNone(a.history_id)
        self.assertEqual(a.history_id, b.history_id)

    def test_ambiguous_match_attaches_best_and_flags_candidates(self):
        h1 = self._existing("Match This Title", url="http://ifwiki.ru/One")
        h2 = self._existing("Totally Other Name", url="http://ifwiki.ru/Two")
        source = self._orphan(
            "http://apero.ru/orphan-d",
            self._canon(
                "Match This Title",
                [
                    ("game_page", "http://ifwiki.ru/One"),
                    ("game_page", "http://ifwiki.ru/Two"),
                ],
            ),
        )

        stats = run_reconcile()

        self.assertEqual(stats[0].ambiguous, 1)
        self.assertEqual(stats[0].attached, 1)
        source.refresh_from_db()
        self.assertEqual(source.history_id, h1.pk)
        h1.refresh_from_db()
        h2.refresh_from_db()
        self.assertEqual(h1.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(
            h1.note,
            f"Источник #{source.pk} присоединён неоднозначно",
        )
        self.assertEqual(h2.state, GameHistory.State.NEEDS_ATTENTION)
        self.assertEqual(
            h2.note,
            f"Источник #{source.pk} похож на эту игру",
        )
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                history=h1,
                kind=GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED,
                new_id=source.pk,
            ).exists()
        )
        self.assertEqual(
            GameHistoryAuditLog.objects.filter(
                kind=GameHistoryAuditLog.AuditKind.FIELD_CHANGE,
                field=GameHistoryAuditLog.AuditField.STATE,
                old_text=GameHistory.State.SETTLED,
                new_text=GameHistory.State.NEEDS_ATTENTION,
            ).count(),
            2,
        )

    def test_ambiguous_match_appends_note(self):
        self._existing("Match This Title", url="http://ifwiki.ru/One")
        h2 = self._existing("Totally Other Name", url="http://ifwiki.ru/Two")
        h2.state = GameHistory.State.NEEDS_ATTENTION
        h2.note = "Старая причина"
        h2.save(update_fields=["state", "note"])
        source = self._orphan(
            "http://apero.ru/orphan-d",
            self._canon(
                "Match This Title",
                [
                    ("game_page", "http://ifwiki.ru/One"),
                    ("game_page", "http://ifwiki.ru/Two"),
                ],
            ),
        )

        run_reconcile()

        h2.refresh_from_db()
        self.assertEqual(
            h2.note,
            f"Старая причина\nИсточник #{source.pk} похож на эту игру",
        )
        self.assertFalse(
            GameHistoryAuditLog.objects.filter(
                history=h2,
                kind=GameHistoryAuditLog.AuditKind.FIELD_CHANGE,
                field=GameHistoryAuditLog.AuditField.STATE,
            ).exists()
        )
        self.assertTrue(
            GameHistoryAuditLog.objects.filter(
                history=h2,
                kind=GameHistoryAuditLog.AuditKind.FIELD_CHANGE,
                field=GameHistoryAuditLog.AuditField.NOTE,
                old_text="Старая причина",
                new_text=(
                    f"Старая причина\nИсточник #{source.pk} похож на эту игру"
                ),
            ).exists()
        )

    def test_orphan_without_fetch_is_skipped(self):
        source = GameSource.objects.create(
            type=self.stype, url="http://apero.ru/e"
        )

        stats = run_reconcile()

        self.assertEqual(stats[0].skipped_no_fetch, 1)
        self.assertEqual(stats[0].processed, 0)
        source.refresh_from_db()
        self.assertIsNone(source.history_id)
        self.assertFalse(
            GameHistoryAuditLog.objects.filter(
                kind=GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED,
                new_id=source.pk,
            ).exists()
        )

    def test_new_attached_fetch_marks_history_in_progress(self):
        edited_at = now()
        history = self._existing("Existing Game")
        history.edit_time = edited_at
        history.save(update_fields=["edit_time"])
        source = GameSource.objects.create(
            type=self.stype, url="http://apero.ru/attached", history=history
        )
        self._source_fetch(
            source,
            self._canon("Existing Game"),
            edited_at + timezone.timedelta(seconds=1),
        )

        stats = run_reconcile()

        self.assertEqual(stats[0].processed, 1)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SCHEDULED_FOR_UPDATE)

    def test_new_attached_fetch_ignores_abandoned_history(self):
        edited_at = now()
        history = self._existing("Existing Game")
        history.state = GameHistory.State.ABANDONED
        history.edit_time = edited_at
        history.save(update_fields=["state", "edit_time"])
        source = GameSource.objects.create(
            type=self.stype, url="http://apero.ru/attached", history=history
        )
        self._source_fetch(
            source,
            self._canon("Existing Game"),
            edited_at + timezone.timedelta(seconds=1),
        )

        stats = run_reconcile()

        self.assertEqual(stats[0].processed, 0)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.ABANDONED)

    def test_old_attached_fetch_keeps_history_settled(self):
        edited_at = now()
        history = self._existing("Existing Game")
        history.edit_time = edited_at
        history.save(update_fields=["edit_time"])
        source = GameSource.objects.create(
            type=self.stype, url="http://apero.ru/attached", history=history
        )
        self._source_fetch(
            source,
            self._canon("Existing Game"),
            edited_at - timezone.timedelta(seconds=1),
        )

        stats = run_reconcile()

        self.assertEqual(stats[0].processed, 0)
        history.refresh_from_db()
        self.assertEqual(history.state, GameHistory.State.SETTLED)
