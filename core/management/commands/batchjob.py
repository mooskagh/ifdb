import re
from logging import getLogger

from django.core.management.base import BaseCommand

from games.models import (
    URL,
    Game,
    GameAuthor,
    GameURL,
    Personality,
    PersonalityAlias,
    PersonalityAliasRedirect,
)

logger = getLogger("worker")


def IfwikiCapitalizeFile():
    r = re.compile(r"^(.*ifwiki.ru/files/)(\w)(.*)$")
    for x in URL.objects.all():
        m = r.match(x.original_url)
        if m and m.group(2).islower():
            print(x.original_url)


def RemoveAuthors():
    Personality.objects.all().delete()
    GameAuthor.objects.filter(game__edit_time__isnull=True).delete()
    PersonalityAlias.objects.filter(gameauthor__isnull=True).delete()


# TODO Run that as a periodic job.
def FixGameAuthors():
    logger.info("*** Fixing game duplicate aliases")
    for g in Game.objects.all():
        clusters = dict()
        for x in GameAuthor.objects.filter(game=g).select_related():
            clusters.setdefault((x.role.id, x.author.personality), []).append(
                x
            )
        for k, v in clusters.items():
            if len(v) == 1:
                continue
            best = None
            record = None
            for i, y in enumerate(v):
                count = y.author.gameauthor_set.count()
                if best is None or count < best:
                    best = count
                    record = i

            logger.info(
                "Game [%s], over [%s] we are keeping [%s]" % (g, v, v[record])
            )
            for i, y in enumerate(v):
                if i != record:
                    y.delete()
            if g.edit_time is not None:
                logger.warning("Game [%s] NOT AUTOUPDATEABLE!" % g)

    logger.info("*** Killing hanging personalities")
    Personality.objects.filter(personalityalias__isnull=True).delete()

    logger.info("*** Killing hanging aliases")
    PersonalityAlias.objects.filter(
        keep_if_empty=False, gameauthor__isnull=True
    ).delete()


def FixDuplicateUrls():
    logger.info("Fixing duplicate URLs")
    for x in Game.objects.all():
        urls = set()
        for y in GameURL.objects.filter(game=x):
            v = (y.url_id, y.category_id)
            if v in urls:
                logger.info("Game %s, url %s, removing" % (x, y))
                y.delete()
            else:
                urls.add(v)


def PopulateAliasRedirects():
    for x in PersonalityAlias.objects.all():
        if not x.hidden_for and not x.is_blacklisted:
            continue
        PersonalityAliasRedirect.objects.create(
            name=x.name, hidden_for=x.hidden_for
        )
        x.delete()


class Command(BaseCommand):
    help = "Does some batch processing."

    def add_arguments(self, parser):
        parser.add_argument("cmd")

    def handle(self, cmd, *args, **options):
        options = {
            "fixgameauthors": FixGameAuthors,
            "fixurldups": FixDuplicateUrls,
        }
        if cmd in options:
            options[cmd]()
        else:
            print(
                "Unknown command, valid ones are:\n%s"
                % ", ".join(options.keys())
            )
