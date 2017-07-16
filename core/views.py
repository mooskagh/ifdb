import json
from django.views.decorators.csrf import csrf_exempt
from django.core import signing
from django.core.signing import BadSignature
from django.http import HttpResponse
from logging import getLogger
from django.core.exceptions import SuspiciousOperation
from .models import Package
from django.contrib.auth import get_user_model

logger = getLogger('web')


@csrf_exempt
def fetchpackage(request):
    response = {}
    try:
        if request.method != 'POST':
            raise SuspiciousOperation
        j = json.loads(request.body)
        user = None
        package = None
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

    except BadSignature:
        response = {
            'error': "Не удалось удостовериться в подлинности запроса."
        }
    except:
        response = {'error': "Неведомая ошибка."}
        logger.exception("Exception in fetchpackage")
    return HttpResponse(json.dumps(response))


def BuildGameUserFingerprint(request, game):
    x = [game]
    if request.user.is_authenticated:
        x.append(request.user.id)
    return signing.dumps(x, salt='core.packages.token')


"""

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