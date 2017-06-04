from html import unescape
from html2text import HTML2Text
from mediawiki_parser import wikitextParser, preprocessorParser, apostrophes
# from mediawiki_parser.constants import html_entities
from pijnu.library.node import Nodes
from urllib.parse import urlparse, unquote, quote, urlunsplit, urlsplit
import datetime
import re
import urllib

# TODO log code when this is hit.
DEBG = False


def FetchUrl(url):
    url = quote(url.encode('utf-8'), safe='/+=&?%:@;!#$*()_-')
    print('Fetching: %s' % url)
    with urllib.request.urlopen(url) as response:
        return response.read().decode('utf-8')


MARKDOWN_SPECIAL_ESCAPED = re.compile(r'\\([\\\]\[()])')


def MdUnescape(str):
    return MARKDOWN_SPECIAL_ESCAPED.sub(r'\1', str)


def DispatchImport(url):
    if PLUT_URL.match(url):
        return ImportFromPlut(url)

    if IFWIKI_URL.match(url):
        return ImportFromIfWiki(url)

    return None


RE_WORD = re.compile('\w+')
MIN_SIMILARITY = 0.67


def SimilarEnough(w1, w2):
    s1 = set(RE_WORD.findall(w1.lower()))
    s2 = set(RE_WORD.findall(w2.lower()))
    if not s1:
        return False

    similarity = len(s1 & s2) / len(s1 | s2)
    return similarity > MIN_SIMILARITY


def HashizeUrl(url):
    url = quote(url.encode('utf-8'), safe='/+=&?%:;@!#$*()_-')
    purl = urlsplit(url, allow_fragments=False)
    return urlunsplit(('', purl[1], purl[2], purl[3], ''))


def Import(seed_url):
    urls_checked = set()
    urls_to_check = set([seed_url])
    res = []
    title = None

    s_urls = set()
    s_tags = set()
    s_auth = set()

    def MergeImport(y, x):
        for z in ['title', 'release_date']:
            if z not in y and z in x:
                y[z] = x[z]

        if 'desc' in x:
            if 'desc' in y:
                y['desc'] += '\n\n---\n\n'
            else:
                y['desc'] = ''
            y['desc'] += x['desc']

        for setz, field, extractor in [
            (s_urls, 'urls', lambda xx: HashizeUrl(xx['url'])),
            (s_tags, 'tags',
             lambda xx: (xx.get('tag_slug'), xx.get('tag'), xx.get('cat_slug'))
             ),
            (s_auth, 'authors',
             lambda v: (v.get('role_slug'), v.get('role_slug'), v.get('name'))
             ),
        ]:
            if field in x:
                if field not in y:
                    y[field] = []
                for z in x[field]:
                    if extractor(z) in setz:
                        continue
                    setz.add(extractor(z))
                    y[field].append(z)

    while urls_to_check:
        url = urls_to_check.pop()
        url_hash = HashizeUrl(url)
        if url_hash in urls_checked:
            continue
        urls_checked.add(url_hash)

        r = DispatchImport(url)

        append = False
        if 'title' in r:
            if title:
                if SimilarEnough(title, r['title']):
                    append = True
            else:
                title = r['title']
                append = True

        if append:
            res.append(r)
            if 'urls' in r:
                for x in r['urls']:
                    if x['urlcat_slug'] == 'game_page':
                        urls_to_check.add(x['url'])
    if not res:
        return {'error': 'Ссылка на неизвестный ресурс.'}

    res.sort(key=lambda x: x['priority'], reverse=True)

    r = {}
    for x in res:
        MergeImport(r, x)
    return r


