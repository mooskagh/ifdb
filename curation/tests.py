from django.test import TestCase
from django.utils import timezone

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
