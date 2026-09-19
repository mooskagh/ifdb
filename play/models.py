import shutil
import uuid
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import User
from games.models import Game, GameURL


class Playable(models.Model):
    class Meta:
        default_permissions = ()

    class State(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        BUILDING = "BUILDING", _("Building")
        READY = "READY", _("Ready")
        ERROR = "ERROR", _("Error")

    slug: models.SlugField[str | None, str | None] = models.SlugField(
        unique=True, null=True, blank=True
    )
    game: models.ForeignKey[Game, Game] = models.ForeignKey(
        "games.Game", on_delete=models.PROTECT
    )
    game_url: models.ForeignKey[GameURL | None, GameURL | None] = (
        models.ForeignKey(
            "games.GameURL",
            on_delete=models.PROTECT,
            null=True,
            blank=True,
            related_name="playables",
        )
    )
    template: models.SlugField[str, str] = models.SlugField()
    template_version: models.CharField[str, str] = models.CharField(
        max_length=32
    )
    template_config: models.JSONField[dict[str, object], dict[str, object]] = (
        models.JSONField(default=dict, blank=True)
    )
    config: models.JSONField[dict[str, object], dict[str, object]] = (
        models.JSONField(default=dict, blank=True)
    )
    state: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.PENDING,
    )
    visible: models.BooleanField[bool, bool] = models.BooleanField(
        default=True,
    )
    player_name: models.CharField[str | None, str | None] = models.CharField(
        max_length=128, null=True, blank=True
    )
    player_url: models.CharField[str | None, str | None] = models.CharField(
        max_length=512, null=True, blank=True
    )
    created: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now_add=True
    )
    updated: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now=True
    )

    def __str__(self) -> str:
        return self.slug or f"playable-{self.pk}"


class PlaySession(models.Model):
    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["-last_seen_at"]),
        ]

    play_session_id: models.UUIDField[uuid.UUID | str, uuid.UUID] = (
        models.UUIDField(unique=True, db_index=True)
    )
    playable: models.ForeignKey[Playable, Playable] = models.ForeignKey(
        Playable, on_delete=models.CASCADE, related_name="sessions"
    )
    started_at: models.DateTimeField[datetime, datetime] = (
        models.DateTimeField(default=timezone.now)
    )
    last_seen_at: models.DateTimeField[datetime, datetime] = (
        models.DateTimeField(default=timezone.now)
    )

    def __str__(self) -> str:
        return (
            f"PlaySession {self.play_session_id} (playable {self.playable.pk})"
        )


class PlaySegment(models.Model):
    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["play_session", "-started_at"]),
        ]

    class State(models.TextChoices):
        ACTIVE = "active", _("Active")
        IDLE = "idle", _("Idle")
        BACKGROUND = "background", _("Background")

    play_session: models.ForeignKey[PlaySession, PlaySession] = (
        models.ForeignKey(
            PlaySession, on_delete=models.CASCADE, related_name="segments"
        )
    )
    user: models.ForeignKey[User | None, User | None] = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    django_session_key: models.CharField[str | None, str | None] = (
        models.CharField(max_length=40, null=True, blank=True)
    )
    ip_addr: models.CharField[str | None, str | None] = models.CharField(
        max_length=50, null=True, blank=True
    )
    state: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.ACTIVE,
    )
    started_at: models.DateTimeField[datetime, datetime] = (
        models.DateTimeField(default=timezone.now)
    )
    last_seen_at: models.DateTimeField[datetime, datetime] = (
        models.DateTimeField(default=timezone.now)
    )
    active_seconds: models.FloatField[float, float] = models.FloatField(
        default=0.0
    )

    def __str__(self) -> str:
        return f"PlaySegment {self.pk} ({self.state})"


@receiver(pre_delete, sender=Playable)
def on_playable_pre_delete(
    sender: type[Playable], instance: Playable, **kwargs: object
) -> None:
    from play.caddy import delete_caddy_playable

    delete_caddy_playable(instance.pk)
    destination = Path(settings.PLAYABLE_DIR) / str(instance.pk)
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
