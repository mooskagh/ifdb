from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from .curation import GameEdit, GameHistory

_MTOK = Decimal(1_000_000)


class LLMModel(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    def cost_for(self, prompt, cached_input, cache_write, completion):
        """Total USD for the given token counts, from the four $/Mtok rates."""
        return (
            self.input_cost * prompt
            + self.cached_input_cost * cached_input
            + self.cache_write_cost * cache_write
            + self.output_cost * completion
        ) / _MTOK

    name = models.CharField(_("OpenRouter id"), max_length=200, unique=True)
    context_length = models.PositiveIntegerField(_("Context length"))
    input_cost = models.DecimalField(
        _("Input cost ($/Mtok)"), max_digits=12, decimal_places=4
    )
    cached_input_cost = models.DecimalField(
        _("Cached input read cost ($/Mtok)"), max_digits=12, decimal_places=4
    )
    cache_write_cost = models.DecimalField(
        _("Cache write cost ($/Mtok)"), max_digits=12, decimal_places=4
    )
    output_cost = models.DecimalField(
        _("Output cost ($/Mtok)"), max_digits=12, decimal_places=4
    )
    updated_at = models.DateTimeField(_("Updated at"), null=True, blank=True)


class LlmWorkflow(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    name = models.CharField(_("Name"), max_length=100, unique=True)
    runner = models.CharField(
        _("Python runner"), max_length=100, db_index=True
    )
    prompt_template = models.TextField(_("Prompt template"))
    model = models.ForeignKey(LLMModel, on_delete=models.PROTECT)
    runner_params = models.JSONField(
        _("Runner parameters"), default=dict, blank=True
    )


class LlmTrajectory(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return f"LLM trajectory #{self.pk} (${self.cost})"

    history = models.ForeignKey(GameHistory, on_delete=models.CASCADE)
    edit = models.ForeignKey(
        GameEdit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    workflow = models.ForeignKey(
        LlmWorkflow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    model = models.ForeignKey(
        LLMModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("Created at"))
    messages = models.JSONField(_("Messages"), default=list)
    prompt_tokens = models.PositiveIntegerField(_("Prompt tokens"), default=0)
    cached_input_tokens = models.PositiveIntegerField(
        _("Cached input tokens"), default=0
    )
    cache_write_tokens = models.PositiveIntegerField(
        _("Cache write tokens"), default=0
    )
    completion_tokens = models.PositiveIntegerField(
        _("Completion tokens"), default=0
    )
    cost = models.DecimalField(
        _("Cost (USD)"), max_digits=12, decimal_places=6
    )
