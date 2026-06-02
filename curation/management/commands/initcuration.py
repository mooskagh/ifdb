from collections import Counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

from curation.models import GameHistory, GameHistoryAuditLog, GameSource
from curation.providers import PROVIDER_BY_TYPE, REGISTERED_PROVIDERS
from games.models import Game

SOURCE_URL_CATEGORIES = {"game_page", "play_online"}


class Command(BaseCommand):
    help = (
        "Seed the curation system (histories, sources, audit log) from the "
        "data produced by the old importer. Idempotent / re-runnable."
    )

    def handle(self, *args, **options):
        def classify(url):
            for provider in REGISTERED_PROVIDERS:
                if provider.owns(url):
                    return provider
            return None

        with transaction.atomic():
            robot, created = get_user_model().objects.get_or_create(
                username=settings.MAINTENANCE_USER,
                defaults={"email": "robot@db.crem.xyz"},
            )
            if created:
                robot.set_unusable_password()
                robot.save()

            histories_created = 0
            sources_created = Counter()
            skipped = 0

            games = Game.objects.prefetch_related(
                "gameurl_set__category", "gameurl_set__url"
            )
            for game in games:
                history, history_created = GameHistory.objects.get_or_create(
                    game=game,
                    defaults={
                        "auto_updates": self.auto_update_policy(game),
                        "state": GameHistory.State.IN_PROGRESS,
                        "creation_time": game.creation_time,
                        "edit_time": game.edit_time or game.creation_time,
                    },
                )
                histories_created += history_created
                seen_sources = set()
                for source in history.gamesource_set.all():
                    provider = PROVIDER_BY_TYPE.get(source.type)
                    if source.url and provider:
                        seen_sources.add((
                            source.type,
                            provider.source_key(source.url),
                        ))

                for gu in game.gameurl_set.order_by("pk"):
                    if gu.category.symbolic_id not in SOURCE_URL_CATEGORIES:
                        continue
                    provider = classify(gu.url.original_url)
                    if provider is None:
                        skipped += 1
                        continue
                    source_type = provider.source_type
                    source_key = provider.source_key(gu.url.original_url)
                    source_identity = (source_type, source_key)
                    if source_identity in seen_sources:
                        continue
                    seen_sources.add(source_identity)
                    _, source_created = GameSource.objects.get_or_create(
                        history=history,
                        url=gu.url.original_url,
                        type=source_type,
                        defaults={
                            "created_at": game.edit_time
                            or game.creation_time
                            or now()
                        },
                    )
                    if source_created:
                        sources_created[source_type] += 1

                GameHistoryAuditLog.objects.get_or_create(
                    history=history,
                    kind=GameHistoryAuditLog.AuditKind.INITIAL_IMPORT,
                    defaults={"actor": robot, "created_at": now()},
                )

        self.stdout.write(f"Histories created: {histories_created}")
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
            GameHistory.AutoUpdate.ACCEPT
            if bot_untouched
            else GameHistory.AutoUpdate.PROPOSE
        )