def CategorizeUrl(url, desc='', category=None):
    purl = urlparse(url)
    cat_slug = 'unknown'
    if purl.hostname == 'ifwiki.ru':
        cat_slug = 'game_page'
        if not desc:
            desc = 'Страница на IfWiki'
        elif 'ifwiki' not in desc.lower():
            desc = desc + ' (IfWiki)'

    if purl.hostname == 'urq.plut.info':
        if '/files/' in purl.path:
            cat_slug = 'download_direct'
            if not desc:
                desc = 'Скачать с плута'
        else:
            cat_slug = 'game_page'
            if not desc:
                desc = 'Страница на плуте'
            elif 'plut' not in desc.lower() and 'плут' not in desc.lower():
                desc = desc + ' (плут)'

    if purl.hostname == 'yadi.sk':
        cat_slug = 'download_landing'

    if purl.hostname == 'rilarhiv.ru':
        cat_slug = 'download_direct'
        if not desc:
            desc = 'Скачать с РилАрхива'

    if purl.hostname == 'instead-games.ru':
        if '/download/' in purl.path:
            cat_slug = 'download_direct'
            if not desc:
                desc = 'Скачать с Инстеда'
        else:
            cat_slug = 'game_page'
            if not desc:
                desc = 'Страница на инстеде'

    if purl.hostname == 'instead.syscall.ru':
        if '/forum/' in purl.path:
            cat_slug = 'forum'
            if not desc:
                desc = 'Форум на инстеде'

    if purl.hostname == 'www.youtube.com' or purl.hostname == 'youtube.com':
        cat_slug = 'video'
        if not desc:
            desc = 'Видео игры'

    if category:
        cat_slug = category

    return {'urlcat_slug': cat_slug, 'description': desc, 'url': url}

# Schema:
# title: title
# desc: description, markdown-formatted
# release_date: release-date
# authors[]:
#   role_slug:
#   role: ...         (either role_slug or role is defined)
#   name: ...
# tags[]:
#   tag_slug  (doesn't need anything else
#   cat_slug
#   tag
# urls[]:
#   urlcat_slug
#   description
#   url
#
# Role slugs:
#   artist, author
# Tag slug:
#   in_dev, beta, released, demo
# Cat slug:
#   genre
#   platform
#   country
# Url slug:
#   game_page (ifwiki)
#   download_direct
#   download_landing
#   unknown

##############################################################################
# PLUT
##############################################################################

PLUT_URL = re.compile(r'https?://urq.plut.info/(?:node/\d+|[^/]+)')
PLUT_TITLE = re.compile(r'<h1 class="title">(.*?)</h1>')
PLUT_DESC = re.compile(
    r'<div class="field field-name-body field-type-text-with-summary '
    r'field-label-hidden"><div class="field-items">(.*?)</div>', re.DOTALL)

PLUT_RELEASE = re.compile(
    r'<div id="block-system-main".*?'
    r'<span property="dc:date dc:created" content="(\d\d\d\d-\d\d-\d\d)',
    re.DOTALL)

PLUT_FIELD = re.compile(r'<div class="field-label">([^<:]+).*?</div>.*?</div>',
                        re.DOTALL)

PLUT_FIELD_ITEM = re.compile(r'<a [^>]+>([^<]+)</a>')
PLUT_DOWNLOAD_LINK = re.compile(
    r'<td><span class="file"><img class="file-icon" [^>]+> '
    r'<a href="([^"]+)"[^>]*>([^<]*)</a>')

MARKDOWN_LINK = re.compile(r'\[([^\]]*)\]\((.*?[^\\])\)|<([^> ]+)>')


def ParseFields(html):
    res = []
    for m in PLUT_FIELD.finditer(html):
        for n in PLUT_FIELD_ITEM.finditer(m.group()):
            res.append([unescape(m.group(1)), unescape(n.group(1))])
    return res


