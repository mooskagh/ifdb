import re
import datetime
import games.importer.ifwiki
from django.core.management.base import BaseCommand
from django.utils import timezone
from games.importer import Importer
from games.models import URL
from contest.models import (CompetitionURLCategory, Competition,
                            CompetitionDocument, CompetitionURL,
                            CompetitionNomination, GameList)

COMPETITION_DEFAULT_DOCS = {
    '': 'Главная',
    'rules': 'Правила конкурса',
}

COMP_RE = re.compile(r'@comp (.*)$')
DATE_RE = re.compile(r'@date (\d\d\d\d-\d\d-\d\d)$')
DOC_RE = re.compile(r'@doc (?:(\S+)(?: "([^"]+)")? )?(\S+)$')
LINK_RE = re.compile(r'@link (?:(\S+)(?: "([^"]+)")? )?(\S+)$')
EMPTY_RE = re.compile(r'^$')
COMMIT_RE = re.compile(r'^@commit$')
NOMINATION_RE = re.compile(r'^@nomination (.*)$')

COMPETITION_URLS = [
    'https://ifwiki.ru/%D0%9A%D0%A0%D0%98%D0%9B_' + str(x)
    for x in range(2006, 2018)
] + [
    'https://ifwiki.ru/%D0%97%D0%B8%D0%BC%D0%BD%D0%B8%D0%B9_'
    '%D0%BA%D0%BE%D0%BD%D0%BA%D1%83%D1%80%D1%81_2005-2006',
    'https://ifwiki.ru/%D0%97%D0%B8%D0%BC%D0%BD%D0%B8%D0%B9_'
    '%D0%BA%D0%BE%D0%BD%D0%BA%D1%83%D1%80%D1%81_2007',
] + [
    'https://ifwiki.ru/%D0%97%D0%B8%D0%BC%D0%BD%D1%8F%D1%8F_'
    '%D0%9E%D0%BB%D0%B8%D0%BC%D0%BF%D0%B8%D0%B0%D0%B4%D0%B0_'
    '%D0%9A%D0%B2%D0%B5%D1%81%D1%82%D0%BE%D0%B2_' + str(x)
    for x in range(2010, 2017)
]


def TitleToSlug(title):
    m = re.match(r'КРИЛ (\d+)', title)
    if m:
        return 'kril-' + m.group(1)
    if 'Зимн' in title:
        m = re.search(r'(\d\d\d\d)', title)
        return 'zok-' + m.group(1)
    raise ValueError("Unknown title: [%s]" % title)


def TitleToStartDate(title):
    m = re.match(r'КРИЛ (\d+)', title)
    if m:
        return datetime.date(int(m.group(1)), 8, 1)
    return None


def TitleToEndDate(title):
    m = re.match(r'КРИЛ (\d+)', title)
    if m:
        return datetime.date(int(m.group(1)) + 1, 2, 1)
    if 'Зимн' in title:
        m = re.search(r'(\d\d\d\d)', title)
        return datetime.date(int(m.group(1)), 4, 1)
    raise ValueError("Unknown title: [%s]" % title)


# src_slug, src_url, src_desc, dst_cat, dst_doc_slug
CATEGORIZATION_RULES = [
    ('', '@', '', 'other_site', ''),
    ('', 'ifwiki', 'правила', 'other_site', 'rules'),
    ('download_direct', '', '', 'download_direct', ''),
    ('', '', 'обзор', 'review', ''),
    ('forum', '', '', 'forum', None),
    ('', '', 'официаль', 'official_page', ''),
    ('video', '', '', 'video', ''),
    ('poster', '', '', 'logo', ''),
    ('screenshot', '', '', 'logo', ''),
]

RESULTATIVE_COMPS = ['kril-', 'zok-']

games.importer.ifwiki.ALLOW_INTERNAL_LINKS = True


class Command(BaseCommand):
    help = 'Populates contests from the list'

    def handle(self, *args, **options):
        importer = Importer()
        for seed_url in COMPETITION_URLS:
            data = importer.DispatchImport(seed_url)
            print(repr(data))
            title = data['title']
            self.stdout.write('Competition: %s... ' % title, ending='')
            if Competition.objects.filter(title=title).exists():
                self.stdout.write(self.style.WARNING('already exists.'))
                continue
            comp = Competition()
            comp.title = title
            comp.slug = TitleToSlug(title)
            comp.start_date = TitleToStartDate(title)
            comp.end_date = TitleToEndDate(title)
            comp.save()

            CompetitionNomination.objects.create(
                competition=comp, gamelist=GameList.objects.create())

            urls_checked = {seed_url}
            urls_stored = set()
            urls_to_check = [('(@)', '')]

            while urls_to_check:
                x, doc_slug = urls_to_check.pop()
                if x != '(@)':
                    data = importer.DispatchImport(x)
                    if 'title' not in data:
                        continue

                doc = CompetitionDocument()
                doc.slug = doc_slug
                doc.title = data['title'] if doc_slug else 'Главная'
                doc.text = data['desc']
                doc.competition = comp
                doc.view_perm = '@all'
                doc.save()

                for x in data['urls']:
                    slug = x['urlcat_slug']
                    url = x['url']
                    desc = x['description']

                    if url in urls_stored:
                        continue
                    urls_stored.add(url)

                    for (src_slug, src_url, src_desc, dst_cat,
                         dst_doc_slug) in CATEGORIZATION_RULES:
                        if src_slug and src_slug != slug:
                            continue
                        if ((not re.search(src_url, url))
                                and not (src_url == '@' and url == seed_url)):
                            continue
                        if not re.search(src_desc, desc.lower()):
                            continue

                        cat = CompetitionURLCategory.objects.get(
                            symbolic_id=dst_cat)

                        try:
                            u = URL.objects.get(original_url=url)
                        except URL.DoesNotExist:
                            u = URL()
                            u.original_url = url
                            u.creation_date = timezone.now()
                            u.ok_to_clone = cat.allow_cloning
                            u.save()
                        cu = CompetitionURL()
                        cu.competition = comp
                        cu.url = u
                        cu.category = cat
                        cu.description = desc
                        cu.save()

                        if dst_doc_slug and url not in urls_checked:
                            urls_checked.add(url)
                            urls_to_check.append((url, dst_doc_slug))
                        break

            for x in RESULTATIVE_COMPS:
                if comp.slug.startswith(x):
                    doc = CompetitionDocument()
                    doc.slug = 'results'
                    doc.title = 'Результаты'
                    doc.text = '{{RESULTS}}'
                    doc.competition = comp
                    doc.view_perm = '@all'
                    doc.save()
                    break

            self.stdout.write(self.style.SUCCESS('done.'))
