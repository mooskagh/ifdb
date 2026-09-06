from datetime import datetime

from django.db import models
from django.utils.translation import gettext_lazy as _

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
    created: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now_add=True
    )
    updated: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now=True
    )

    def __str__(self) -> str:
        return self.slug or f"playable-{self.pk}"
