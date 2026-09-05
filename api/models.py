import secrets
from typing import Any

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


def generate_token_key() -> str:
    return secrets.token_hex(32)


class APIToken(models.Model):
    class Meta:
        verbose_name = _("API Token")
        verbose_name_plural = _("API Tokens")
        ordering = ["-created_at"]

    user = models.ForeignKey(  # type: ignore[var-annotated]
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
        verbose_name=_("User"),
    )
    name = models.CharField(  # type: ignore[var-annotated]
        _("Name / Description"), max_length=128
    )
    key = models.CharField(  # type: ignore[var-annotated]
        _("Token Key"),
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_token_key,
    )
    created_at = models.DateTimeField(  # type: ignore[var-annotated]
        _("Created at"), auto_now_add=True
    )
    last_used_at = models.DateTimeField(  # type: ignore[var-annotated]
        _("Last used at"), null=True, blank=True
    )
    is_active = models.BooleanField(  # type: ignore[var-annotated]
        _("Active"), default=True
    )
    permissions = models.JSONField(
        _("Permissions / Scopes"),
        default=list,
        blank=True,
        help_text=_(
            "List of allowed scopes (e.g. 'games:read', 'games:write', "
            "'games:publish', 'files:upload'). Use '*' or empty for all."
        ),
    )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.key:
            self.key = generate_token_key()
        super().save(*args, **kwargs)

    def has_perm(self, perm: str) -> bool:
        if not self.is_active:
            return False
        perms: list[str] = (
            self.permissions if isinstance(self.permissions, list) else []
        )
        if not perms or "*" in perms:
            return True
        return perm in perms

    def __str__(self) -> str:
        user_str = str(getattr(self, "user", "unknown"))
        return f"{self.name} ({user_str})"
