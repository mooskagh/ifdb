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
    search_fields = ["action", "user__username", "user__email", "ip_addr"]
    list_filter = ["action", "is_mutation"]
    raw_id_fields = ["user"]
