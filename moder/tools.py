import math
from .models import UserLog
from collections import Counter
from django.utils import timezone


def GetPopularGameids(daily_decay=3, anonymous_factor=0.3):
    factor = math.log2(daily_decay)
    seen = set()
    counts = Counter()
    visits = UserLog.objects.filter(action='gam-view').order_by('-pk')[:2000]
    now = timezone.now()

    for x in visits:
        user_id = '[%d]' % x.user_id if x.user else x.ip_addr[:7]
        visit_id = (x.obj_id, user_id)
        if visit_id in seen:
            continue
        seen.add(visit_id)
        age_days = (now - x.timestamp).total_seconds() / (24 * 60 * 60)
        amount = 1 / (1 + age_days)**factor
        if not x.user:
            amount *= anonymous_factor
        counts.update({x.obj_id: amount})
    return counts