def ImportFromPlut(url):
    try:
        html = FetchUrl(url)
    except:
        return {'error': 'Не открывается что-то этот URL.'}

    res = {'priority': 50}
    m = PLUT_TITLE.search(html)
    if not m:
        return {'error': 'Не найдена игра на странице'}
    res['title'] = unescape(m.group(1))

    m = PLUT_DESC.search(html)
    if m:
        tt = HTML2Text()
        tt.body_width = 0
        res['desc'] = tt.handle(m.group(1))

    m = PLUT_RELEASE.search(html)
    if m:
        res['release_date'] = datetime.datetime.strptime(
            m.group(1), "%Y-%m-%d").date()

    res['urls'] = [CategorizeUrl(url, '')]

    for m in PLUT_DOWNLOAD_LINK.finditer(html):
        url = m.group(1)
        desc = unescape(m.group(2))
        res['urls'].append(CategorizeUrl(url, desc))

    tags = []
    authors = []

    for cat, tag in ParseFields(html):
        if cat == 'Статус':
            if tag == 'ббета':
                tags.append({'tag_slug': 'beta'})
            elif tag == 'готовая':
                tags.append({'tag_slug': 'released'})
            elif tag == 'демо':
                tags.append({'tag_slug': 'demo'})
            elif tag == 'в разработке':
                tags.append({'tag_slug': 'in_dev'})
        elif cat == 'Платформа':
            tags.append({'cat_slug': 'platform', 'tag': tag})
        elif cat == 'Страна':
            tags.append({'cat_slug': 'country', 'tag': tag.capitalize()})
        elif cat == 'Жанр':
            tags.append({'cat_slug': 'genre', 'tag': tag.capitalize()})
        elif cat == 'Авторы':
            authors.append({'role_slug': 'author', 'name': tag})

    if tags:
        res['tags'] = tags
    if authors:
        res['authors'] = authors

    # if 'desc' in res. Parse the rest of links
    if 'desc' in res:
        for m in MARKDOWN_LINK.finditer(res['desc']):
            if m.group(3):
                x = CategorizeUrl(m.group(3))
            else:
                x = CategorizeUrl(
                    MdUnescape(m.group(2)), MdUnescape(m.group(1)))
            if x:
                res['urls'].append(x)

    return res

##############################################################################
# IfWiki
##############################################################################


def ImportFromIfWiki(url):
    m = IFWIKI_URL.match(url)

    try:
        fetch_url = '%s/index.php?title=%s&action=raw' % (m.group(1),
                                                          m.group(2))
        cont = FetchUrl(fetch_url) + '\n'
    except:
        return {'error': 'Не открывается что-то этот URL.'}

    res = {'priority': 100}

    context = WikiParsingContext(unquote(m.group(2)).replace('_', ' '), url)

    preproc = preprocessorParser.make_parser(toolset_preproc(context))
    parser = wikitextParser.make_parser(toolset_wiki(context))

    try:
        pre_text = preproc.parse(cont)
        output = parser.parse(pre_text.leaves())
    except:
        # TODO(crem)  log(error) that case.
        return {'error': 'Какая-то ошибка при парсинге. Надо сказать админам.'}

    res['title'] = context.title
    res['desc'] = output.leaves()
    if context.release_date:
        res['release_date'] = context.release_date
    if context.authors:
        res['authors'] = context.authors
    if context.tags:
        res['tags'] = context.tags
    if context.urls:
        res['urls'] = context.urls

    return res


IFWIKI_URL = re.compile(r'(https?://ifwiki.ru)/([^/:]+)')
IFWIKI_LINK_PARSE = re.compile(r'\[\[(.*?)\]\]')
IFWIKI_LINK_INTERNALS_PARSE = re.compile(
    r'([^:\]|]+)::?([^:\]|]+)(?:\|([^\]|]+))?')

IFWIKI_ROLES = [
    ('Автор', 'author'),
    ('ifwiki-en', 'author'),
    ('Переводчик', 'translator'),
    ('Персонаж', 'character'),
]
IFWIKI_IGNORE_ROLES = ['Категория']

IFWIKI_COMPETITIONS = {'Конкурс': '',
                       'ЛОК': 'ЛОК-',
                       'ЗОК': 'ЗОК-',
                       'КРИЛ': 'КРИЛ-',
                       'goldhamster': 'Золотой Хомяк ',
                       'qspcompo': 'QSP-Compo '}
IFWIKI_IGNORE = ['ЗаглушкаТекста', 'ЗаглушкаСсылок']


