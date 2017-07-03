from django.core.management.base import BaseCommand
from games.tasks.game_importer import ImportGames


class Command(BaseCommand):
    help = 'Populates games'

    def handle(self, *args, **options):
        ImportGames()
