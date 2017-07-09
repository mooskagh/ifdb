from django.contrib import admin
from .models import TaskQueueElement, User
from django.contrib.sessions.models import Session


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    def _session_data(self, obj):
        return obj.get_decoded()

    list_display = ['session_key', '_session_data', 'expire_date']


@admin.register(TaskQueueElement)
class TaskQueueElementAdmin(admin.ModelAdmin):
    list_display = [
        'pk', 'name', 'command_json', 'retries_left', 'scheduled_time',
        'pending', 'success', 'fail'
    ]
    list_filter = ['scheduled_time', 'pending', 'success', 'fail']
    search_fields = ['pk', 'name']


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        'username', 'email', 'last_login', 'is_staff', 'is_superuser',
        'is_active', 'pk'
    ]
    search_fields = ['username']
    list_filter = ['last_login', 'is_active']
