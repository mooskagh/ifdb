from django.db import models


class Playable(models.Model):
    class Meta:
        default_permissions = ()

    slug = models.SlugField(unique=True)
    game = models.ForeignKey("games.Game", on_delete=models.PROTECT)
    template = models.SlugField()
    config = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.slug
