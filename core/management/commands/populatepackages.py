import json
import os
import re
from logging import getLogger

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Package, PackageVersion
from games.models import Game

logger = getLogger("worker")
R = re.compile(r"(\d{4}).txt")


class Command(BaseCommand):
    help = "Populates packages from the current directory."

    def add_arguments(self, parser):
        parser.add_argument("dir", type=str)

    def handle(self, *args, **options):
        os.chdir(options["dir"])
        for ff in os.listdir("."):
            m = R.match(ff)
            if not m:
                continue
            with open(ff, encoding="utf-8") as f:
                j = json.loads(f.read())
            pkg = j["pkg"]
            gam = j.get("games")
            if gam:
                gam = gam[0]

            met = j["metadata"]
            ver = j.get("version", "0.0.0")
            md5 = j["md5"]

            try:
                p = Package.objects.get(name=pkg)
            except:
                p = Package()

            g = None
            if gam:
                try:
                    g = Game.objects.get(title=gam)
                except:
                    logger.error("Game not found at %s (%s)" % (pkg, ff))

            p.name = pkg
            p.game = g
            p.save()

            try:
                v = PackageVersion.objects.get(package=p, version=ver)
            except:
                v = PackageVersion()
                v.creation_date = timezone.now()

            v.package = p
            v.version = ver
            v.md5hash = md5
            v.metadata_json = json.dumps(met, indent=2, ensure_ascii=False)
            v.save()
