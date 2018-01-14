from .models import UserLog
from django.utils import timezone
import json


def GetIpAddr(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    else:
        return request.META.get('REMOTE_ADDR')


def LogAction(request,
              action,
              *,
              is_mutation,
              obj,
              obj2=None,
              before=None,
              after=None):
    x = UserLog()
    x.user = request.user
    x.ip_addr = GetIpAddr(request)
    x.session = request.session.session_key
    x.timestamp = timezone.now()
    x.perm = str(request.perm)
    x.action = action
    x.is_mutation = is_mutation
    if obj:
        x.obj_type = obj.__class__.__name__
        x.obj_id = obj.id
    if obj2:
        x.obj2_type = obj2.__class__.__name__
        x.obj2_id = obj2.id
    if before:
        x.before = json.dumps(before, ensure_ascii=False)
    if after:
        x.after = json.dumps(after, ensure_ascii=False)
    x.save()
