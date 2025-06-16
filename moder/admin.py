from django.contrib import admin

from .models import UserLog


@admin.register(UserLog)
class UserLogAdmin(admin.ModelAdmin):
    list_display = [
        "action",
        "obj_id",
        "obj2_id",
        "user",
        "ip_addr",
        "timestamp",
        "is_mutation",
    ]
    search_fields = ["action", "user", "ip_addr", "timestamp", "is_mutation"]
    list_filter = ["action"]
    raw_id_fields = ["user"]
