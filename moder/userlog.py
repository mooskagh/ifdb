from .models import UserLog
from django.utils import timezone
from games.tools import GetIpAddr
import json


def LogAction(request,
              action,
              *,
              is_mutation,
              obj=None,
              obj_type=None,
              obj_id=None,
              obj2=None,
              before=None,
              after=None):
    if request.perm('(o @crawler @nolog)'):
        return
    x = UserLog()
    if request.user.is_authenticated:
        x.user = request.user
    x.ip_addr = GetIpAddr(request)
    x.session = request.session.session_key
    x.timestamp = timezone.now()
    x.perm = str(request.perm)
    x.action = action
    x.useragent = request.META.get('HTTP_USER_AGENT')
    x.is_mutation = is_mutation
    if obj:
        obj_type = obj.__class__.__name__
        obj_id = obj.id
    x.obj_type = obj_type
    x.obj_id = obj_id
    if obj2:
        x.obj2_type = obj2.__class__.__name__
        x.obj2_id = obj2.id
    if before:
        x.before = json.dumps(before, ensure_ascii=False, sort_keys=2)
    if after:
        x.after = json.dumps(after, ensure_ascii=False, sort_keys=2)
    x.save()
