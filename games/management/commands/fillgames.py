from django.core.management.base import BaseCommand

from games.tasks.game_importer import ImportGames


class Command(BaseCommand):
    help = "Populates games"

    def add_arguments(self, parser):
        # Named (optional) arguments
        parser.add_argument(
            "--force-update-urls",
            action="store_true",
            dest="force_urls",
            help="Force URL update even in non-updateable games",
        )

    def handle(self, *args, **options):
        ImportGames(options["force_urls"])
