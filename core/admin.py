from django.contrib import admin
from .models import TaskQueueElement, User

admin.site.register(TaskQueueElement)
admin.site.register(User)
