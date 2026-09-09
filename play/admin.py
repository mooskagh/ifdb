from typing import TYPE_CHECKING

from django.contrib import admin

from .models import Playable

if TYPE_CHECKING:
    _ModelAdminBase = admin.ModelAdmin[Playable]
else:
    _ModelAdminBase = admin.ModelAdmin


@admin.register(Playable)
class PlayableAdmin(_ModelAdminBase):
    list_display = [
        "pk",
        "slug",
        "game",
        "game_url",
        "template",
        "template_version",
        "state",
        "visible",
        "created",
        "updated",
    ]
    list_filter = ["state", "visible", "template"]
    search_fields = ["pk", "slug", "game__title", "template"]
    raw_id_fields = ["game", "game_url"]
    readonly_fields = ["created", "updated"]
