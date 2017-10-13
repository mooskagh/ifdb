from .tools import CategorizeUrl
from core.crawler import FetchUrlToString
from logging import getLogger
from mediawiki_parser import wikitextParser, preprocessorParser, apostrophes
from pijnu.library.node import Nodes
from urllib.parse import unquote, quote
import datetime
import json
import re
import time

logger = getLogger('crawler')


class IfwikiImporter:
    def Match(self, url):
        return IFWIKI_URL.match(url)

    def Import(self, url):
        return ImportFromIfwiki(url)

    def GetUrlCandidates(self):
        return GetUrlList()

    def GetDirtyUrls(self, age_minutes=60 * 14):
        return GetDirtyUrls(age_minutes)


CATEGORY_STR = (
    r'ifwiki.ru/%D0%9A%D0%B0%D1%82%D0%B5%D0%B3%D0%BE%D1%80%D0%B8%D1%8F:')


def _batch(iterable, n=40):
    l = len(iterable)
    for ndx in range(0, l, n):
        yield iterable[ndx:min(ndx + n, l)]


def GetDirtyUrls(age_minutes):
    ids = set()
    r = json.loads(
        FetchUrlToString(
            r'http://ifwiki.ru/api.php?action=query&list=recentchanges&'
            r'rclimit=500&format=json&rcend=%d' % int(
                time.time() - 60 * age_minutes),
            use_cache=False))['query']['recentchanges']

    for x in r:
        ids.add(x['pageid'])

    res = []
    for batch in _batch(list(ids)):
        pageidlist = '|'.join(["%d" % x for x in batch if x != 0])
        if not pageidlist:
          continue
        r = json.loads(
            FetchUrlToString(
                r'http://ifwiki.ru/api.php?action=query&prop=info&format=json&'
                r'inprop=url&pageids=' + pageidlist,
                use_cache=False))
        for _, v in r['query']['pages'].items():
          if 'fullurl' in v:
            res.append(v['fullurl'])
    return res


def GetUrlList():
    keystart = ''
    ids = set()

    while True:
        r = json.loads(
            FetchUrlToString(
                r'http://ifwiki.ru/api.php?action=query&list=categorymembers&'
                r'cmtitle=%D0%9A%D0%B0%D1%82%D0%B5%D0%B3%D0%BE%D1%80%D0'
                r'%B8%D1%8F:%D0%98%D0%B3%D1%80%D1%8B&rawcontinue=1&'
                r'cmlimit=2000&format=json&cmsort=sortkey&'
                r'cmprop=ids|title|sortkey&cmstarthexsortkey=' + keystart,
                use_cache=False))
        res = r['query']['categorymembers']

        for x in res:
            ids.add(x['pageid'])

        if len(res) <= 300:
            break
        else:
            keystart = res[-1]['sortkey']

    res = []
    for batch in _batch(list(ids)):
        pageidlist = '|'.join(["%d" % x for x in batch])
        r = json.loads(
            FetchUrlToString(
                r'http://ifwiki.ru/api.php?action=query&prop=info&format=json&'
                r'inprop=url&pageids=' + pageidlist,
                use_cache=False))
        for _, v in r['query']['pages'].items():
            if CATEGORY_STR not in v['fullurl']:
                res.append(v['fullurl'])
    return res


def CapitalizeFirstLetter(x):
    return x[:1].upper() + x[1:]


def WikiQuote(name):
    return quote(CapitalizeFirstLetter(name.replace(' ', '_')))


def ImportFromIfwiki(url):
    m = IFWIKI_URL.match(url)

    try:
        fetch_url = '%s/index.php?title=%s&action=raw' % (m.group(1),
                                                          m.group(2))
        cont = FetchUrlToString(fetch_url) + '\n'
    except Exception as e:
        logger.exception("Error while importing [%s] from Ifwiki" % url)
        return {'error': 'Не открывается что-то этот URL.'}

    res = {'priority': 100}

    context = WikiParsingContext(unquote(m.group(2)).replace('_', ' '), url)

    preproc = preprocessorParser.make_parser(toolset_preproc(context))
    parser = wikitextParser.make_parser(toolset_wiki(context))

    try:
        pre_text = preproc.parse(cont)
        output = parser.parse(pre_text.leaves())
    except Exception as e:
        logger.exception('Error while parsing %s' % url)
        return {'error': 'Какая-то ошибка при парсинге. Надо сказать админам.'}

    res['title'] = context.title
    res['desc'] = output.leaves() + '\n\n_(описание взято с сайта ifwiki.ru)_'
    if context.release_date:
        res['release_date'] = context.release_date
    res['authors'] = context.authors
    res['tags'] = context.tags
    res['urls'] = context.urls

    return res


