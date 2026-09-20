from django.contrib import admin
from django.contrib.sessions.models import Session

from .models import (
    BlogFeed,
    FeedCache,
    Snippet,
    SnippetPin,
    User,
)


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    def _session_data(self, obj):
        return obj.get_decoded()

    list_display = ["session_key", "_session_data", "expire_date"]


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        "username",
        "email",
        "last_login",
        "is_staff",
        "is_superuser",
        "is_active",
        "pk",
    ]
    search_fields = ["pk", "username"]
    list_filter = ["last_login", "is_active"]


@admin.register(Snippet)
class SnippetAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "order",
        "show_start",
        "show_end",
        "is_async",
    ]
    search_fields = ["pk", "title"]
    list_filter = ["order", "is_async"]


@admin.register(SnippetPin)
class SnippetPinAdmin(admin.ModelAdmin):
    list_display = ["snippet", "user", "is_hidden", "order"]


@admin.register(FeedCache)
class FeedCacheAdmin(admin.ModelAdmin):
    list_display = ["feed_id", "item_id", "date_published", "title"]


@admin.register(BlogFeed)
class BlogFeedAdmin(admin.ModelAdmin):
    list_display = ["feed_id", "title"]
