import re
from urllib.parse import urlsplit


class RuleBase:
    pass


class HasTag(RuleBase):
    def __init__(self, cat, *tag_re):
        self.cat = cat
        self.tags = [re.compile(x) for x in tag_re]

    def Match(self, game):
        if 'tags' not in game:
            return False
        for x in game['tags']:
            if x.get('cat_slug') != self.cat:
                continue
            for y in self.tags:
                if y.match(x.get('tag', '').lower()):
                    return True
        return False


class IsFromSite(RuleBase):
    def __init__(self, cat, site):
        self.cat = cat
        self.site = site

    def Match(self, game):
        if 'urls' not in game:
            return False

        for x in game['urls']:
            if x['urlcat_slug'] == self.cat:
                if self.site == urlsplit(x['url']).netloc:
                    return True

        return False


class HasUrlCategory(RuleBase):
    def __init__(self, cat):
        self.cat = cat

    def Match(self, game):
        if 'urls' not in game:
            return False

        for x in game['urls']:
            if x['urlcat_slug'] == self.cat:
                return True

        return False


class And(RuleBase):
    def __init__(self, *subrules):
        self.subrules = subrules

    def Match(self, game):
        for x in self.subrules:
            if not x.Match(game):
                return False
        return True


class Or(RuleBase):
    def __init__(self, *subrules):
        self.subrules = subrules

    def Match(self, game):
        for x in self.subrules:
            if x.Match(game):
                return True
        return False


class Not(RuleBase):
    def __init__(self, subrule):
        self.subrule = subrule

    def Match(self, game):
        return not self.subrule.Match(game)


class ActionBase:
    pass


class AddTag(ActionBase):
    def __init__(self, *vals):
        self.vals = vals

    def Apply(self, game):
        vals_to_apply = set(self.vals)
        for x in game.setdefault('tags', []):
            if 'tag_slug' in x:
                vals_to_apply.discard(x['tag_slug'])
        for x in vals_to_apply:
            game['tags'].append({'tag_slug': x})


class AddRawTag(ActionBase):
    def __init__(self, category, tag):
        self.category = category
        self.tag = tag

    def Apply(self, game):
        game.setdefault('tags', []).append({
            'cat_slug': self.category,
            'tag': self.tag
        })


class CloneUrl(ActionBase):
    def __init__(self, fr, to, desc):
        self.fr = fr
        self.to = to
        self.desc = desc

    def Apply(self, game):
        urls = {}
        for x in game.setdefault('urls', []):
            if x['urlcat_slug'] == self.fr:
                urls[x['url']] = self.desc.format(**x)
        for url, desc in urls.items():
            game['urls'].append({
                'urlcat_slug': self.to,
                'description': desc,
                'url': url,
            })


class Enricher:
    def __init__(self):
        self.rules = []
        self.funcs = []

    def AddRule(self, rule, action):
        self.rules.append((rule, action))

    def AddFunction(self, f):
        self.funcs.append(f)

    def Enrich(self, game):
        for rule, action in self.rules:
            if rule.Match(game):
                action.Apply(game)
        for f in self.funcs:
            f(game)


enricher = Enricher()
enricher.AddRule(
    HasTag(
        'platform',
        # List
        '6days.*',
        'adrift',
        'r?inform.*',
        'r?tads.*',
        'tom 2',
        'ярил',
    ),
    AddTag('parser'))
enricher.AddRule(
    HasTag(
        'platform',
        # List
        '.*qsp',
        '.*urq( .*)?',
        'apero',
        'axma.*',
        'ink.*',
        'instead',
        'questbox',
        'tweebox',
        'twine',
        'аперо',
        'квестер',
    ),
    AddTag('menu'))
enricher.AddRule(
    HasTag(
        'platform',
        # List
        'aeroqsp',
        'apero',
        'axma.*',
        'r?inform.*',
        'tweebox',
        'twine',
        'urqw',
        'аперо',
        'квестер',
    ),
    AddTag('os_web'))
enricher.AddRule(
    HasTag(
        'platform',
        # List
        '.*qsp',
        'akurq.*',
        'fireurq',
        'r?inform.*',
        'r?tads.*',
        'ripurq',
    ),
    AddTag('os_win'))
enricher.AddRule(
    HasTag('platform', 'r?tads.*', 'r?inform.*'), AddTag(
        'os_linux', 'os_macos'))
