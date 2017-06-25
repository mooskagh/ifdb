from django.core.management.base import BaseCommand
from core.taskqueue import Worker


class Command(BaseCommand):
    help = 'IFDB TaskQueue worker'

    def handle(self, *args, **options):
        Worker()