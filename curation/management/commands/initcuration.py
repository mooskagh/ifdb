from collections import Counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

from curation.models import GameSource, GameTicket, GameTicketAuditLog
from games.importer.apero import AperoImporter
from games.importer.ifiction import IfictionImporter
from games.importer.ifwiki import IfwikiImporter
from games.importer.insteadgames import InsteadGamesImporter
from games.importer.qspsu import QspsuImporter
from games.importer.questbook import QuestBookImporter
from games.models import Game

SourceType = GameSource.SourceType

# Maps each old-importer matcher to the curation source type it produces.
# QspsuImporter is included on purpose (it is not in REGISTERED_IMPORTERS);
# PlutImporter is excluded (no matching SourceType). Rilarhiv is deferred — its
# Match() needs a live crawl, so it is intentionally not handled here.
IMPORTER_SOURCE_TYPES = {
    IfwikiImporter: SourceType.IFWIKI,
    AperoImporter: SourceType.APERO,
    QspsuImporter: SourceType.QSP,
    InsteadGamesImporter: SourceType.INSTEAD,
    QuestBookImporter: SourceType.QUESTBOOK,
    IfictionImporter: SourceType.IFICTION,
}


class Command(BaseCommand):
    help = (
        "Seed the curation system (tickets, sources, audit log) from the "
        "data produced by the old importer. Idempotent / re-runnable."
    )

    def handle(self, *args, **options):
        classifiers = [
            (importer(), source_type)
            for importer, source_type in IMPORTER_SOURCE_TYPES.items()
        ]

        def classify(url, cat):
            for importer, source_type in classifiers:
                if importer.MatchWithCat(url, cat):
                    return source_type
            return None

        with transaction.atomic():
            robot, created = get_user_model().objects.get_or_create(
                username=settings.MAINTENANCE_USER,
                defaults={"email": "robot@db.crem.xyz"},
            )
            if created:
                robot.set_unusable_password()
                robot.save()

            tickets_created = 0
            sources_created = Counter()
            skipped = 0

            games = Game.objects.prefetch_related(
                "gameurl_set__category", "gameurl_set__url"
            )
            for game in games:
                ticket, ticket_created = GameTicket.objects.get_or_create(
                    game=game,
                    defaults={
                        "auto_updates": self.auto_update_policy(game),
                        "state": GameTicket.State.IN_PROGRESS,
                        "creation_time": game.creation_time,
                        "edit_time": game.edit_time,
                    },
                )
                tickets_created += ticket_created

                for gu in game.gameurl_set.all():
                    source_type = classify(
                        gu.url.original_url, gu.category.symbolic_id
                    )
                    if source_type is None:
                        skipped += 1
                        continue
                    _, source_created = GameSource.objects.get_or_create(
                        ticket=ticket,
                        url=gu.url.original_url,
                        type=source_type,
                    )
                    if source_created:
                        sources_created[source_type] += 1

                GameTicketAuditLog.objects.get_or_create(
                    ticket=ticket,
                    kind=GameTicketAuditLog.AuditKind.INITIAL_IMPORT,
                    defaults={"actor": robot, "created_at": now()},
                )

        self.stdout.write(f"Tickets created: {tickets_created}")
        for source_type, count in sorted(sources_created.items()):
            self.stdout.write(f"  sources [{source_type}]: {count}")
        self.stdout.write(f"Links skipped (unrecognized): {skipped}")

    @staticmethod
    def auto_update_policy(game):
        """Mirror the old ImportedGame.is_updateable: ACCEPT only when the game
        was added by the bot and never human-edited, else PROPOSE."""
        bot_untouched = (
            game.added_by is not None
            and game.added_by.username == settings.MAINTENANCE_USER
            and game.edit_time is None
        )
        return (
            GameTicket.AutoUpdate.ACCEPT
            if bot_untouched
            else GameTicket.AutoUpdate.PROPOSE
        )
