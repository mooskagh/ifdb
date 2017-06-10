from .tools import FetchUrl, CategorizeUrl
from mediawiki_parser import wikitextParser, preprocessorParser, apostrophes
from pijnu.library.node import Nodes
from urllib.parse import unquote
import datetime
import re
import logging


class IfwikiImporter:
    def Match(self, url):
        return IFWIKI_URL.match(url)

    def Import(self, url):
        return ImportFromIfwiki(url)


def ImportFromIfwiki(url):
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
        logging.error('Error while parsing %s' % url)
        return {'error': 'Какая-то ошибка при парсинге. Надо сказать админам.'}

    res['title'] = context.title
    res['desc'] = output.leaves()
    res['header'] = '\n\n---\n**=== Описание с ifwiki ===**\n\n'
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

GAMEINFO_IGNORE = ['ширинаобложки', 'высотаобложки']


class WikiParsingContext:
    def __init__(self, game_name, url):
        self.title = game_name
        self.release_date = None
        self.authors = []
        self.tags = []
        self.urls = [CategorizeUrl(url)]
        self.url = url

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
            logging.error('Unknown role %s' % role)
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
            elif k == 'обложка':
                self.urls.append({'urlcat_slug': 'poster',
                                  'description': 'Обложка',
                                  'url': 'http://ifwiki.ru/files/%s' % v})
            elif k == 'IFID':
                self.tags.append({'cat_slug': 'ifid', 'tag': v})
            elif k == '1' and not v.strip():
                pass
            elif k in GAMEINFO_IGNORE:
                pass
            else:
                logging.error('Unknown gameinfo tag: %s %s' % (k, v))

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
        if name == 'Тема':
            self.tags.append({'cat_slug': 'genre', 'tag': params['1']})
            return ''
        logging.error('Unknown template: %s %s' % (name, params))
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
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))

    def substitute_template_parameter(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))

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

    autoclose_tags = {'br': '\n', }

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
        if node.value[0].value in style_tags:
            node.value = style_tags[node.value[0].value]
        elif node.value[0].value in autoclose_tags:
            node.value = autoclose_tags[node.value[0].value]
        else:
            logging.error('url: %s, title:%s\n%s' %
                          (context.url, context.title, node.treeView()))
            node.value = ''

    def render_tag_close(node):
        render_tag_open(node)

    def render_tag_autoclose(node):
        if node.value[0].value in autoclose_tags:
            node.value = autoclose_tags[node.value[0].value]
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_attribute(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_table(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_table_line_break(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_table_header_cell(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_table_normal_cell(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_table_empty_cell(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_table_caption(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_preformatted(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_source(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_source_open(node):
        node.value = ''

    def render_source_text(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    def render_hr(node):
        node.value = '\n===\n'

    def render_li(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
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
        node.value = '**%s**' % (
            context.ProcessLink('|'.join([x.leaf() for x in node.value])))

    def render_invalid(node):
        logging.error('url: %s, title:%s\n%s' %
                      (context.url, context.title, node.treeView()))
        node.value = ''

    return locals()
