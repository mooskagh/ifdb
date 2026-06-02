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

    def save(self, *args, **kwargs):
        if self.state != self.State.NEEDS_ATTENTION:
            self.attention_reason = None
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {
                    *kwargs["update_fields"],
                    "attention_reason",
                }
        super().save(*args, **kwargs)

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
        PLUT = "PLUT", _("Plut")
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
    missing_since = models.DateTimeField(
        _("Missing since"), null=True, blank=True
    )


class SourceDiscoveryStatus(models.Model):
    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["source_type", "-last_seen"])]

    def __str__(self):
        return f"{self.get_source_type_display()} @ {self.last_seen:%Y-%m-%d}"

    source_type = models.CharField(
        _("Source type"), max_length=16, choices=GameSource.SourceType
    )
    first_seen = models.DateTimeField(_("First seen"))
    last_seen = models.DateTimeField(_("Last seen"))
    is_error = models.BooleanField(_("Error"), default=False)
    error_message = models.TextField(_("Error message"), null=True, blank=True)
    new_ids = models.JSONField(_("New sources"), default=list)
    existing_ids = models.JSONField(_("Existing sources"), default=list)
    absent_ids = models.JSONField(_("Absent sources"), default=list)
    newly_missing_ids = models.JSONField(
        _("Newly missing sources"), default=list
    )
    unused_ids = models.JSONField(_("Unused sources"), default=list)
    duplicate_id_clusters = models.JSONField(
        _("Duplicate source clusters"), default=list
    )

    @classmethod
    def record(
        cls,
        source_type,
        *,
        ts,
        is_error,
        error_message,
        new_ids,
        existing_ids,
        absent_ids,
        newly_missing_ids,
        unused_ids,
        duplicate_id_clusters,
    ):
        """Extend the current run-length row, or start a new one on change."""
        new_ids = sorted(new_ids)
        existing_ids = sorted(existing_ids)
        absent_ids = sorted(absent_ids)
        newly_missing_ids = sorted(newly_missing_ids)
        unused_ids = sorted(unused_ids)
        duplicate_id_clusters = sorted(
            sorted(cluster) for cluster in duplicate_id_clusters
        )
        last = (
            cls.objects
            .filter(source_type=source_type)
            .order_by("-last_seen")
            .first()
        )
        same = last and (
            last.is_error == is_error
            and last.error_message == error_message
            and last.new_ids == new_ids
            and last.existing_ids == existing_ids
            and last.absent_ids == absent_ids
            and last.newly_missing_ids == newly_missing_ids
            and last.unused_ids == unused_ids
            and last.duplicate_id_clusters == duplicate_id_clusters
        )
        if same:
            last.last_seen = ts
            last.save(update_fields=["last_seen"])
            return last
        return cls.objects.create(
            source_type=source_type,
            first_seen=ts,
            last_seen=ts,
            is_error=is_error,
            error_message=error_message,
            new_ids=new_ids,
            existing_ids=existing_ids,
            absent_ids=absent_ids,
            newly_missing_ids=newly_missing_ids,
            unused_ids=unused_ids,
            duplicate_id_clusters=duplicate_id_clusters,
        )


class GameSourceFetch(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return f"Fetch #{self.pk} of source #{self.source_id}"

    source = models.ForeignKey(GameSource, on_delete=models.CASCADE)
    raw_content = models.TextField(_("Raw content"))
    canonical_text = models.TextField(_("Canonical text"))
    canonical_text_hash = models.CharField(
        _("Canonical text hash"), max_length=64, db_index=True
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
    proposed_at = models.DateTimeField(_("Proposed at"))
    approved_at = models.DateTimeField(_("Approved at"), null=True, blank=True)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposed_game_edits",
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(_("Status"), max_length=16, choices=EditStatus)
    origin = models.CharField(_("Origin"), max_length=16, choices=Origin)
    used_sources = models.ManyToManyField(GameSourceFetch, blank=True)
    passes = models.JSONField(_("Passes"), default=list)
    previous_canonical_text = models.TextField(
        _("Previous canonical text"), null=True, blank=True
    )
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


class EnrichmentRule(models.Model):
    class Meta:
        default_permissions = ()
        ordering = ["order", "pk"]

    def __str__(self):
        return self.description or f"Rule #{self.pk}"

    order = models.PositiveSmallIntegerField(_("Order"), default=0)
    enabled = models.BooleanField(_("Enabled"), default=True)
    description = models.CharField(
        _("Description"), max_length=200, blank=True
    )
    condition = models.TextField(_("Condition"), blank=True)  # empty = always
    action = models.TextField(_("Action"))


class GenreMapping(models.Model):
    class Meta:
        default_permissions = ()
        ordering = ["tag"]

    def __str__(self):
        return f"{self.tag} -> {self.genre_slug}"

    tag = models.CharField(_("Free-text tag"), max_length=100, unique=True)
    genre_slug = models.CharField(_("Genre slug"), max_length=32)
    replace = models.BooleanField(_("Replace original tag"), default=True)


class GameHistoryAuditLog(models.Model):
    class Meta:
        default_permissions = ()

    class AuditKind(models.TextChoices):
        INITIAL_IMPORT = (
            "INITIAL_IMPORT",
            _("Initial import from old importer"),
        )
        SOURCE_ATTACHED = "SOURCE_ATTACHED", _("Source attached")
        FIELD_CHANGE = "FIELD_CHANGE", _("Field changed")

    class AuditField(models.TextChoices):
        AUTO_UPDATES = "AUTO_UPDATES", _("Auto-update policy")
        STATE = "STATE", _("State")
        CANONICAL_TEXT = "CANONICAL_TEXT", _("Canonical text")

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
