from games.models import PersonalityAlias, Personality
from games.importer.tools import GetAuthorBio
from logging import getLogger
from django.db.models import Max

logger = getLogger('worker')

# LAST_FIRST_RE = re.compile(r'^(\w+), (\w+)$')


class AuthorFixer:
    def __init__(self):
        self.new_personalities = []
        self.name_to_aliases = {}
        for x in PersonalityAlias.objects.all():
            self.name_to_aliases.setdefault(x.name.lower(), []).append(x.id)

    def FixSingleAlias(self, author):
        if author.is_blacklisted:
            if author.personality:
                logger.info("Removing personality from blacklisted author [%s]"
                            % author.name)
                author.personality = None
                author.save()
            return

        if author.personality:
            return

        if author.hidden_for:
            if not author.personality:
                logger.info(
                    "Attaching personality for hidden alias: %s" % author.name)
                author.personality = author.hidden_for.personality
                author.save()
            return

        for yid in self.name_to_aliases.get(author.name.lower()):
            if yid == author.id:
                continue
            y = PersonalityAlias.objects.get(pk=yid)
            if y.is_blacklisted or y.personality:
                logger.info("Attaching name %s to %s" % (y.name, author.name))
                author.is_blacklisted = y.is_blacklisted
                author.personality = y.personality
                author.hidden_for = y.hidden_for
                author.save()
                return

        fetched = GetAuthorBio(author.name)
        if 'canonical' in fetched:
            logger.info("Found canonical name for [%s]: [%s]" %
                        (author.name, fetched['canonical']))
            for yid in self.name_to_aliases.get(fetched['canonical'].lower(),
                                                []):
                if yid == author.id:
                    continue
                logger.info("Reattaching [%s] to canonical [%s]" %
                            (author.name, fetched['canonical']))
                y = PersonalityAlias.objects.get(pk=yid)
                self.FixSingleAlias(y)
                author.personality = y.personality
                author.save()
                return

        # m = LAST_FIRST_RE.match(author.name.lower())
        # if m:
        #     name = '%s %s' % (m.group(2), m.group(1))
        #     logger.info("Trying alternative name [%s]" % name)
        #     for yid in self.name_to_aliases.get(name, []):
        #         logger.info("Found under alternative name [%s]" % name)
        #         y = PersonalityAlias.objects.get(pk=yid)
        #         self.FixSingleAlias(y)
        #         author.hidden_for = y
        #         author.personality = y.personality
        #         author.save()
        #         return

        logger.info("Creating new personality: [%s]" % author.name)
        p = Personality()
        p.name = author.name
        if 'bio' in fetched:
            p.bio = fetched['bio']            
        p.save()
        if 'urls' in fetched:
            

        self.new_personalities = p
        author.personality = p
        author.save()

    def FixSingleGame(self, game):
        authors = game.gameauthor_set()
        role_to_authors = {}
        for x in authors:
            role_to_authors.setdefault(x.role__id, []).append(x)

        for authors in role_to_authors.values():
            personality_to_gameauthor = {}
            for x in authors:
                alias = x.author
                if alias.is_blacklisted:
                    logger.info("Removing blacklisted author %s" % x)
                    x.delete()
                    continue
                if alias.hidden_for:
                    while alias.hidden_for:
                        alias = alias.hidden_for
                    logger.info("Replacing %s to %s" % (x.author, alias))
                    x.author = alias
                    x.save()
                if alias.personality:
                    personality_to_gameauthor.setdefault(
                        alias.personality__id, []).append(x)
            for x in personality_to_gameauthor.values():
                if len(x) < 2:
                    continue

                logger.info("Removing duplicate entries: %s" % ', '.join(
                    ["[%s]" % w for w in x]))

                x.sort(key=lambda y: y.id)
                for y in x[1:]:
                    y.delete()

    def FixSinglePersonality(self, personality):
        x = PersonalityAlias.objects.filter(personality=personality).annotate(
            gamz=Max('gameauthor__count')).filter(gameauthor__count='gamz')
        personality.name = x[0].name
        personality.save()


def FixAuthorAliases(alias_ids):
    to_save = set()

    for aid in alias_ids:
        FixSingleAuthor(PersonalityAlias.objects.get(pk=aid))

    for x in to_save:
        x.save()
