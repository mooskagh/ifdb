import json
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from logging import getLogger

logger = getLogger('web')


@csrf_exempt
def fetchpackage(request):
    response = {}
    try:
        if request.method == 'POST':
            print('Raw Data: "%s"' % request.body)
    except:
        logger.exception()
    return HttpResponse(json.dumps(response))


"""

    Token   string `json:"token,omitempty"`
    Package string `json:"package,omitempty"`
    User    string `json:"user,omitempty"`
    Client  string `json:"client,omitempty"`
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