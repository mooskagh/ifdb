import datetime
import json
import re
import time
from logging import getLogger
from urllib.parse import quote, unquote

import mwparserfromhell

from core.crawler import FetchUrlToString

from .tools import CategorizeAuthorUrl, CategorizeUrl

logger = getLogger("crawler")


class IfwikiImporter:
    def MatchWithCat(self, url, cat):
        return cat == "game_page" and self.Match(url)

    def Match(self, url):
        return IFWIKI_URL.match(url)

    def MatchAuthor(self, url):
        return self.Match(url)

    def Import(self, url):
        return ImportFromIfwiki(url)

    def ImportAuthor(self, url):
        return ImportAuthorFromIfwiki(url)

    def GetUrlCandidates(self):
        return FetchCategoryUrls("Игры")

    def GetDirtyUrls(self, age_minutes=60 * 14):
        return GetDirtyUrls(age_minutes)


CATEGORY_STR = (
    r"ifwiki.ru/%D0%9A%D0%B0%D1%82%D0%B5%D0%B3%D0%BE%D1%80%D0%B8%D1%8F:"
)

ALLOW_INTERNAL_LINKS = False


def _batch(iterable, n=40):
    length = len(iterable)
    for ndx in range(0, length, n):
        yield iterable[ndx : min(ndx + n, length)]


def GetDirtyUrls(age_minutes):
    ids = set()
    r = json.loads(
        FetchUrlToString(
            r"http://ifwiki.ru/api.php?action=query&list=recentchanges&"
            r"rclimit=500&format=json&rcend=%d"
            % int(time.time() - 60 * age_minutes),
            use_cache=False,
        )
    )["query"]["recentchanges"]

    for x in r:
        ids.add(x["pageid"])

    res = []
    for batch in _batch(list(ids)):
        pageidlist = "|".join([str(x) for x in batch if x != 0])
        if not pageidlist:
            continue
        r = json.loads(
            FetchUrlToString(
                r"http://ifwiki.ru/api.php?action=query&prop=info&format=json&"
                r"inprop=url&pageids=" + pageidlist,
                use_cache=False,
            )
        )
        for _, v in r["query"]["pages"].items():
            if "fullurl" in v:
                res.append(v["fullurl"])
    return res


def FetchCategoryUrls(category):
    keystart = ""
    ids = set()

    while True:
        r = json.loads(
            FetchUrlToString(
                r"http://ifwiki.ru/api.php?action=query&list=categorymembers&"
                r"cmtitle=%D0%9A%D0%B0%D1%82%D0%B5%D0%B3%D0%BE%D1%80%D0"
                r"%B8%D1%8F:" + quote(category) + r"&rawcontinue=1&"
                r"cmlimit=400&format=json&cmsort=sortkey&"
                r"cmprop=ids|title|sortkey&cmstarthexsortkey=" + keystart,
                use_cache=False,
            )
        )
        res = r["query"]["categorymembers"]

        for x in res:
            ids.add(x["pageid"])

        if len(res) <= 300:
            break
        else:
            keystart = res[-1]["sortkey"]

    res = []
    for batch in _batch(list(ids)):
        pageidlist = "|".join([str(x) for x in batch])
        r = json.loads(
            FetchUrlToString(
                r"http://ifwiki.ru/api.php?action=query&prop=info&format=json&"
                r"inprop=url&pageids=" + pageidlist,
                use_cache=False,
            )
        )
        for _, v in r["query"]["pages"].items():
            if CATEGORY_STR not in v["fullurl"]:
                res.append(v["fullurl"])
    return res


def CapitalizeFirstLetter(x):
    return x[:1].upper() + x[1:]


def WikiQuote(name):
    return quote(CapitalizeFirstLetter(name.replace(" ", "_")))


REDIRECT_RE = re.compile(r"#(?:REDIRECT|ПЕРЕНАПРАВЛЕНИЕ)\s*\[\[(.*)\]\]")


def ImportAuthorFromIfwiki(url, res=None):
    if not res:
        res = {}
    m = IFWIKI_URL.match(url)

    try:
        fetch_url = f"{m.group(1)}/index.php?title={m.group(2)}&action=raw"
        name = unquote(m.group(2)).replace("_", " ")
        cont = FetchUrlToString(fetch_url) + "\n"
    except Exception:
        logger.info(
            f"Error while importing [{url}] from Ifwiki", exc_info=True
        )
        return {}

    m = REDIRECT_RE.match(cont)
    if m:
        res["canonical"] = m.group(1)
        url_to_fetch = f"http://ifwiki.ru/{WikiQuote(res['canonical'])}"
        res["canonical_url"] = url_to_fetch
        return ImportAuthorFromIfwiki(url_to_fetch, res)

    context = WikiAuthorParsingContext(name, url)
    parsed_wikitext = mwparserfromhell.parse(cont)

    # Convert to markdown-like text
    output = process_wikitext_for_author(parsed_wikitext, context)

    res["name"] = name
    res["bio"] = output + "\n\n_(описание взято с сайта ifwiki.ru)_"
    res.setdefault("urls", []).extend(context.urls)

    return res


