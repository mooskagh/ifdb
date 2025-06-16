import datetime
import re

from django.core.management.base import BaseCommand

import games.importer.ifwiki
from contest.models import (
    Competition,
    CompetitionDocument,
    CompetitionURL,
    CompetitionURLCategory,
    GameList,
    GameListEntry,
)
from games.importer import Importer
from games.models import GameTag, GameTagCategory
from games.tools import CreateUrl

COMPETITION_DEFAULT_DOCS = {
    "": "Главная",
    "rules": "Правила конкурса",
}

COMP_RE = re.compile(r"@comp (.*)$")
DATE_RE = re.compile(r"@date (\d\d\d\d-\d\d-\d\d)$")
DOC_RE = re.compile(r'@doc (?:(\S+)(?: "([^"]+)")? )?(\S+)$')
LINK_RE = re.compile(r'@link (?:(\S+)(?: "([^"]+)")? )?(\S+)$')
EMPTY_RE = re.compile(r"^$")
COMMIT_RE = re.compile(r"^@commit$")
NOMINATION_RE = re.compile(r"^@nomination (.*)$")

COMPETITION_URLS_OLD = (
    [
        "https://ifwiki.ru/%D0%9A%D0%A0%D0%98%D0%9B_" + str(x)
        for x in range(2006, 2018)
    ]
    + [
        (
            "https://ifwiki.ru/%D0%97%D0%B8%D0%BC%D0%BD%D0%B8%D0%B9_"
            "%D0%BA%D0%BE%D0%BD%D0%BA%D1%83%D1%80%D1%81_2005-2006"
        ),
        (
            "https://ifwiki.ru/%D0%97%D0%B8%D0%BC%D0%BD%D0%B8%D0%B9_"
            "%D0%BA%D0%BE%D0%BD%D0%BA%D1%83%D1%80%D1%81_2007"
        ),
    ]
    + [
        "https://ifwiki.ru/%D0%97%D0%B8%D0%BC%D0%BD%D1%8F%D1%8F_"
        "%D0%9E%D0%BB%D0%B8%D0%BC%D0%BF%D0%B8%D0%B0%D0%B4%D0%B0_"
        "%D0%9A%D0%B2%D0%B5%D1%81%D1%82%D0%BE%D0%B2_"
        + str(x)
        for x in range(2010, 2017)
    ]
    + [
        "https://ifwiki.ru/%D0%9F%D0%B0%D1%80%D0%BE%D0%B2%D0%BE%D0%B7%D0%B8%D0%BA_3"
    ]
    + [
        "https://ifwiki.ru/%D0%9B%D0%9E%D0%9A_" + str(x)
        for x in range(2004, 2015)
    ]
    + [
        "https://ifwiki.ru/%D0%9B%D0%9E%D0%9A_2015-2016",
        "https://ifwiki.ru/%D0%9B%D0%9E%D0%9A_2017",
    ]
)

COMPETITION_URLS_OLD2 = [
    "https://ifwiki.ru/QSP-Compo_" + str(x) for x in range(2009, 2018)
]

COMPETITION_URLS = [
    "https://ifwiki.ru/%D0%97%D0%BE%D0%BB%D0%BE%D1%82%D0%BE%D0%B9_%D0%A5%D0%BE%D0%BC%D1%8F%D0%BA_"
    + str(x)
    for x in range(2009, 2016)
]


def TitleToSlug(title):
    m = re.match(r"КРИЛ (\d+)", title)
    if m:
        return "kril-" + m.group(1)
    if "Зимн" in title:
        m = re.search(r"(\d\d\d\d)", title)
        return "zok-" + m.group(1)
    if "Паровоз" in title:
        return "parovoz-2017"
    if "ЛОК" in title:
        m = re.search(r"(\d\d\d\d)$", title)
        return "lok-" + m.group(1)
    if "QSP-Compo" in title:
        m = re.search(r"(\d\d\d\d)$", title)
        return "qspcompo-" + m.group(1)
    if "Хомяк" in title:
        m = re.search(r"(\d\d\d\d)$", title)
        return "zh-" + m.group(1)
    raise ValueError("Unknown title: [%s]" % title)


def TitleToStartDate(title):
    m = re.match(r"КРИЛ (\d+)", title)
    if m:
        return datetime.date(int(m.group(1)), 8, 1)
    return None


def TitleToEndDate(title):
    m = re.match(r"КРИЛ (\d+)", title)
    if m:
        return datetime.date(int(m.group(1)) + 1, 2, 1)
    if "Зимн" in title:
        m = re.search(r"(\d\d\d\d)", title)
        return datetime.date(int(m.group(1)), 4, 1)
    if "Паровоз" in title:
        return datetime.date(2017, 11, 26)
    if "ЛОК" in title:
        m = re.search(r"(\d\d\d\d)$", title)
        return datetime.date(int(m.group(1)), 10, 1)
    if "QSP-Compo" in title:
        m = re.search(r"(\d\d\d\d)$", title)
        return datetime.date(int(m.group(1)), 3, 31)
    if "Хомяк" in title:
        m = re.search(r"(\d\d\d\d)$", title)
        return datetime.date(int(m.group(1)), 12, 31)
    raise ValueError("Unknown title: [%s]" % title)


