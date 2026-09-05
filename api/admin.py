from django.contrib import admin

from .models import APIToken


@admin.register(APIToken)
class APITokenAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "name",
        "user",
        "key_prefix",
        "is_active",
        "created_at",
        "last_used_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "user__username", "user__email", "key")
    readonly_fields = ("created_at", "last_used_at")

    def key_prefix(self, obj: APIToken) -> str:
        if obj.key:
            return f"{obj.key[:8]}..."
        return ""

    key_prefix.short_description = "Key"  # type: ignore[attr-defined]