def ImportFromIfwiki(url):
    m = IFWIKI_URL.match(url)

    try:
        fetch_url = f"{m.group(1)}/index.php?title={m.group(2)}&action=raw"
        cont = FetchUrlToString(fetch_url) + "\n"
    except Exception:
        logger.exception(f"Error while importing [{url}] from Ifwiki")
        return {"error": "Не открывается что-то этот URL."}

    res = {"priority": 100}

    context = WikiParsingContext(unquote(m.group(2)).replace("_", " "), url)

    try:
        parsed_wikitext = mwparserfromhell.parse(cont)
        output = process_wikitext_for_game(parsed_wikitext, context)
    except Exception:
        logger.exception(f"Error while parsing {url}")
        return {"error": "Какая-то ошибка при парсинге. Надо сказать админам."}

    res["title"] = context.title
    res["desc"] = output + "\n\n_(описание взято с сайта ifwiki.ru)_"
    if context.release_date:
        res["release_date"] = context.release_date
    res["authors"] = context.authors
    res["tags"] = context.tags
    res["urls"] = context.urls

    return res


IFWIKI_URL = re.compile(r"(https?://ifwiki.ru)/([^?]+)")
IFWIKI_LINK_PARSE = re.compile(r"\[\[(.*?)\]\]")
IFWIKI_LINK_INTERNALS_PARSE = re.compile(
    r"^(?:([^:\]|]*)::?)?([^:\]|]+)(?:\|([^\]|]+))?(?:\|([^\]]+))?$"
)

IFWIKI_ROLES = [
    ("автор", "author"),
    ("Автор", "author"),
    ("Переводчик", "translator"),
    ("Персонаж", "character"),
    ("Тестировщик", "tester"),
    ("Участник", "member"),
    ("Иллюстратор", "artist"),
    ("Программист", "programmer"),
    ("Композитор", "composer"),
]
IFWIKI_IGNORE_ROLES = ["Категория"]

IFWIKI_COMPETITIONS = {
    "Конкурс": "{_1}",
    "ЛОК": "ЛОК-{_1}",
    "ЗОК": "ЗОК-{_1}",
    "КРИЛ": "КРИЛ-{_1}",
    "goldhamster": "Золотой Хомяк {_1}",
    "qspcompo": "QSP-Compo {_1}",
    "Проект 31": "Проект 31",
    "Ludum Dare": "Ludum Dare {_1}",
}

IFWIKI_IGNORE = ["ЗаглушкаТекста", "ЗаглушкаСсылок"]

GAMEINFO_IGNORE = ["ширинаобложки", "высотаобложки"]


class WikiAuthorParsingContext:
    def __init__(self, name, url):
        self.name = name
        self.url = url
        self.urls = [CategorizeAuthorUrl(url)]
        self.title = "(no title)"

    def AddUrl(self, url, desc="", category=None, base=None):
        self.urls.append(CategorizeAuthorUrl(url, desc, category, base))

    def ProcessLink(self, text):
        m = IFWIKI_LINK_INTERNALS_PARSE.match(text)
        if not m:
            return text  # Internal link without a category.
        role = m.group(1)
        name = m.group(2)
        typ = m.group(3)
        display_name = m.group(4)

        if role in ["Медиа", "Media", "Изображение", "Image"]:
            self.AddUrl(
                "/files/" + WikiQuote(name),
                display_name,
                "avatar" if typ == "thumb" else "download_direct",
                self.url,
            )
        elif role:
            logger.warning(f"Unknown role {role}")

        if display_name:
            return display_name
        if role:
            return name
        return name


