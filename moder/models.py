from django.db import models
from django.conf import settings


class UserLog(models.Model):
    class Meta:
        default_permissions = ()

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True)
    action = models.CharField(max_length=32)
    ip_addr = models.CharField(max_length=50, null=True, blank=True)
    session = models.CharField(max_length=32, null=True, blank=True)
    timestamp = models.DateTimeField()
    perm = models.TextField(null=True, blank=True)
    is_mutation = models.BooleanField()
    obj_type = models.CharField(max_length=32, null=True, blank=True)
    obj_id = models.IntegerField(null=True, blank=True)
    obj2_type = models.CharField(max_length=32, null=True, blank=True)
    obj2_id = models.IntegerField(null=True, blank=True)
    before = models.TextField(null=True, blank=True)
    after = models.TextField(null=True, blank=True)
    useragent = models.TextField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
