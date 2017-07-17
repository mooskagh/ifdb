import json
from django.views.decorators.csrf import csrf_exempt
from django.core import signing
from django.core.signing import BadSignature
from django.utils import timezone
from django.http import HttpResponse
from logging import getLogger
from django.core.exceptions import SuspiciousOperation
from .models import Package, PackageSession
from django.contrib.auth import get_user_model

logger = getLogger('web')


@csrf_exempt
def logtime(request):
    if request.method != 'POST':
        raise SuspiciousOperation
    j = json.loads(request.body)

    session_id = signing.loads(j['session'], salt='core.packages.session')
    timesecs = j['time_secs']
    finish = j.get('finish', False)

    session = PackageSession.objects.get(pk=session_id)
    old_time = session.duration_secs or 0
    if timesecs < old_time:
        raise SuspiciousOperation

    if timesecs - old_time > (
            timezone.now() - session.last_update).seconds + 60:
        raise SuspiciousOperation

    if session.is_finished:
        raise SuspiciousOperation

    session.duration_secs = timesecs
    session.last_update = timezone.now()
    session.is_finished = finish
    session.save()

    return HttpResponse("A cat.")


@csrf_exempt
def fetchpackage(request):
    response = {}
    try:
        if request.method != 'POST':
            raise SuspiciousOperation
        j = json.loads(request.body)
        user = None
        package = None
        client = None
        if j.get('token'):
            x = signing.loads(j['token'], salt='core.packages.token')
            package = Package.objects.get(pk=x[0])
            if len(x) > 1:
                user = get_user_model().objects.get(pk=x[1])
        if not package and j.get('package'):
            package = Package.object.get(name=j['package'])
        if j.get('user'):
            x = signing.loads(j['user'], salt='core.packages.user')
            user = get_user_model().objects.get(pk=x)
        client = j.get('client')

        if not package:
            raise SuspiciousOperation

        response = BuildPackageResponse(user, package)

        if j.get('startsession'):
            response['session']['session'] = CreateNewSession(
                package, user, client)

    except BadSignature:
        response = {
            'error': "Не удалось удостовериться в подлинности запроса."
        }
    except:
        response = {'error': "Неведомая ошибка."}
        logger.exception("Exception in fetchpackage")
    return HttpResponse(json.dumps(response))


def CreateNewSession(package, user, client):
    session = PackageSession()
    session.package = package
    session.user = user
    session.client = client
    session.start_time = timezone.now()
    session.last_update = timezone.now()
    session.save()
    return signing.dumps(session.id, salt='core.packages.session')


def ExpandSelf(s, repl):
    if isinstance(s, str):
        return s.replace(r'{{self}}', "{{%s}}" % repl)
    if isinstance(s, list):
        res = []
        for x in s:
            res.append(ExpandSelf(x, repl))
        return res
    if isinstance(s, dict):
        res = {}
        for k, v in s.items():
            res[k] = ExpandSelf(v, repl)
        return res


def BuildPackageResponse(user, package):
    res = {
        'session': {},
        'shortcut': {
            'invocation': BuildPackageUserFingerprint(user, package.id),
            'package': package.name,
        },
        'runtime': {},
        'packages': [],
        'variables': {
            'this': '{{%s}}' % package.name,
        },
    }

    if user:
        res['session']['user'] = signing.dumps(
            user.id, salt='core.packages.user')

    if package.game:
        res['shortcut']['name'] = package.game.title

    todo = set([package])
    done = set()

    while todo:
        x = todo.pop()
        done.add(x.name)
        version = x.packageversion_set.order_by('-version')[0]
        j = json.loads(version.metadata_json)
        res['packages'].append({
            'package': x.name,
            'version': version.version,
            'md5': version.md5hash,
        })
        runtime = j.get('runtime', {})
        for z in ['chdir', 'execute']:
            if z in runtime and runtime[z] and z not in res['runtime']:
                res['runtime'][z] = ExpandSelf(runtime[z], x.name)
        for k, v in j.get('variables', {}).items():
            if k not in res['variables']:
                res['variables'][k] = ExpandSelf(v, x.name)
        for y in j.get('dependencies', []):
            if y['package'] in done:
                continue
            todo.add(Package.objects.get(name=y['package']))
    return res


def BuildPackageUserFingerprint(user, package):
    x = [package]
    if user:
        x.append(user.id)
    return signing.dumps(x, salt='core.packages.token')


"""
    res = {
        'session': {
            'user': None,
            'session': None,
        },
        'runtime': {
            'chdir': None,
            'execute': None,
        },
        'shortcut': {
            'invocation': BuildPackageUserFingerprint(user, package),
            'name': None,
            'icon': None,
        },
        'packages': [],  # {'package', 'version', 'md5'}
    }

    metadata = {
        'dependencies': [
            {'package': 'fireurq', 'min-vers...'}
        ],
        'runtime': {
            'chdir': 'self',
            'execute': '{{fireurq} -o sdfsdf'
        },
        'variables': {
            'game': 'sdfsdfsd',
        }
    }




    Token   string `json:"token,omitempty"`
    Package string `json:"package,omitempty"`  -- name
    User    string `json:"user,omitempty"`  -- token
> Request:
  game: "hash-of-user-and-game"
  user: hash_of_user
  client: unique client id
  packages: comma-separated (os-win32)


Response   - to write near teh package
[Response]
error=text

[Session]  # not written to the file!
User=hash-of-user   # to write to config
Session=hash-of-session

[ShortCut]
Invocation=hash-of-user-and-game  # For next invocation
Title=sdfjksfsjkld
Icon=sdfjsdlfjsdlfj.exe,1

[Packages]
fireurq-2.2.2=34583045800ej708g0fg #  Without cab or prefix
....

[Runtime]
Run=game-package
ChDir=sdfsdfsdfsdfsdf
Execute=sdjfksdflsdkfjlk
"""