class WikiParsingContext:
    def __init__(self, game_name, url):
        self.title = game_name
        self.release_date = None
        self.authors = []
        self.tags = []
        self.urls = [CategorizeUrl(url)]
        self.url = url

    def AddUrl(self, url, desc="", category=None, base=None):
        self.urls.append(CategorizeUrl(url, desc, category, base))

    def ProcessLink(self, text, default_role=None):
        m = IFWIKI_LINK_INTERNALS_PARSE.match(text)
        if not m:
            return text  # Internal link without a category.
        role = m.group(1)
        name = m.group(2)
        # typ = m.group(3)
        display_name = m.group(4)

        if role in IFWIKI_IGNORE_ROLES:
            return ""

        for r, t in IFWIKI_ROLES:
            if r == role:
                self.authors.append({
                    "role_slug": t,
                    "name": display_name or name,
                    "url": f"http://ifwiki.ru/{WikiQuote(name)}",
                    "urldesc": "Страница автора на ifwiki",
                })
                break
        else:
            if role in ["Медиа", "Media", "Изображение", "Image"]:
                self.AddUrl(
                    "/files/" + WikiQuote(name), display_name, base=self.url
                )
            elif role in ["Изображение"]:
                self.AddUrl(
                    "/files/" + WikiQuote(name),
                    display_name,
                    "screenshot",
                    self.url,
                )
            elif role == "Тема":
                self.tags.append({"cat_slug": "tag", "tag": name})
            elif role == "ifwiki-en":
                self.AddUrl(
                    "http://ifwiki.org/index.php/" + WikiQuote(name),
                    display_name,
                    "game_page",
                )
            elif role:
                logger.warning(f"Unknown role {role}")
                # self.authors.append({'role_slug': 'member', 'name': name})
            elif default_role:
                self.authors.append({
                    "role_slug": default_role,
                    "name": name,
                })
            elif ALLOW_INTERNAL_LINKS:
                self.AddUrl(
                    f"http://ifwiki.ru/{WikiQuote(name)}",
                    display_name or name,
                )
        if display_name:
            return display_name
        if role:
            return f"{role}:{name}"
        return name

    def ProcessGameinfo(self, params):
        """Process game info template parameters elegantly."""

        def add_tag(cat_slug, tag):
            self.tags.append({"cat_slug": cat_slug, "tag": tag})

        def parse_date(date_str):
            try:
                return datetime.datetime.strptime(date_str, "%d.%m.%Y").date()
            except ValueError:
                return None  # TODO: Support incomplete dates

        handlers = {
            "автор": lambda v: [
                self.ProcessLink(m.group(1))
                for m in IFWIKI_LINK_PARSE.finditer(v)
            ],
            "название": lambda v: setattr(self, "title", v),
            "вышла": lambda v: setattr(self, "release_date", parse_date(v)),
            "платформа": lambda v: add_tag("platform", v),
            "язык": lambda v: add_tag("language", v),
            "темы": lambda v: [
                add_tag("tag", t.strip()) for t in v.split(",") if t.strip()
            ],
            "обложка": lambda v: self.AddUrl(
                f"/files/{WikiQuote(v)}", "Обложка", "poster", self.url
            ),
            "IFID": lambda v: add_tag("ifid", v),
        }

        for k, v in params.items():
            if k in handlers:
                handlers[k](v)
            elif k in ["1", "2"] and not v.strip():
                continue
            elif k in GAMEINFO_IGNORE:
                continue
            else:
                logger.warning(f"Unknown gameinfo tag: {k} {v}")

    def DispatchTemplate(self, name, params):
        """Dispatch template processing with elegant handlers."""

        def add_tag(cat_slug, tag, tag_slug=None):
            tag_dict = {"cat_slug": cat_slug, "tag": tag}
            if tag_slug:
                tag_dict["tag_slug"] = tag_slug
            self.tags.append(tag_dict)

        def handle_competition():
            # Add numbered parameters with underscore prefix
            p = {
                **params,
                **{f"_{k}": v for k, v in params.items() if k[0].isdigit()},
            }
            add_tag("competition", IFWIKI_COMPETITIONS[name].format(**p))
            return ""

        def handle_link():
            self.AddUrl(params["на"], desc=params.get("1"))
            if "архив" in params:
                self.AddUrl(params["архив"])
            return f"[{params['на']} {params.get('1') or 'ссылка'}]"

        # Simple template handlers
        simple_handlers = {
            "PAGENAME": lambda: self.title,
            "game info": lambda: (self.ProcessGameinfo(params), "")[1],
            "Избранная игра": lambda: (add_tag("", "", "ifwiki_featured"), "")[
                1
            ],
            "РИЛФайл": lambda: (
                self.AddUrl(params["1"]),
                f"[{params['1']} Ссылка на РилАрхив]",
            )[1],
            "Ссылка": handle_link,
            "Тема": lambda: (add_tag("tag", params["1"]), "")[1],
            "ns:6": lambda: "Media",
            "URQStead": lambda: (
                self.AddUrl(params["1"], "Игра на URQ-модуле INSTEAD"),
                "",
            )[1],
        }

        if name in simple_handlers:
            return simple_handlers[name]()
        elif name in IFWIKI_COMPETITIONS:
            return handle_competition()
        elif name in IFWIKI_IGNORE:
            return ""
        else:
            logger.warning(f"Unknown template: {name} {params}")
            return ""


