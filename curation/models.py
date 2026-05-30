from django.conf import settings
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _


class GameHistory(models.Model):
    class Meta:
        default_permissions = ()

    class AutoUpdate(models.TextChoices):
        REJECT = "REJECT", _("Reject incoming imports")
        PROPOSE = "PROPOSE", _("Propose for review")
        ACCEPT = "ACCEPT", _("Auto-approve and apply")

    class State(models.TextChoices):
        SETTLED = "SETTLED", _("Settled")
        IN_PROGRESS = "IN_PROGRESS", _("In progress")
        NEEDS_ATTENTION = "NEEDS_ATTENTION", _("Needs attention")

    def __str__(self):
        return f"History #{self.pk} ({self.get_state_display()})"

    game = models.OneToOneField(
        "games.Game",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    auto_updates = models.CharField(
        _("Auto-update policy"),
        max_length=16,
        choices=AutoUpdate,
        default=AutoUpdate.ACCEPT,
    )
    priority = models.IntegerField(_("Priority"), default=100)
    state = models.CharField(
        _("State"),
        max_length=16,
        choices=State,
        default=State.IN_PROGRESS,
    )
    attention_reason = models.TextField(
        _("Attention reason"), null=True, blank=True
    )
    creation_time = models.DateTimeField(_("Created at"))
    edit_time = models.DateTimeField(_("Last edit"), null=True, blank=True)


class GameSource(models.Model):
    class Meta:
        default_permissions = ()

    class SourceType(models.TextChoices):
        APERO = "APERO", _("Apero")
        IFWIKI = "IFWIKI", _("IFWiki")
        QSP = "QSP", _("QSP")
        INSTEAD = "INSTEAD", _("INSTEAD")
        QUESTBOOK = "QUESTBOOK", _("QuestBook")
        IFICTION = "IFICTION", _("ifiction")
        RILARHIV = "RILARHIV", _("Rilarhiv")
        CURRENT_TEXT = "CURRENT_TEXT", _("Current text")
        STICKY_NOTE = "STICKY_NOTE", _("Sticky note")

    def __str__(self):
        return f"{self.get_type_display()}: {self.url or '(no url)'}"

    history = models.ForeignKey(
        GameHistory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    url = models.CharField(
        _("URL"), max_length=2048, null=True, blank=True, db_index=True
    )
    type = models.CharField(_("Type"), max_length=16, choices=SourceType)
    failing_since = models.DateTimeField(
        _("Failing since"), null=True, blank=True
    )
    last_attempt = models.DateTimeField(
        _("Last attempt"), null=True, blank=True
    )
    last_error = models.TextField(_("Last error"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created at"), null=True, blank=True)


class GameSourceFetch(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return f"Fetch #{self.pk} of source #{self.source_id}"

    source = models.ForeignKey(GameSource, on_delete=models.CASCADE)
    raw_content = models.TextField(_("Raw content"))
    filtered_content = models.TextField(_("Filtered content"))
    filtered_content_hash = models.CharField(
        _("Filtered content hash"), max_length=64, db_index=True
    )
    first_fetch = models.DateTimeField(_("First fetch"))
    last_fetch = models.DateTimeField(_("Last fetch"))


class GameEdit(models.Model):
    class Meta:
        default_permissions = ()

    class EditStatus(models.TextChoices):
        PROPOSED = "PROPOSED", _("Proposed")
        APPLIED = "APPLIED", _("Applied")
        REJECTED = "REJECTED", _("Rejected")

    class Origin(models.TextChoices):
        AUTO_IMPORT = "AUTO_IMPORT", _("Automatic import")
        MANUAL_EDIT = "MANUAL_EDIT", _("Manual edit")
        USER_SUGGESTION = "USER_SUGGESTION", _("User suggestion")

    def __str__(self):
        return f"Edit #{self.pk} ({self.get_status_display()})"

    history = models.ForeignKey(GameHistory, on_delete=models.CASCADE)
    parent_edit = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    proposed_at = models.DateTimeField(_("Proposed at"))
    approved_at = models.DateTimeField(_("Approved at"), null=True, blank=True)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(_("Status"), max_length=16, choices=EditStatus)
    origin = models.CharField(_("Origin"), max_length=16, choices=Origin)
    used_sources = models.ManyToManyField(GameSourceFetch, blank=True)
    canonical_text = models.TextField(_("Canonical text"))


class GameHistoryComment(models.Model):
    class Meta:
        default_permissions = ()

    class CommentType(models.TextChoices):
        USER_FEEDBACK = "USER_FEEDBACK", _("User feedback")
        MODS_COMMENT = "MODS_COMMENT", _("Moderator comment")
        NOTE_FOR_AI = "NOTE_FOR_AI", _("Note for AI")
        STATUS_MESSAGE = "STATUS_MESSAGE", _("Status message")
        EMAIL_RESPONSE = "EMAIL_RESPONSE", _("Email response")

    def __str__(self):
        return f"Comment #{self.pk} on history #{self.history_id}"

    history = models.ForeignKey(GameHistory, on_delete=models.CASCADE)
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    type = models.CharField(_("Type"), max_length=16, choices=CommentType)
    text = models.TextField(_("Text"))
    creation_time = models.DateTimeField(_("Created at"))


class GameHistoryAuditLog(models.Model):
    class Meta:
        default_permissions = ()

    class AuditKind(models.TextChoices):
        INITIAL_IMPORT = (
            "INITIAL_IMPORT",
            _("Initial import from old importer"),
        )
        FIELD_CHANGE = "FIELD_CHANGE", _("Field changed")

    class AuditField(models.TextChoices):
        AUTO_UPDATES = "AUTO_UPDATES", _("Auto-update policy")
        STATE = "STATE", _("State")

    def __str__(self):
        return f"Audit #{self.pk} on history #{self.history_id}"

    @classmethod
    def record_change(cls, history, actor, field, old, new):
        """Record a FIELD_CHANGE entry for an editable history field."""
        return cls.objects.create(
            history=history,
            actor=actor,
            created_at=now(),
            kind=cls.AuditKind.FIELD_CHANGE,
            field=field,
            old_text=old,
            new_text=new,
        )

    history = models.ForeignKey(GameHistory, on_delete=models.CASCADE)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("Created at"))
    kind = models.CharField(_("Kind"), max_length=32, choices=AuditKind)
    field = models.CharField(
        _("Field"), max_length=32, choices=AuditField, null=True, blank=True
    )
    old_id = models.IntegerField(null=True, blank=True)
    new_id = models.IntegerField(null=True, blank=True)
    old_text = models.TextField(null=True, blank=True)
    new_text = models.TextField(null=True, blank=True)