IFWIKI_URL = re.compile(r'(https?://ifwiki.ru)/([^/?]+)')
IFWIKI_LINK_PARSE = re.compile(r'\[\[(.*?)\]\]')
IFWIKI_LINK_INTERNALS_PARSE = re.compile(
    r'^(?:([^:\]|]*)::?)?([^:\]|]+)(?:\|([^\]|]+))??(?:\|([^\]|]+))?$')

IFWIKI_ROLES = [
    ('автор', 'author'),
    ('Автор', 'author'),
    ('ifwiki-en', 'author'),
    ('Переводчик', 'translator'),
    ('Персонаж', 'character'),
    ('Тестировщик', 'tester'),
    ('Участник', 'member'),
    ('Иллюстратор', 'artist'),
    ('Программист', 'programmer'),
    ('Композитор', 'composer'),
]
IFWIKI_IGNORE_ROLES = ['Категория']

IFWIKI_COMPETITIONS = {
    'Конкурс': '{_1}',
    'ЛОК': 'ЛОК-{_1}',
    'ЗОК': 'ЗОК-{_1}',
    'КРИЛ': 'КРИЛ-{_1}',
    'goldhamster': 'Золотой Хомяк {_1}',
    'qspcompo': 'QSP-Compo {_1}',
    'Проект 31': 'Проект 31',
    'Ludum Dare': 'Ludum Dare {_1}',
}

IFWIKI_IGNORE = ['ЗаглушкаТекста', 'ЗаглушкаСсылок']

GAMEINFO_IGNORE = ['ширинаобложки', 'высотаобложки']


