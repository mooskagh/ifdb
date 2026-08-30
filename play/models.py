from datetime import datetime

from django.db import models

from games.models import Game


class Playable(models.Model):
    class Meta:
        default_permissions = ()

    slug: models.SlugField[str, str] = models.SlugField(unique=True)
    game: models.ForeignKey[Game, Game] = models.ForeignKey(
        "games.Game", on_delete=models.PROTECT
    )
    template: models.SlugField[str, str] = models.SlugField()
    template_version: models.CharField[str, str] = models.CharField(
        max_length=32
    )
    config: models.JSONField[dict[str, object], dict[str, object]] = (
        models.JSONField(default=dict, blank=True)
    )
    created: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now_add=True
    )
    updated: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now=True
    )

    def __str__(self) -> str:
        return self.slug
