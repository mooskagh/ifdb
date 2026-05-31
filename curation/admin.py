from django.contrib import admin

from .models import (
    GameEdit,
    GameHistory,
    GameHistoryAuditLog,
    GameHistoryComment,
    GameSource,
    GameSourceFetch,
)


@admin.register(GameHistory)
class GameHistoryAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "game",
        "state",
        "auto_updates",
        "priority",
        "creation_time",
    ]
    list_filter = ["state", "auto_updates"]
    search_fields = ["pk", "attention_reason"]
    raw_id_fields = ["game"]


@admin.register(GameSource)
class GameSourceAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "history",
        "type",
        "url",
        "failing_since",
        "last_attempt",
    ]
    list_filter = ["type"]
    search_fields = ["pk", "url"]
    raw_id_fields = ["history"]


@admin.register(GameSourceFetch)
class GameSourceFetchAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "source",
        "canonical_text_hash",
        "first_fetch",
        "last_fetch",
    ]
    search_fields = ["pk", "canonical_text_hash"]
    raw_id_fields = ["source"]


@admin.register(GameEdit)
class GameEditAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "history",
        "status",
        "origin",
        "proposed_at",
        "approver",
    ]
    list_filter = ["status", "origin"]
    search_fields = ["pk"]
    raw_id_fields = [
        "history",
        "parent_edit",
        "approver",
        "used_sources",
    ]


@admin.register(GameHistoryComment)
class GameHistoryCommentAdmin(admin.ModelAdmin):
    list_display = ["pk", "history", "type", "user", "creation_time"]
    list_filter = ["type"]
    search_fields = ["pk", "text"]
    raw_id_fields = ["history", "reply_to", "user"]


@admin.register(GameHistoryAuditLog)
class GameHistoryAuditLogAdmin(admin.ModelAdmin):
    list_display = ["pk", "history", "kind", "field", "actor", "created_at"]
    list_filter = ["kind", "field"]
    search_fields = ["pk"]
    raw_id_fields = ["history", "actor"]
