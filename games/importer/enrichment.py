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


class CloneUrl(ActionBase):
    def __init__(self, fr, to):
        self.fr = fr
        self.to = to

    def Apply(self, game):
        urls = set()
        for x in game.setdefault('urls', []):
            if x['urlcat_slug'] == self.fr:
                urls.add(x['url'])
        for x in urls:
            game['urls'].append({
                'urlcat_slug': self.to,
                'description': 'Запустить в UrqW',
                'url': x
            })


class Enricher:
    def __init__(self):
        self.rules = []

    def AddRule(self, rule, action):
        self.rules.append((rule, action))

    def Enrich(self, game):
        for rule, action in self.rules:
            if rule.Match(game):
                action.Apply(game)


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
        'ярил', ),
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
        'квестер', ),
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
        'квестер', ),
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
        'ripurq', ),
    AddTag('os_win'))
enricher.AddRule(
    HasTag('platform', 'r?tads.*', 'r?inform.*'),
    AddTag('os_linux', 'os_macos'))
enricher.AddRule(HasTag('platform', 'dosurq'), AddTag('os_dos'))
enricher.AddRule(
    And(HasTag('platform', 'qsp'), HasUrlCategory('play_online')),
    AddTag('os_web'))
enricher.AddRule(
    And(
        Or(
            HasTag('platform', '.*urq.*'),
            IsFromSite('game_page', 'urq.plut.info')),
        Not(HasTag('platform', 'fireurq'))),
    CloneUrl('download_direct', 'play_in_interpreter'))