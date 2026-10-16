import re
import statistics
from typing import Any
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as etree

import markdown
from django import template
from django.contrib.auth.models import AbstractBaseUser
from django.db.models import F
from django.utils import timezone
from markdown.blockprocessors import BlockProcessor
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.postprocessors import Postprocessor
from markdown.util import AtomicString

from .models import URL, Game, GameURL, GameVote


def SnippetFromList(games, populate_authors=True):
    posters = (
        GameURL.objects
        .filter(category__symbolic_id="poster")
        .filter(game__in=games)
        .select_related("url", "category")
        .prefetch_related("url__fetches__stored_file")
    )
    screenshots = (
        GameURL.objects
        .filter(category__symbolic_id="screenshot")
        .filter(game__in=games)
        .select_related("url", "category")
        .prefetch_related("url__fetches__stored_file")
    )

    g2p = {}
    for x in posters:
        g2p[x.game_id] = x.GetLocalUrl()
    for x in screenshots:
        if x.game_id not in g2p:
            g2p[x.game_id] = x.GetLocalUrl()

    for x in games:
        x.poster = g2p.get(x.id)
        if populate_authors:
            x.authors = [
                x
                for x in x.gameauthor_set.all()
                if x.role.symbolic_id == "author"
            ]
    return games


def FormatDate(x):
    if not x:
        return None
    return "%d %s %d" % (
        x.day,
        [
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        ][x.month - 1],
        x.year,
    )


def FormatDateShort(x):
    if not x:
        return None
    return "%d %s" % (
        x.day,
        [
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        ][x.month - 1],
    )


def FormatTime(x):
    if not x:
        return None
    return "%04d-%02d-%02d %02d:%02d" % (
        x.year,
        x.month,
        x.day,
        x.hour,
        x.minute,
    )


def ConcoreNumeral(value, arg):
    bits = arg.split(",")
    try:
        one = str(value)[-1:]
        dec = str(value)[-2:-1]
        if dec == "1":
            res = bits[2]
        elif one == "1":
            res = bits[0]
        elif one in "234":
            res = bits[1]
        else:
            res = bits[2]
        return "%s %s" % (value, res)
    except (IndexError, ValueError):
        raise template.TemplateSyntaxError
    return ""


def FormatLag(x):
    x = int(x)
    if x <= 0:
        x = -x
        fmtstr = "%s назад"
    else:
        fmtstr = "через %s"

    def GetDurationStr(x):
        if x < 60:
            return ConcoreNumeral(x, "секунду,секунды,секунд")
        x //= 60
        if x < 60:
            return ConcoreNumeral(x, "минуту,минуты,минут")
        x //= 60
        if x < 24:
            return ConcoreNumeral(x, "час,часа,часов")
        x //= 24
        if x < 31:
            return ConcoreNumeral(x, "день,дня,дней")
        x //= 30
        if x < 12:
            return ConcoreNumeral(x, "месяц,месяца,месяцев")
        x //= 12
        return ConcoreNumeral(x, "год,года,лет")

    return fmtstr % GetDurationStr(x)


def ExtractYoutubeId(url):
    purl = urlparse(url)
    if purl.hostname in ["youtube.com", "www.youtube.com"]:
        q = parse_qs(purl.query).get("v")
        if q:
            return q[0]
    elif purl.hostname == "youtu.be":
        return purl.path[1:]