def TitleToTag(title):
    m = re.match(r"КРИЛ (\d+)", title)
    if m:
        return "КРИЛ-" + m.group(1)
    if "Зимн" in title:
        m = re.search(r"(\d\d\d\d)", title)
        return "ЗОК-" + m.group(1)
    if "ЛОК" in title:
        m = re.search(r"(\d\d\d\d)$", title)
        return "ЛОК-" + m.group(1)
    if "Паровоз" in title:
        return "Паровозик-2017"
    if "QSP-Compo" in title:
        m = re.search(r"(\d\d\d\d)$", title)
        return "QSP-Compo " + m.group(1)
    if "Хомяк" in title:
        m = re.search(r"(\d\d\d\d)$", title)
        return "Золотой Хомяк " + m.group(1)


# src_slug, src_url, src_desc, dst_cat, dst_doc_slug
CATEGORIZATION_RULES = [
    ("", "@", "", "other_site", ""),
    ("", "ifwiki", "правила", "other_site", "rules"),
    (
        "",
        r"ifwiki.*%D0%9F%D1%80%D0%B0%D0%B2%D0%B8%D0%BB%D0%B0",
        "",
        "other_site",
        "rules",
    ),
    ("download_direct", "", "", "download_direct", ""),
    ("", "", "обзор", "review", ""),
    ("forum", "", "", "forum", None),
    ("", "", "официаль", "official_page", ""),
    ("video", "", "", "video", ""),
    ("poster", "", "", "logo", ""),
    ("screenshot", "", "", "logo", ""),
]

RESULTATIVE_COMPS = ["kril-", "zok-", "qspcompo-", "zh-"]

games.importer.ifwiki.ALLOW_INTERNAL_LINKS = True

PLACE_RE = re.compile(r"(\d+)-о?е мест")


class Command(BaseCommand):
    help = "Populates contests from the list"

    def handle(self, *args, **options):
        importer = Importer()
        for seed_url in COMPETITION_URLS:
            data = importer.DispatchImport(seed_url)
            title = data["title"]
            self.stdout.write("Competition: %s... " % title, ending="")
            slug = TitleToSlug(title)
            if Competition.objects.filter(slug=slug).exists():
                self.stdout.write(self.style.WARNING("already exists."))
                continue
            comp = Competition()
            comp.title = title
            comp.slug = slug
            comp.start_date = TitleToStartDate(title)
            comp.end_date = TitleToEndDate(title)
            comp.published = True
            comp.save()

            gamelist = GameList.objects.create(competition=comp)

            urls_checked = {seed_url}
            urls_stored = set()
            urls_to_check = [("(@)", "index")]
            used_slugs = set()

            while urls_to_check:
                x, doc_slug = urls_to_check.pop()
                if x != "(@)":
                    data = importer.DispatchImport(x)
                    if "title" not in data:
                        continue

                if doc_slug in used_slugs:
                    continue

                used_slugs.add(doc_slug)

                doc = CompetitionDocument()
                doc.slug = doc_slug
                doc.title = (
                    "Описание конкурса"
                    if doc_slug == "index"
                    else data["title"]
                )
                doc.text = data["desc"]
                doc.competition = comp
                doc.view_perm = "@all"
                doc.save()

                for x in data["urls"]:
                    slug = x["urlcat_slug"]
                    url = x["url"]
                    desc = x["description"]

                    if url in urls_stored:
                        continue
                    urls_stored.add(url)

                    for (
                        src_slug,
                        src_url,
                        src_desc,
                        dst_cat,
                        dst_doc_slug,
                    ) in CATEGORIZATION_RULES:
                        if src_slug and src_slug != slug:
                            continue
                        if (not re.search(src_url, url)) and not (
                            src_url == "@" and url == seed_url
                        ):
                            continue
                        if not re.search(src_desc, desc.lower()):
                            continue

                        cat = CompetitionURLCategory.objects.get(
                            symbolic_id=dst_cat
                        )

                        u = CreateUrl(url, ok_to_clone=cat.allow_cloning)
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

            is_comp = False
            for x in RESULTATIVE_COMPS:
                if comp.slug.startswith(x):
                    is_comp = True
                    break
            doc = CompetitionDocument()
            doc.slug = ""
            doc.title = "Результаты" if is_comp else "Участники"
            doc.text = "{{RESULTS}}" if is_comp else "{{PARTICIPANTS}}"
            doc.competition = comp
            doc.view_perm = "@all"
            doc.save()

            tag = TitleToTag(title)
            if tag:
                cat = GameTagCategory.objects.get(symbolic_id="competition")
                try:
                    t = GameTag.objects.get(category=cat, name=tag)
                    for g in t.game_set.all():
                        e = GameListEntry()
                        e.gamelist = gamelist
                        e.game = g
                        m = PLACE_RE.search(g.description)
                        if m:
                            e.rank = m.group(1)
                        e.save()

                except GameTag.DoesNotExist:
                    pass

            self.stdout.write(self.style.SUCCESS("done."))