class WikiParsingContext:
    def __init__(self, game_name, url):
        self.title = game_name
        self.release_date = None
        self.authors = []
        self.tags = []
        self.urls = [CategorizeUrl(url)]
        self.url = url

    def AddUrl(self, url, desc='', category=None, base=None):
        self.urls.append(CategorizeUrl(url, desc, category, base))

    def ProcessLink(self, text, default_role='member'):
        m = IFWIKI_LINK_INTERNALS_PARSE.match(text)
        if not m:
            return text  # Internal link without a category.
        role = m.group(1)
        name = m.group(2)
        typ = m.group(3)
        display_name = m.group(4)

        if role in IFWIKI_IGNORE_ROLES:
            return ''

        for r, t in IFWIKI_ROLES:
            if r == role:
                self.authors.append({'role_slug': t, 'name': name})
                break
        else:
            if role in ['Медиа', 'Media']:
                self.AddUrl('/files/' + WikiQuote(name), display_name, 'poster'
                            if typ == 'thumb' else 'download_direct', self.url)
            elif role in ['Изображение']:
                self.AddUrl('/files/' + WikiQuote(name), display_name,
                            'screenshot', self.url)
            elif role == 'Тема':
                self.tags.append({'cat_slug': 'tag', 'tag': name})
            elif not role:
                self.authors.append({'role_slug': default_role, 'name': name})
            else:
                logger.warning('Unknown role %s' % role)
                self.authors.append({'role_slug': 'member', 'name': name})
        if display_name:
            return display_name
        if role:
            return "%s:%s" % (role, name)
        return name

    def ProcessGameinfo(self, params):
        for k, v in params.items():
            if k == 'автор':
                for m in IFWIKI_LINK_PARSE.finditer(v):
                    self.ProcessLink(m.group(1), 'author')
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
            elif k == 'язык':
                self.tags.append({'cat_slug': 'language', 'tag': v})
            elif k == 'темы':
                for t in [x.strip() for x in v.split(',')]:
                    self.tags.append({'cat_slug': 'tag', 'tag': t})
            elif k == 'обложка':
                self.AddUrl('/files/' + WikiQuote(v), 'Обложка', 'poster',
                            self.url)
            elif k == 'IFID':
                self.tags.append({'cat_slug': 'ifid', 'tag': v})
            elif k in ['1', '2'] and not v.strip():
                pass
            elif k in GAMEINFO_IGNORE:
                pass
            else:
                logger.warning('Unknown gameinfo tag: %s %s' % (k, v))

    def DispatchTemplate(self, name, params):
        if name == 'PAGENAME':
            return self.title
        if name == 'game info':
            self.ProcessGameinfo(params)
            return ''
        if name in IFWIKI_COMPETITIONS:
            p = {**params}
            for k, v in params.items():
                if k[0] in '0123456789':
                    p["_%s" % k] = v
            self.tags.append({
                'cat_slug': 'competition',
                'tag': (IFWIKI_COMPETITIONS[name].format(**p))
            })
            return ''
        if name == 'Избранная игра':
            self.tags.append({'tag_slug': 'ifwiki_featured'})
            return ''
        if name == 'РИЛФайл':
            self.AddUrl(params['1'])
            return '[%s Ссылка на РилАрхив]' % params['1']
        if name == 'Ссылка':
            self.AddUrl(params['на'], desc=params.get('1'))
            if 'архив' in params:
                self.AddUrl(params['архив'])
            return '[%s %s]' % (params['на'], params.get('1') or 'ссылка')
        if name == 'Тема':
            self.tags.append({'cat_slug': 'tag', 'tag': params['1']})
            return ''
        if name == 'ns:6':
            return 'Media'
        if name in IFWIKI_IGNORE:
            return ''
        logger.warning('Unknown template: %s %s' % (name, params))
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
        logger.warning('O url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))

    def substitute_template_parameter(node):
        logger.warning('N url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))

    def substitute_template(node):
        node.value = context.ParseTemplate(node)

    return locals()


def BuildLeaves(node):
    res = []
    for x in node.value:
        if isinstance(x.value, str):
            res.append(x.value)
        else:
            res.extend(BuildLeaves(x))
    return res


def toolset_wiki(context):
    style_tags = {
        'bold': '**',
        'bold_close': '**',
        'italic': '_',
        'italic_close': '_',
        'strike': '~~',
        'strike_close': '~~',
        'blockquote': '\n> ',
        'span': '',
    }

    style_tags_close = {
        'blockquote': '\n\n',
    }

    autoclose_tags = {
        'br': '\n',
    }

    def collapse_list(list):
        i = 0
        while i + 1 < len(list):
            if (list[i].tag == 'bullet_list_leaf'
                    and list[i + 1].tag == '@bullet_sub_list@'
                    or list[i].tag == 'number_list_leaf'
                    and list[i + 1].tag == '@number_sub_list@'
                    or list[i].tag == 'colon_list_leaf'
                    and list[i + 1].tag == '@colon_sub_list@'
                    or list[i].tag == 'semi_colon_list_leaf'
                    and list[i + 1].tag == '@semi_colon_sub_list@'):
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
        list_tags = [
            'bullet_list_leaf', 'number_list_leaf', 'colon_list_leaf',
            'semi_colon_list_leaf'
        ]
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
            if (list[i].tag == 'bullet_list_leaf'
                    or list[i].tag == '@bullet_sub_list@'):
                list[i].value = render_ul(
                    select_items(list, i, 'bullet_list_leaf', level), level)
            elif (list[i].tag == 'number_list_leaf'
                  or list[i].tag == '@number_sub_list@'):
                list[i].value = render_ol(
                    select_items(list, i, 'number_list_leaf', level), level)
            elif (list[i].tag == 'colon_list_leaf'
                  or list[i].tag == '@colon_sub_list@'):
                list[i].value = render_ul(
                    select_items(list, i, 'colon_list_leaf', level), level)
            elif (list[i].tag == 'semi_colon_list_leaf'
                  or list[i].tag == '@semi_colon_sub_list@'):
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
        if node.value[0].value in style_tags:
            node.value = style_tags[node.value[0].value]
        elif node.value[0].value in autoclose_tags:
            node.value = autoclose_tags[node.value[0].value]
        else:
            logger.warning('A url: %s, title:%s\n%s' % (context.url,
                                                        context.title, node))
            node.value = ''

    def render_tag_close(node):
        if node.value[0].value in style_tags_close:
            node.value = style_tags_close[node.value[0].value]
        else:
            render_tag_open(node)

    def render_tag_autoclose(node):
        if node.value[0].value in autoclose_tags:
            node.value = autoclose_tags[node.value[0].value]
        node.value = ''

    def render_attribute(node):
        logger.warning('B url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_table(node):
        logger.warning('C url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_table_line_break(node):
        logger.warning('D url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_table_header_cell(node):
        logger.warning('E url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_table_normal_cell(node):
        logger.warning('F url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_table_empty_cell(node):
        logger.warning('G url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_table_caption(node):
        logger.warning('H url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_preformatted(node):
        logger.warning('I url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_source(node):
        logger.warning('J url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_source_open(node):
        node.value = ''

    def render_source_text(node):
        logger.warning('K url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

    def render_hr(node):
        node.value = '\n===\n'

    def render_li(node):
        logger.warning('L url: %s, title:%s\n%s' % (context.url, context.title,
                                                    node))
        node.value = ''

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
        BuildLeaves(node)
        node.value = '**%s**' % (
            context.ProcessLink('|'.join(BuildLeaves(node))))

    def render_invalid(node):
        logger.warning('Invalid line, url: %s, title:%s' % (context.url,
                                                            context.title))
        node.value = ''

    return locals()