def StarsFromRating(rating):
    avg = round(rating * 10)
    res = [10] * (avg // 10)
    if avg % 10 != 0:
        res.append(avg % 10)
    res.extend([0] * (5 - len(res)))
    return res


def DiscountRating(x, count, P1=2.7, P2=0.3, P3=1.3):
    #  return (x - P1) * (P2 + count) / (P2 + count + 1) + P1
    v = (x - P1) * (P2 ** (1 / count)) * P3 + P1
    if v > 5:
        v = 5
    if v < 1:
        v = 1
    return v


def ComputeGameRating(votes):
    ds = {}
    ds["scores"] = len(votes)
    if votes:
        ds["avg"] = statistics.mean(votes)
        ds["vote"] = DiscountRating(ds["avg"], len(votes))
    else:
        ds["avg"] = 0.0

    ds["stars"] = StarsFromRating(ds["avg"])
    ds["avg_txt"] = ("%3.1f" % ds["avg"]).replace(".", ",")
    return ds


def ComputeHonors(author=None):
    xs = dict()
    votes = GameVote.objects.filter(
        game__in=Game.objects.published(),
        game__gameauthor__role__symbolic_id="author",
    ).annotate(
        gameid=F("game__id"),
        author=F("game__gameauthor__author__personality__id"),
    )
    if author:
        votes = votes.filter(author=author)

    for x in votes:
        xs.setdefault(x.author, {}).setdefault(x.gameid, []).append(
            x.star_rating
        )

    res = dict()
    for a, games in xs.items():
        gams = []
        for votes in games.values():
            gams.append(DiscountRating(sum(votes) / len(votes), len(votes)))
        gams.sort()
        games_to_consider = len(gams) - int(len(gams) * 0.26)
        sms = sum(gams[-games_to_consider:]) / games_to_consider
        res[a] = DiscountRating(sms, len(games), P1=2.3, P2=0.2, P3=2.4)
    if author:
        return res.get(author, 0.0)
    else:
        return res


def GroupByCategory(queryset, catfield, follow):
    items = {}
    cats = []
    for x in queryset:
        category = getattr(x, catfield)
        if follow:
            x = getattr(x, follow)
        if category in items:
            items[category].append(x)
        else:
            cats.append(category)
            items[category] = [x]
    cats.sort(key=lambda x: x.order)
    res = []
    for r in cats:
        res.append({"category": r, "items": items[r]})
    return res


def PartitionItems(queryset, partitions, catfield="category", follow=None):
    links = GroupByCategory(queryset, catfield, follow=follow)
    rest = []
    cats = {x: None for y in partitions for x in y}
    for x in links:
        if x["category"].symbolic_id in cats:
            cats[x["category"].symbolic_id] = x
        else:
            rest.append(x)

    res = []
    for x in partitions:
        r = []
        for y in x:
            if cats[y] and cats[y]["items"]:
                for z in cats[y]["items"]:
                    r.append(z)
        res.append(r)
    return res + [rest]


SNIPPET_PATTERN = re.compile(r"{{\s*([\w\d\s]+)\s*}}")


class MarkdownSnippetProcessor(BlockProcessor):
    def test(self, parent, block):
        return SNIPPET_PATTERN.match(block)

    def run(self, parent, blocks):
        block = blocks.pop(0)
        m = SNIPPET_PATTERN.match(block)
        params = m.group(1).split()
        snippet_call = "render_%s" % params[0]
        if hasattr(self.provider, snippet_call):
            val = self.md.htmlStash.store(
                getattr(self.provider, snippet_call)(*params[1:])
            )
        else:
            val = self.md.htmlStash.store(m.group(1) + "??")

        h = etree.SubElement(parent, "div")
        h.text = AtomicString(val)


class MarkdownSnippet(Extension):
    def __init__(self, provider):
        super().__init__()
        self.provider = provider

    def extendMarkdown(self, md):
        processor = MarkdownSnippetProcessor(md.parser)
        processor.provider = self.provider
        processor.md = md
        md.parser.blockprocessors.register(processor, "snippets", 200)


A_TAG_RE = re.compile(r"<a\b([^>]*)>", re.IGNORECASE)
HREF_RE = re.compile(r"""\bhref=(?:(["'])(.*?)\1|([^\s>]+))""", re.IGNORECASE)
TARGET_RE = re.compile(r"""\btarget=(?:(["']).*?\1|[^\s>]+)""", re.IGNORECASE)
REL_RE = re.compile(r"""\brel=(?:(["']).*?\1|[^\s>]+)""", re.IGNORECASE)


class BareUrlInlineProcessor(InlineProcessor):
    TRAILING_PUNCT = ".,:;!?]}\"'"

    def handleMatch(
        self, m: re.Match[str], data: str
    ) -> tuple[etree.Element | None, int | None, int | None]:
        raw = m.group(0)
        trimmed = raw.rstrip(self.TRAILING_PUNCT)
        while trimmed.endswith(")") and trimmed.count(")") > trimmed.count(
            "("
        ):
            trimmed = trimmed[:-1].rstrip(self.TRAILING_PUNCT)

        if not trimmed:
            return None, None, None

        cut = len(raw) - len(trimmed)
        el = etree.Element("a")
        el.set("href", trimmed)
        el.text = AtomicString(trimmed)
        return el, m.start(0), m.end(0) - cut


class ExternalLinksPostprocessor(Postprocessor):
    def __init__(
        self,
        md: markdown.Markdown,
        target_blank: bool = True,
        nofollow: bool = True,
    ) -> None:
        super().__init__(md)
        self.target_blank = target_blank
        self.nofollow = nofollow

    def run(self, text: str) -> str:
        def replace_a(match: re.Match[str]) -> str:
            attrs = match.group(1)
            href_match = HREF_RE.search(attrs)
            if not href_match:
                return match.group(0)
            href = href_match.group(2) or href_match.group(3)
            if not href.startswith(("http://", "https://", "//")):
                return match.group(0)

            new_attrs = attrs.rstrip()
            if self.target_blank:
                if TARGET_RE.search(new_attrs):
                    new_attrs = TARGET_RE.sub('target="_blank"', new_attrs)
                else:
                    new_attrs += ' target="_blank"'
            if self.nofollow:
                if REL_RE.search(new_attrs):
                    new_attrs = REL_RE.sub(
                        'rel="nofollow noopener noreferrer"', new_attrs
                    )
                else:
                    new_attrs += ' rel="nofollow noopener noreferrer"'
            return f"<a{new_attrs}>"

        return A_TAG_RE.sub(replace_a, text)


class CommentLinksExtension(Extension):
    def __init__(
        self,
        *,
        autolink: bool = True,
        target_blank: bool = True,
        nofollow: bool = True,
    ) -> None:
        super().__init__()
        self.autolink = autolink
        self.target_blank = target_blank
        self.nofollow = nofollow

    def extendMarkdown(self, md: markdown.Markdown) -> None:
        if self.autolink:
            md.inlinePatterns.register(
                BareUrlInlineProcessor(r"https?://[^\s<>]+"), "bare_url", 85
            )
        if self.target_blank or self.nofollow:
            md.postprocessors.register(
                ExternalLinksPostprocessor(
                    md, self.target_blank, self.nofollow
                ),
                "external_links",
                15,
            )


def RenderMarkdown(
    content: str | None,
    snippet_provider: Any = None,
    *,
    autolink: bool = False,
    target_blank: bool = False,
    nofollow: bool = False,
) -> str:
    if not content:
        return ""
    if "{|" in content:
        from games.importer.ifwiki import convert_wikitext_tables

        content = convert_wikitext_tables(content)
    extensions: list[Extension | str] = [
        "markdown.extensions.extra",
        "markdown.extensions.smarty",
        "markdown.extensions.wikilinks",
        "markdown_del_ins",
    ]
    if snippet_provider:
        extensions.append(MarkdownSnippet(snippet_provider))
    if autolink or target_blank or nofollow:
        extensions.append(
            CommentLinksExtension(
                autolink=autolink,
                target_blank=target_blank,
                nofollow=nofollow,
            )
        )
    return markdown.markdown(content, extensions=extensions)


def RenderCommentMarkdown(content: str | None) -> str:
    return RenderMarkdown(
        content,
        autolink=True,
        target_blank=True,
        nofollow=True,
    )


def CreateUrl(
    url: str,
    *,
    creator: AbstractBaseUser | None = None,
    is_uploaded: bool = False,
) -> URL:
    try:
        u = URL.objects.get(original_url=url)
    except URL.DoesNotExist:
        u = URL()
        u.original_url = url
        u.creation_date = timezone.now()
        u.creator = creator
        u.is_uploaded = is_uploaded
        u.save()
        return u

    return u


def GetIpAddr(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0]
    else:
        return request.META.get("REMOTE_ADDR")
