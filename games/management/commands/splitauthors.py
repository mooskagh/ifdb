from django.core.management.base import BaseCommand
from games.updater import UpdatePersonalityUrls
from games.tasks.game_importer import FakeRequest, USER
from games.importer.tools import Importer
from games.importer.ifwiki import WikiQuote
from games.models import PersonalityAlias, Personality, PersonalityURLCategory


class Command(BaseCommand):
    help = 'Split aliases into a separate personality'

    def add_arguments(self, parser):
        parser.add_argument('alias_id', nargs='+', type=int)

    def handle(self, *args, **options):
        importer = Importer()
        request = FakeRequest(USER)
        personality = Personality()
        personality.name = PersonalityAlias.objects.get(
            pk=options['alias_id'][0]).name
        personality.save()
        for a in options['alias_id']:
            alias = PersonalityAlias.objects.get(pk=a)
            alias.personality = personality
            alias.save()
            UpdatePersonalityUrls(importer, request, a, [(
                PersonalityURLCategory.OtherSiteCatId(),
                'Профиль на ifwiki',
                'http://ifwiki.ru/%s' % WikiQuote(alias.name),
            )], True)
