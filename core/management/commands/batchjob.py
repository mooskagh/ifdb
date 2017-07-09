import re
from django.core.management.base import BaseCommand
from games.models import InterpretedGameUrl, URL


def IfwikiCapitalizeFile():
    r = re.compile('^(.*ifwiki.ru/files/)(\w)(.*)$')
    for x in URL.objects.all():
        m = r.match(x.original_url)
        if m and m.group(2).islower():
            print(x.original_url)


def RenameUrls():
    R = re.compile(r'^/uploads/(.*)$')
    for x in URL.objects.all():
        if not x.local_url:
            continue
        m = R.match(x.local_url)
        if not m:
            raise x
        if x.is_uploaded:
            x.local_url = '/f/uploads/' + m.group(1)
        else:
            x.local_url = '/f/backups/' + m.group(1)
        x.save()


def RenameRecodes():
    R = re.compile(r'^/uploads/recode/(.*)$')
    for x in InterpretedGameUrl.objects.all():
        if not x.recoded_url:
            continue
        m = R.match(x.recoded_url)
        if not m:
            raise x
        x.recoded_url = '/f/recodes/' + m.group(1)
        x.save()


class Command(BaseCommand):
    help = 'Does some batch processing.'

    def handle(self, *args, **options):
        pass
        # RenameRecodes()
