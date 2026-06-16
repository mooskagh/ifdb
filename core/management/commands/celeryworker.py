import shlex
import subprocess

from django.core.management.base import BaseCommand
from django.utils import autoreload


class Command(BaseCommand):
    help = "Run Celery worker with autoreload."

    def add_arguments(self, parser):
        parser.add_argument(
            "--celery-args",
            default="worker --loglevel=INFO --pool=solo",
            help="Arguments passed after `celery -A <app>`.",
        )
        parser.add_argument(
            "--app",
            default="ifdb",
            help="Celery app path, e.g. ifdb, myproject, proj.celery_app.",
        )

    def handle(self, *args, **options):
        app = options["app"]
        celery_args = shlex.split(options["celery_args"])

        def run_worker():
            subprocess.call(["celery", "-A", app, *celery_args])

        self.stdout.write("Starting Celery worker with autoreload...")
        autoreload.run_with_reloader(run_worker)
