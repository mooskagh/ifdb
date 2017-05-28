from django.core.exceptions import PermissionDenied

EVERYONE_GROUP = '@all'
UNAUTH_GROUP = '@guest'
AUTH_GROUP = '@auth'
SUPERUSER_GROUP = '@admin'


class Permissioner:
    def __init__(self, user):
        self.is_admin = user.is_superuser
        self.tokens = set()
        self.tokens.add(EVERYONE_GROUP)
        if not user.is_authenticated:
            self.tokens.add(UNAUTH_GROUP)
            return
        self.tokens.add(AUTH_GROUP)
        if self.is_admin:
            self.tokens.add(SUPERUSER_GROUP)

        self.tokens.add(user.username)

        for g in user.groups.values_list('name', flat=True):
            self.tokens.add('@%s' % g)

    def __str__(self):
        return '%s(%s)' % ('#'
                           if self.is_admin else '$', ', '.join(self.tokens))

    def __call__(self, expr):
        if self.is_admin:
            return True
        valid_perms = set(expr.split(','))
        return bool(valid_perms & self.tokens)

    def Ensure(self, expr):
        if not self(expr):
            raise PermissionDenied


def perm_required(perm):
    def real_decorator(f):
        def middleware(request):
            request.perm.Ensure(f)
            return f(request)

        return middleware

    return real_decorator


def permissioner(get_response):
    def middleware(request):
        request.perm = Permissioner(request.user)
        return get_response(request)

    return middleware