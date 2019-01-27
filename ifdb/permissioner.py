# Syntax:
#   @group
#   [user id]
#   (func)

from django.core.exceptions import PermissionDenied
from django.core.cache import caches
import dns.resolver

EVERYONE_GROUP = '@all'
UNAUTH_GROUP = '@guest'
AUTH_GROUP = '@auth'
SUPERUSER_GROUP = '@admin'
NOTOR_GROUP = '@notor'
TOR_GROUP = '@tor'
CRAWLER_GROUP = '@crawler'

# Add groups to the right if it's to the left.
EXPAND_GROUPS = [
    ['@admin', '@moder', '@gardener'],
]

GROUP_ALIAS = {
    'game_view': '@all',
    'game_edit': '(a @auth (n @ban))',
    'game_comment': '(a @auth (n @ban))',  # '(a @notor (n @ban))',
    'game_delete': '@moder',
    'game_vote': '(a @auth (n @ban))',
    'personality_view': '@all',
    'personality_edit': '@moder',
}

CRAWLER_STRS = [
    'YandexBot', 'Googlebot', 'YandexMobileBot', 'MegaIndex.ru', 'Barkrowler',
    'DotBot', 'BLEXBot', 'MauiBot', 'AhrefsBot', 'Mail.RU_Bot', 'SemrushBot',
    'bingbot', 'Twitterbot', 'Discordbot', 'MJ12bot', 'CCBot'
]


def IsCrawler(request):
    useragent = request.META.get('HTTP_USER_AGENT', '')
    for x in CRAWLER_STRS:
        if x in useragent:
            return True
    return False


def IsTor(request):
    ip = None
    try:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        m = caches['tor-ips'].get(ip)
        if m is not None:
            return m

        addr_to_query = (
            '%s.%s.%s.%s.443.192.32.76.45.ip-port.exitlist.torproject.org' %
            tuple(reversed(ip.split('.'))))

        for x in dns.resolver.query(addr_to_query):
            if str(x) == '127.0.0.2':
                caches['tor-ips'].set(ip, True)
                return True
    except:
        pass

    if ip:
        caches['tor-ips'].set(ip, False)
    return False


def parse_sexp(s):
    res = [[]]
    token = ''
    for c in s:
        if c in '() ':
            if token:
                res[-1].append(token)
            token = ''
        else:
            token += c
            continue

        if c == '(':
            res.append([])
        elif c == ')':
            x = res.pop()
            res[-1].append(x)

    if token:
        res[-1].append(token)

    if len(res) != 1:
        raise ValueError(s)

    return res[0]


class Permissioner:
    def __init__(self, request):
        user = request.user
        self.tokens = set()
        self.tokens.add(EVERYONE_GROUP)
        if IsTor(request):
            self.tokens.add(TOR_GROUP)
        else:
            self.tokens.add(NOTOR_GROUP)
        if IsCrawler(request):
            self.tokens.add(CRAWLER_GROUP)

        if not user.is_authenticated:
            self.tokens.add(UNAUTH_GROUP)
            return
        self.tokens.add(AUTH_GROUP)
        if user.is_superuser:
            self.tokens.add(SUPERUSER_GROUP)
        self.tokens.add('[%d]' % user.id)
        for g in user.groups.values_list('name', flat=True):
            self.tokens.add('@%s' % g)

        for group in EXPAND_GROUPS:
            expand = False
            for g in group:
                if expand:
                    self.tokens.add(g)
                elif g in self.tokens:
                    expand = True

    def __str__(self):
        return '%s(%s)' % ('#' if SUPERUSER_GROUP in self.tokens else '$',
                           ', '.join(self.tokens))

    def Eval(self, x):
        if isinstance(x, str):
            return x in self.tokens
        if x[0] in ['or', 'o']:
            for y in x[1:]:
                if self.Eval(y):
                    return True
            return False
        if x[0] in ['and', 'a']:
            for y in x[1:]:
                if not self.Eval(y):
                    return False
            return True
        if x[0] in ['not', 'n']:
            if len(x) != 2:
                raise ValueError(x)
            return not self.Eval(x[1])
        if x[0] == 'alias':
            if len(x) != 2:
                raise ValueError(x)
            return self.__call__(GROUP_ALIAS[x[1]])
        raise ValueError(repr(x))

    def __call__(self, expr):
        p = parse_sexp(expr)
        if len(p) != 1:
            raise ValueError(expr)
        return self.Eval(p[0])

        valid_perms = set(expr.split(','))
        return bool(valid_perms & self.tokens)

    def Ensure(self, expr):
        if not self(expr):
            raise PermissionDenied


def perm_required(perm):
    def real_decorator(f):
        def middleware(request):
            request.perm.Ensure(perm)
            return f(request)

        return middleware

    return real_decorator


def permissioner(get_response):
    def middleware(request):
        request.perm = Permissioner(request)
        return get_response(request)

    return middleware