class WikiParsingContext:
    def __init__(self, game_name, url):
        self.title = game_name
        self.release_date = None
        self.authors = []
        self.tags = []
        self.urls = [CategorizeUrl(url)]

    def AddUrl(self, url, desc=''):
        self.urls.append(CategorizeUrl(url, desc))

    def ProcessLink(self, text):
        m = IFWIKI_LINK_INTERNALS_PARSE.match(text)
        if not m:
            return text  # Internal link without a category.
        role = m.group(1)
        name = m.group(2)
        display_name = m.group(3)

        if role in IFWIKI_IGNORE_ROLES:
            return ''

        for r, t in IFWIKI_ROLES:
            if r == role:
                self.authors.append({'role_slug': t, 'name': name})
                break
        else:
            # TODO log that
            self.authors.append({'role_slug': 'member', 'name': name})
        return display_name or name

    def ProcessGameinfo(self, params):
        for k, v in params.items():
            if k == 'автор':
                for m in IFWIKI_LINK_PARSE.finditer(v):
                    self.ProcessLink(m.group(1))
            elif k == 'название':
                self.title = v
            elif k == 'вышла':
                try:
                    self.release_date = datetime.datetime.strptime(
                        v, "%d.%m.%Y").date()
                except:
                    # TODO(crem) Support incomplete dates
                    pass
            elif k == 'платформа':
                self.tags.append({'cat_slug': 'platform', 'tag': v})
            elif k == 'темы':
                for t in [x.strip() for x in v.split(',')]:
                    self.tags.append({'cat_slug': 'genre', 'tag': t})
            # TODO else log

    def DispatchTemplate(self, name, params):
        if name == 'PAGENAME':
            return self.title
        if name == 'game info':
            self.ProcessGameinfo(params)
            return ''
        if name in IFWIKI_COMPETITIONS:
            self.tags.append({'cat_slug': 'competition',
                              'tag': '%s%s' %
                              (IFWIKI_COMPETITIONS[name], params['1'])})
            return ''
        if name == 'РИЛФайл':
            self.AddUrl(params['1'])
            return '[%s Ссылка на РилАрхив]' % params['1']
        if name in IFWIKI_IGNORE:
            return ''
        print('AAAAAAAAAAAAAAA', name, params)  # TODO(crem) Fail
        return ''

    def ParseTemplate(self, node):
        # TODO(crem) assert node.tag == 'template'
        page_name = node.value[0].leaf()

        params = {}
        count = 0
        if len(node.value) > 1:
            for param in node.value[1].value:
                if isinstance(param.value, str) or len(param.value) == 1:
                    count += 1
                    params['%s' % count] = param.leaf()
                else:
                    # TODO assert that
                    # parameter.value[0].tag == 'parameter_name' and \
                    # parameter.value[1].tag == 'parameter_value':
                    params[param.value[0].leaf()] = param.value[1].leaf()
        return self.DispatchTemplate(page_name, params)