enricher.AddRule(HasTag('platform', 'dosurq'), AddTag('os_dos'))
enricher.AddRule(
    And(HasTag('platform', 'qsp'), HasUrlCategory('play_online')),
    AddTag('os_web'))
# enricher.AddRule(
#     And(
#         Or(
#             HasTag('platform', '.*urq.*'),
#             IsFromSite('game_page', 'urq.plut.info')),
#         Not(HasTag('platform', 'fireurq'))),
#     CloneUrl('download_direct', 'play_in_interpreter',
#              'Открыть в UrqW: {description:.30}'))
enricher.AddRule(
    Or(
        HasTag('platform', '.*urq.*'), IsFromSite('game_page',
                                                  'urq.plut.info')),
    CloneUrl('download_direct', 'play_in_interpreter',
             'Открыть в UrqW: {description:.30}'))
enricher.AddRule(
    Not(HasTag('language', '.*')), AddRawTag('language', 'русский'))

tag_to_genre = {
    '18+': ('g_adult', True),
    'action': ('g_action', False),
    'horror': ('g_horror', False),
    'rpg': ('g_rpg', True),
    'боевик': ('g_action', True),
    'викторина': ('g_puzzle', False),
    'головоломка': ('g_puzzle', True),
    'головоломки': ('g_puzzle', True),
    'детектив': ('g_detective', True),
    'детская': ('g_kids', True),
    'детское': ('g_kids', True),
    'дистопия': ('g_dystopy', True),
    'доисторическое': ('g_historical', True),
    'дорожное приключение': ('g_adventure', True),
    'драма': ('g_drama', True),
    'историческое': ('g_historical', True),
    'казка': ('g_fairytale', True),
    'космос': ('g_scifi', False),
    'логическая': ('g_puzzle', True),
    'мистика': ('g_mystic', True),
    'містыка': ('g_mystic', True),
    'научная фантастика': ('g_scifi', False),
    'непонятное': ('g_experimental', False),
    'паззл': ('g_puzzle', True),
    'паззлы': ('g_puzzle', True),
    'пазл': ('g_puzzle', True),
    'пазлы': ('g_puzzle', True),
    'постапокалипсис': ('g_dystopy', False),
    'постапокалиптика': ('g_dystopy', False),
    'преступление': ('g_detective', False),
    'приключение': ('g_adventure', True),
    'приключения': ('g_adventure', True),
    'рамантыка': ('g_romance', True),
    'ребус': ('g_puzzle', False),
    'роботы': ('g_scifi', False),
    'романтика': ('g_romance', True),
    'рпг': ('g_rpg', True),
    'секс': ('g_adult', False),
    'симулятор': ('g_simulation', True),
    'сказка': ('g_fairytale', True),
    'сюр': ('g_experimental', False),
    'сюрреализм': ('g_experimental', False),
    'триллер': ('g_horror', False),
    'убийство': ('g_detective', False),
    'ужас': ('g_horror', True),
    'ужасы': ('g_horror', True),
    'фантастика': ('g_scifi', True),
    'фанфик': ('g_fanfic', True),
    'фентези': ('g_fantasy', True),
    'фэнтези': ('g_fantasy', True),
    'хоррор': ('g_horror', False),
    'черный юмор': ('g_humor', False),
    'чёрный юмор': ('g_humor', False),
    'чёрти что': ('g_experimental', False),
    'шутер': ('g_action', False),
    'экспериментальное': ('g_experimental', True),
    'экшн': ('g_action', False),
    'эротика': ('g_adult', False),
    'юмор': ('g_humor', True),
}


def LowerCaseTags(game):
    for x in game.get('tags', []):
        if x.get('cat_slug') == 'tag' and 'tag' in x:
            x['tag'] = x['tag'].lower()


def TagsToGenre(game):
    res = []
    for x in game.get('tags', []):
        if x.get('cat_slug') != 'tag':
            continue
        v = x.get('tag', '').lower()
        t2g = tag_to_genre.get(v)
        if t2g:
            if t2g[1]:
                x.clear()
                v = x
            else:
                v = {}
                res.append(v)
            v['cat_slug'] = 'genre'
            v['tag_slug'] = t2g[0]
    if 'tags' in game:
        game['tags'].extend(res)


enricher.AddFunction(LowerCaseTags)
enricher.AddFunction(TagsToGenre)