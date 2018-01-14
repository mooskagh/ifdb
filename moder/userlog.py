from .models import UserLog
from django.utils import timezone
import json

CRAWLER_STRS = ['YandexBot', 'Googlebot']


def GetIpAddr(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    else:
        return request.META.get('REMOTE_ADDR')


def IsCrawler(request):
    useragent = request.META.get('HTTP_USER_AGENT', '')
    for x in CRAWLER_STRS:
        if x in useragent:
            return True
    return False


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
    if IsCrawler(request):
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
