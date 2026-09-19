from typing import TYPE_CHECKING

from django.contrib import admin

from .models import Playable, PlaySegment, PlaySession

if TYPE_CHECKING:
    _PlayableAdminBase = admin.ModelAdmin[Playable]
    _PlaySessionAdminBase = admin.ModelAdmin[PlaySession]
    _PlaySegmentAdminBase = admin.ModelAdmin[PlaySegment]
else:
    _PlayableAdminBase = admin.ModelAdmin
    _PlaySessionAdminBase = admin.ModelAdmin
    _PlaySegmentAdminBase = admin.ModelAdmin


@admin.register(Playable)
class PlayableAdmin(_PlayableAdminBase):
    list_display = [
        "pk",
        "slug",
        "game",
        "game_url",
        "template",
        "template_version",
        "player_name",
        "state",
        "visible",
        "created",
        "updated",
    ]
    list_filter = ["state", "visible", "template"]
    search_fields = ["pk", "slug", "game__title", "template"]
    raw_id_fields = ["game", "game_url"]
    readonly_fields = ["created", "updated"]


@admin.register(PlaySession)
class PlaySessionAdmin(_PlaySessionAdminBase):
    list_display = [
        "pk",
        "play_session_id",
        "playable",
        "started_at",
        "last_seen_at",
    ]
    search_fields = ["play_session_id", "playable__slug"]
    raw_id_fields = ["playable"]
    readonly_fields = ["started_at", "last_seen_at"]


@admin.register(PlaySegment)
class PlaySegmentAdmin(_PlaySegmentAdminBase):
    list_display = [
        "pk",
        "play_session",
        "user",
        "ip_addr",
        "state",
        "active_seconds",
        "started_at",
        "last_seen_at",
    ]
    list_filter = ["state"]
    search_fields = [
        "play_session__play_session_id",
        "ip_addr",
        "user__username",
    ]
    raw_id_fields = ["play_session", "user"]
    readonly_fields = ["started_at", "last_seen_at"]