def process_wikitext_for_game(wikicode, context):
    """Process mwparserfromhell wikicode and convert to markdown-like text."""

    def extract_template_params(template):
        """Extract parameters from a template with nested processing."""
        params = {}

        for param in template.params:
            key = str(param.name).strip()
            value = str(param.value).strip()

            # Process nested templates (like {{PAGENAME}})
            if value == "{{PAGENAME}}":
                value = unquote(context.url.split("/")[-1]).replace("_", " ")

            if key:
                params[key] = value
            elif value:
                params[str(len(params) + 1)] = value

        return params

    # Process templates via string replacement for reliability
    text = str(wikicode)
    template_replacements = {}

    for template in wikicode.filter_templates():
        template_name = str(template.name).strip()
        template_str = str(template)
        params = extract_template_params(template)

        if template_name == "game info":
            context.ProcessGameinfo(params)
            template_replacements[template_str] = ""
        else:
            template_result = context.DispatchTemplate(template_name, params)
            template_replacements[template_str] = template_result or ""

    # Apply template replacements and convert to markdown
    for template_str, replacement in template_replacements.items():
        text = text.replace(template_str, replacement)

    return convert_wikitext_to_markdown(text, context)


def process_wikitext_for_author(wikicode, context):
    """Process mwparserfromhell wikicode and convert to markdown."""
    # Convert the wikitext to markdown
    text = str(wikicode)
    text = convert_wikitext_to_markdown(text, context)

    return text


def convert_wikitext_to_markdown(text, context):
    """Convert MediaWiki markup to markdown-like format."""
    if not text or not text.strip():
        return ""

    # Convert bold markup
    text = re.sub(r"'''(.*?)'''", r"**\1**", text)

    # Convert italic markup
    text = re.sub(r"''(.*?)''", r"_\1_", text)

    # Convert headings (note the order - longest first to avoid conflicts)
    text = re.sub(
        r"^======\s*(.*?)\s*======", r"###### \1", text, flags=re.MULTILINE
    )
    text = re.sub(
        r"^=====\s*(.*?)\s*=====", r"##### \1", text, flags=re.MULTILINE
    )
    text = re.sub(
        r"^====\s*(.*?)\s*====", r"#### \1", text, flags=re.MULTILINE
    )
    text = re.sub(r"^===\s*(.*?)\s*===", r"### \1", text, flags=re.MULTILINE)
    text = re.sub(r"^==\s*(.*?)\s*==", r"## \1", text, flags=re.MULTILINE)
    text = re.sub(r"^=\s*(.*?)\s*=", r"# \1", text, flags=re.MULTILINE)

    # Convert lists (note: # in MediaWiki means numbered list, not heading)
    text = re.sub(r"^\*\s+", r"* ", text, flags=re.MULTILINE)
    text = re.sub(r"^#\s+", r"1. ", text, flags=re.MULTILINE)

    # Convert internal links
    def replace_internal_link(match):
        link_content = match.group(1)
        # Process the link through context
        processed = context.ProcessLink(link_content)
        return f"**{processed}**"

    text = re.sub(r"\[\[(.*?)\]\]", replace_internal_link, text)

    # Convert external links
    def replace_external_link(match):
        url = match.group(1)
        if len(match.groups()) > 1 and match.group(2):
            desc = match.group(2).strip()
            context.AddUrl(url, desc)
            return f"[{desc}]({url})"
        else:
            context.AddUrl(url)
            return f"<{url}>"

    text = re.sub(r"\[([^\s\]]+)\s+([^\]]+)\]", replace_external_link, text)
    text = re.sub(r"\[([^\s\]]+)\]", replace_external_link, text)

    # Remove category links
    text = re.sub(r"\[\[Категория:.*?\]\]", "", text)

    # Convert horizontal rules
    text = re.sub(r"^----+", r"===", text, flags=re.MULTILINE)

    # Clean up extra whitespace but preserve paragraph breaks
    text = re.sub(r"\n\n+", "\n\n", text)
    text = text.strip()

    return text