def toolset_preproc(context):
    def substitute_named_entity(node):
        node.value = '&%s;' % node.leaf()

    def substitute_numbered_entity(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def substitute_template_parameter(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def substitute_template(node):
        node.value = context.ParseTemplate(node)

    return locals()


def toolset_wiki(context):
    style_tags = {'bold': '**',
                  'bold_close': '**',
                  'italic': '_',
                  'italic_close': '_',
                  'strike': '~~',
                  'strike_close': '~~'}

    def collapse_list(list):
        i = 0
        while i + 1 < len(list):
            if (list[i].tag == 'bullet_list_leaf' and
                    list[i + 1].tag == '@bullet_sub_list@' or
                    list[i].tag == 'number_list_leaf' and
                    list[i + 1].tag == '@number_sub_list@' or
                    list[i].tag == 'colon_list_leaf' and
                    list[i + 1].tag == '@colon_sub_list@' or
                    list[i].tag == 'semi_colon_list_leaf' and
                    list[i + 1].tag == '@semi_colon_sub_list@'):
                list[i].value.append(list[i + 1].value[0])
                list.pop(i + 1)
            else:
                i += 1
        for i in range(len(list)):
            if isinstance(list[i].value, Nodes):
                collapse_list(list[i].value)

    def content(node):
        return apostrophes.parse('%s' % node.leaf(), style_tags)

    def render_ul(list, level):
        indent = '  ' * level
        result = '\n'
        for i in range(len(list)):
            result += indent + '* ' + content(list[i]) + '\n'
        return result

    def render_ol(list, level):
        indent = '  ' * level
        result = '\n'
        for i in range(len(list)):
            result += indent + '%i. %s\n' % (i + 1, content(list[i]))
        return result

    def select_items(nodes, i, value, level):
        list_tags = ['bullet_list_leaf', 'number_list_leaf', 'colon_list_leaf',
                     'semi_colon_list_leaf']
        list_tags.remove(value)
        if isinstance(nodes[i].value, Nodes):
            render_lists(nodes[i].value, level + 1)
        items = [nodes[i]]
        while i + 1 < len(nodes) and nodes[i + 1].tag not in list_tags:
            if isinstance(nodes[i + 1].value, Nodes):
                render_lists(nodes[i + 1].value, level + 1)
            items.append(nodes.pop(i + 1))
        return items

    def render_lists(list, level):
        i = 0
        while i < len(list):
            if list[i].tag == 'bullet_list_leaf' or list[
                    i].tag == '@bullet_sub_list@':
                list[i].value = render_ul(
                    select_items(list, i, 'bullet_list_leaf', level), level)
            elif list[i].tag == 'number_list_leaf' or list[
                    i].tag == '@number_sub_list@':
                list[i].value = render_ol(
                    select_items(list, i, 'number_list_leaf', level), level)
            elif list[i].tag == 'colon_list_leaf' or list[
                    i].tag == '@colon_sub_list@':
                list[i].value = render_ul(
                    select_items(list, i, 'colon_list_leaf', level), level)
            elif list[i].tag == 'semi_colon_list_leaf' or list[
                    i].tag == '@semi_colon_sub_list@':
                list[i].value = render_ul(
                    select_items(list, i, 'semi_colon_list_leaf', level),
                    level)
            i += 1

    def render_title1(node):
        node.value = '# %s\n' % node.leaf()

    def render_title2(node):
        node.value = '## %s\n' % node.leaf()

    def render_title3(node):
        node.value = '### %s\n' % node.leaf()

    def render_title4(node):
        node.value = '#### %s\n' % node.leaf()

    def render_title5(node):
        node.value = '##### %s\n' % node.leaf()

    def render_title6(node):
        node.value = '######%s\n' % node.leaf()

    def render_raw_text(node):
        pass

    def render_paragraph(node):
        node.value = '%s\n\n' % node.leaf()

    def render_wikitext(node):
        pass

    def render_body(node):
        node.value = apostrophes.parse('%s' % node.leaves(), style_tags)

    def render_entity(node):
        node.value = '&%s;' % node.leaf()
        # value = '%s' % node.leaf()
        # if value in html_entities:
        #     node.value = '%s' % chr(html_entities[value])
        # else:
        #     node.value = '&%s;' % value

    def render_lt(node):
        node.value = '<'

    def render_gt(node):
        node.value = '>'

    def render_tag_open(node):
        node.value = style_tags[node.value[0].value]

    def render_tag_close(node):
        node.value = style_tags[node.value[0].value]

    def render_tag_autoclose(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_attribute(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_table(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_table_line_break(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_table_header_cell(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_table_normal_cell(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_table_empty_cell(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_table_caption(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_preformatted(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_source(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_source_open(node):
        node.value = ''

    def render_source_text(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_hr(node):
        node.value = '\n===\n'

    def render_li(node):
        if DEBG:
            input(node.treeView() + "\n>")

    def render_list(node):
        collapse_list(node.value)
        render_lists(node.value, 0)

    def render_url(node):
        context.AddUrl(node.leaf())
        node.value = '<%s>' % node.leaf()

    def render_external_link(node):
        url = node.value[0].leaf()
        desc = node.value[1].leaf() if len(node.value) > 1 else ''
        context.AddUrl(url, desc)
        if desc:
            node.value = '[%s](%s)' % (desc, url)
        else:
            node.value = '<%s>' % (url)

    def render_internal_link(node):
        node.value = '**%s**' % (
            context.ProcessLink('|'.join([x.leaf() for x in node.value])))

    def render_invalid(node):
        if DEBG:
            input(node.treeView() + "\n>")

    return locals()
