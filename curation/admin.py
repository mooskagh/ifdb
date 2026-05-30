from django.contrib import admin

from .models import (
    GameReconciliation,
    GameSource,
    GameSourceFetch,
    GameTicket,
    GameTicketAuditLog,
    GameTicketComment,
)


@admin.register(GameTicket)
class GameTicketAdmin(admin.ModelAdmin):
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
        "ticket",
        "type",
        "url",
        "failing_since",
        "last_attempt",
    ]
    list_filter = ["type"]
    search_fields = ["pk", "url"]
    raw_id_fields = ["ticket"]


@admin.register(GameSourceFetch)
class GameSourceFetchAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "source",
        "filtered_content_hash",
        "first_fetch",
        "last_fetch",
    ]
    search_fields = ["pk", "filtered_content_hash"]
    raw_id_fields = ["source"]


@admin.register(GameReconciliation)
class GameReconciliationAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "ticket",
        "status",
        "origin",
        "proposed_at",
        "approver",
    ]
    list_filter = ["status", "origin"]
    search_fields = ["pk"]
    raw_id_fields = [
        "ticket",
        "parent_reconciliation",
        "approver",
        "used_sources",
    ]


@admin.register(GameTicketComment)
class GameTicketCommentAdmin(admin.ModelAdmin):
    list_display = ["pk", "ticket", "type", "user", "creation_time"]
    list_filter = ["type"]
    search_fields = ["pk", "text"]
    raw_id_fields = ["ticket", "reply_to", "user"]


@admin.register(GameTicketAuditLog)
class GameTicketAuditLogAdmin(admin.ModelAdmin):
    list_display = ["pk", "ticket", "kind", "field", "actor", "created_at"]
    list_filter = ["kind", "field"]
    search_fields = ["pk"]
    raw_id_fields = ["ticket", "actor"]
