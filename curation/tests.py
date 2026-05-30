from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from games.models import URL, Game, GameURL, GameURLCategory

from .models import (
    GameReconciliation,
    GameSource,
    GameSourceFetch,
    GameTicket,
    GameTicketAuditLog,
    GameTicketComment,
)


class CurationSmokeTest(TestCase):
    def test_ticket_lifecycle(self):
        now = timezone.now()

        # Ticket may exist before any Game row is created.
        ticket = GameTicket.objects.create(game=None, creation_time=now)
        self.assertIsNone(ticket.game)
        self.assertEqual(ticket.state, GameTicket.State.IN_PROGRESS)
        self.assertEqual(ticket.auto_updates, GameTicket.AutoUpdate.ACCEPT)

        source = GameSource.objects.create(
            ticket=ticket,
            url="https://example.com/game",
            type=GameSource.SourceType.IFWIKI,
        )
        fetch = GameSourceFetch.objects.create(
            source=source,
            raw_content="raw",
            filtered_content="filtered",
            filtered_content_hash="abc123",
            first_fetch=now,
            last_fetch=now,
        )

        recon = GameReconciliation.objects.create(
            ticket=ticket,
            proposed_at=now,
            status=GameReconciliation.ReconciliationStatus.PROPOSED,
            origin=GameReconciliation.Origin.AUTO_IMPORT,
            canonical_text="# Game\n---\ntitle: Game",
        )
        recon.used_sources.add(fetch)
        self.assertEqual(list(recon.used_sources.all()), [fetch])

        parent_comment = GameTicketComment.objects.create(
            ticket=ticket,
            type=GameTicketComment.CommentType.USER_FEEDBACK,
            text="Looks off.",
            creation_time=now,
        )
        reply = GameTicketComment.objects.create(
            ticket=ticket,
            reply_to=parent_comment,
            type=GameTicketComment.CommentType.MODS_COMMENT,
            text="Fixed.",
            creation_time=now,
        )
        self.assertEqual(reply.reply_to, parent_comment)

        GameTicketAuditLog.objects.create(
            ticket=ticket,
            created_at=now,
            kind="",
            new_id=recon.pk,
        )
        self.assertEqual(ticket.gameticketauditlog_set.count(), 1)


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

    def test_seeds_tickets_sources_and_audit(self):
        bot_game = self._game("Bot game")
        self._link(bot_game, "http://ifwiki.ru/Игра", self.game_page)
        # An unrecognized link is skipped, not turned into a source.
        self._link(bot_game, "https://youtube.com/watch?v=x", self.video)

        # Bot-added but human-edited ⇒ PROPOSE rather than ACCEPT.
        edited_game = self._game("Edited game", edit_time=self.now)
        self._link(edited_game, "http://ifwiki.ru/Другая", self.game_page)

        self._run()

        bot_ticket = GameTicket.objects.get(game=bot_game)
        self.assertEqual(bot_ticket.auto_updates, GameTicket.AutoUpdate.ACCEPT)
        self.assertEqual(bot_ticket.state, GameTicket.State.IN_PROGRESS)
        self.assertEqual(
            list(
                GameSource.objects.filter(ticket=bot_ticket).values_list(
                    "type", flat=True
                )
            ),
            [GameSource.SourceType.IFWIKI],
        )
        self.assertEqual(
            GameTicketAuditLog.objects.filter(
                ticket=bot_ticket,
                kind=GameTicketAuditLog.AuditKind.INITIAL_IMPORT,
            ).count(),
            1,
        )

        edited_ticket = GameTicket.objects.get(game=edited_game)
        self.assertEqual(
            edited_ticket.auto_updates, GameTicket.AutoUpdate.PROPOSE
        )

    def test_idempotent(self):
        game = self._game("Bot game")
        self._link(game, "http://ifwiki.ru/Игра", self.game_page)

        self._run()
        self._run()

        self.assertEqual(GameTicket.objects.count(), 1)
        self.assertEqual(GameSource.objects.count(), 1)
        self.assertEqual(
            GameTicketAuditLog.objects.filter(
                kind=GameTicketAuditLog.AuditKind.INITIAL_IMPORT
            ).count(),
            1,
        )
