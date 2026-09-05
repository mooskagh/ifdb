from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

# Create your models here.


class GameQuerySet(models.QuerySet["Game"]):
    def published(self) -> "GameQuerySet":
        return self.filter(state=Game.State.PUBLISHED)


class Game(models.Model):
    class State(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PUBLISHED = "PUBLISHED", _("Published")
        ABANDONED = "ABANDONED", _("Abandoned")
        REDIRECT = "REDIRECT", _("Redirect")

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state="REDIRECT",
                        redirect_to__isnull=False,
                    )
                    | models.Q(
                        state__in=["DRAFT", "PUBLISHED", "ABANDONED"],
                        redirect_to__isnull=True,
                    )
                ),
                name="games_game_state_redirect_target",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(redirect_to__isnull=True)
                    | ~models.Q(pk=models.F("redirect_to_id"))
                ),
                name="games_game_redirect_not_self",
            ),
        ]

    objects = GameQuerySet.as_manager()

    @transaction.atomic
    def abandon(self, actor: Any, *, keep_orphan: bool = False) -> None:
        from curation.models import (
            GameHistory,
            GameHistoryAuditLog,
            GameSource,
        )

        game = Game.objects.select_for_update().get(pk=self.pk)
        history = (
            GameHistory.objects
            .select_for_update()
            .filter(game_id=game.pk)
            .first()
        )
        timestamp = now()
        if history is not None:
            for source in GameSource.objects.select_for_update().filter(
                game=game
            ):
                GameHistoryAuditLog.record_source(
                    game,
                    actor,
                    GameHistoryAuditLog.AuditKind.SOURCE_DETACHED,
                    source,
                )
                source.game = None
                source.keep_orphan = keep_orphan
                source.save(update_fields=["game", "keep_orphan"])

            old_state = history.state
            history.state = GameHistory.State.ABANDONED
            history.auto_updates = GameHistory.AutoUpdate.REJECT
            history.processing_started_at = None
            history.processing_task_id = None
            history.edit_time = timestamp
            history.save(
                update_fields=[
                    "state",
                    "auto_updates",
                    "processing_started_at",
                    "processing_task_id",
                    "edit_time",
                ]
            )
            GameRevision.objects.filter(
                game=game,
                status=GameRevision.Status.PROPOSED,
            ).update(status=GameRevision.Status.REJECTED)
            if old_state != history.state:
                GameHistoryAuditLog.record_change(
                    game,
                    actor,
                    GameHistoryAuditLog.AuditField.STATE,
                    old_state,
                    history.state,
                )

        game.state = Game.State.ABANDONED
        game.redirect_to = None
        game.edit_time = timestamp
        game.save(update_fields=["state", "redirect_to", "edit_time"])

    def __str__(self):
        return self.title

    title = models.CharField(_("Title"), max_length=255)
    description = models.TextField(_("Description"), null=True, blank=True)
    description_attributions = models.ManyToManyField(
        "GameDescriptionAttribution", blank=True
    )
    release_date = models.DateField(
        _("Release date"), null=True, blank=True, db_index=True
    )
    creation_time = models.DateTimeField(_("Added at"), db_index=True)
    edit_time = models.DateTimeField(_("Last edit"), null=True, blank=True)
    state = models.CharField(
        _("Publication state"),
        max_length=16,
        choices=State,
        default=State.DRAFT,
        db_index=True,
    )
    published_revision = models.ForeignKey(
        "GameRevision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Published revision"),
    )
    redirect_to = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="redirects",
    )
    view_perm = models.CharField(
        _("Game view permission"), max_length=255, default="(alias game_view)"
    )
    edit_perm = models.CharField(
        _("Edit permission"), max_length=255, default="(alias game_edit)"
    )
    comment_perm = models.CharField(
        _("Comment permission"), max_length=255, default="(alias game_comment)"
    )
    delete_perm = models.CharField(
        _("Delete permission"), max_length=255, default="(alias game_delete)"
    )
    vote_perm = models.CharField(
        _("Vote permission"), max_length=255, default="(alias game_vote)"
    )
    tags = models.ManyToManyField("GameTag", blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    # -(GameContestEntry)
    # (LoadLog) // For computing popularity
    # -(GamePopularity)


class GameRevision(models.Model):
    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["game"],
                condition=models.Q(status="PROPOSED"),
                name="games_gamerevision_one_proposed_per_game",
            )
        ]

    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", _("Proposed")
        ACCEPTED = "ACCEPTED", _("Accepted")
        REJECTED = "REJECTED", _("Rejected")

    class Origin(models.TextChoices):
        AUTO_IMPORT = "AUTO_IMPORT", _("Automatic import")
        MANUAL_EDIT = "MANUAL_EDIT", _("Manual edit")
        USER_SUGGESTION = "USER_SUGGESTION", _("User suggestion")
        BACKFILL = "BACKFILL", _("Backfill")
        ROLLBACK = "ROLLBACK", _("Rollback")
        PARTIAL_ROLLBACK = "PARTIAL_ROLLBACK", _("Partial rollback")
        REAPPLICATION = "REAPPLICATION", _("Reapplication")
        PARTIAL_REAPPLY = "PARTIAL_REAPPLY", _("Partial reapplication")

    def __str__(self) -> str:
        return f"Revision #{self.pk} ({self.get_status_display()})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.status == self.Status.PROPOSED:
            with transaction.atomic():
                Game.objects.select_for_update().get(pk=self.game_id)
                pending_edits = GameRevision.objects.filter(
                    game_id=self.game_id, status=self.Status.PROPOSED
                )
                if self.pk:
                    pending_edits = pending_edits.exclude(pk=self.pk)
                pending_edits.update(status=self.Status.REJECTED)
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

        if self.status == self.Status.ACCEPTED:
            latest_id = (
                GameRevision.objects
                .filter(game_id=self.game_id, status=self.Status.ACCEPTED)
                .order_by("-published_at", "-created_at", "-id")
                .values_list("id", flat=True)
                .first()
            )
            if latest_id == self.pk:
                Game.objects.filter(pk=self.game_id).update(
                    published_revision_id=self.pk
                )
                if "game" in self._state.fields_cache:
                    self.game.published_revision_id = self.pk
                    self.game.published_revision = self

    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    created_at = models.DateTimeField(_("Created at"))
    published_at = models.DateTimeField(
        _("Published at"), null=True, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_game_revisions",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(_("Status"), max_length=16, choices=Status)
    origin = models.CharField(_("Origin"), max_length=16, choices=Origin)
    used_sources = models.ManyToManyField(
        "curation.GameSourceFetch", blank=True
    )
    passes = models.JSONField(_("Passes"), default=list)
    previous_canonical_text = models.TextField(
        _("Previous canonical text"), null=True, blank=True
    )
    canonical_text = models.TextField(_("Canonical text"))


class GameDescriptionAttribution(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    name = models.CharField(max_length=255, unique=True, db_index=True)


class URL(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s" % (self.original_url)

    def GetLocalUrl(self):
        return self.local_url or self.original_url

    def HasLocalCopy(self):
        return not self.is_uploaded and self.local_url is not None

    def GetFs(self):
        return settings.UPLOADS_FS if self.is_uploaded else settings.BACKUPS_FS

    local_url = models.CharField(null=True, blank=True, max_length=255)
    local_filename = models.CharField(null=True, blank=True, max_length=255)
    original_url = models.CharField(
        null=True, blank=True, max_length=2048, db_index=True
    )
    original_filename = models.CharField(null=True, blank=True, max_length=255)
    content_type = models.CharField(null=True, blank=True, max_length=255)
    ok_to_clone = models.BooleanField(default=False)
    is_uploaded = models.BooleanField(default=False)
    is_broken = models.BooleanField(default=False)
    creation_date = models.DateTimeField()
    use_count = models.IntegerField(default=0)
    file_size = models.IntegerField(null=True, blank=True)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )


class GameURLCategory(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True
    )
    title = models.CharField(max_length=255, db_index=True)
    allow_cloning = models.BooleanField(default=True)
    order = models.SmallIntegerField(default=0)


class GameURL(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s (%s): %s" % (
            self.game.title,
            self.category,
            self.url.original_url,
        )

    def HasLocalCopy(self):
        return self.category.allow_cloning and self.url.HasLocalCopy()

    def GetLocalUrl(self):
        if self.category.allow_cloning:
            return self.url.GetLocalUrl()
        else:
            return self.url.original_url

    def GetRemoteUrl(self):
        return self.url.original_url

    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    url = models.ForeignKey(URL, on_delete=models.CASCADE)
    category = models.ForeignKey(GameURLCategory, on_delete=models.CASCADE)
    description = models.CharField(null=True, blank=True, max_length=255)


class PersonalityURLCategory(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    OTHER_SITE_CAT = None

    @staticmethod
    def OtherSiteCatId():
        if PersonalityURLCategory.OTHER_SITE_CAT is None:
            PersonalityURLCategory.OTHER_SITE_CAT = (
                PersonalityURLCategory.objects.get(symbolic_id="other_site").id
            )
        return PersonalityURLCategory.OTHER_SITE_CAT

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True
    )
    title = models.CharField(max_length=255, db_index=True)
    allow_cloning = models.BooleanField(default=False)


class Personality(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    name = models.CharField(max_length=255)
    bio = models.TextField(null=True, blank=True)
    view_perm = models.CharField(
        _("Game view permission"),
        max_length=255,
        default="(alias personality_view)",
    )
    edit_perm = models.CharField(
        _("Edit permission"),
        max_length=255,
        default="(alias personality_edit)",
    )


class PersonalityUrl(models.Model):
    class Meta:
        default_permissions = ()

    personality = models.ForeignKey(Personality, on_delete=models.CASCADE)
    url = models.ForeignKey(URL, on_delete=models.CASCADE)
    category = models.ForeignKey(
        PersonalityURLCategory, on_delete=models.CASCADE
    )
    description = models.CharField(null=True, blank=True, max_length=255)


class PersonalityAlias(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    personality = models.ForeignKey(
        Personality, null=True, blank=True, on_delete=models.SET_NULL
    )
    name = models.CharField(max_length=255)
    keep_if_empty = models.BooleanField(default=False)


class PersonalityAliasRedirect(models.Model):
    class Meta:
        default_permissions = ()

    name = models.CharField(max_length=255, unique=True, db_index=True)
    hidden_for = models.ForeignKey(
        PersonalityAlias, null=True, blank=True, on_delete=models.CASCADE
    )


class GameAuthorRole(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True
    )
    title = models.CharField(max_length=255, db_index=True)
    order = models.SmallIntegerField(default=100)


class GameAuthor(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s -- %s (%s)" % (self.game, self.author, self.role)

    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    author = models.ForeignKey(PersonalityAlias, on_delete=models.CASCADE)
    role = models.ForeignKey(GameAuthorRole, on_delete=models.CASCADE)


class GameTagCategory(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True
    )
    name = models.CharField(max_length=255, db_index=True)
    allow_new_tags = models.BooleanField(default=True)
    show_in_edit_perm = models.CharField(max_length=255, default="@all")
    show_in_search_perm = models.CharField(max_length=255, default="@all")
    show_in_details_perm = models.CharField(max_length=255, default="@all")
    order = models.SmallIntegerField(default=0)


class GameTag(models.Model):
    class Meta:
        unique_together = (("category", "name"),)
        default_permissions = ()

    def __str__(self):
        return "%s: %s" % (self.category, self.name)

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True
    )
    category = models.ForeignKey(GameTagCategory, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, db_index=True)


class GameVote(models.Model):
    class Meta:
        unique_together = (("game", "user"),)
        default_permissions = ()

    def __str__(self):
        return "%s: %s (%d)" % (self.user, self.game, self.star_rating)

    game = models.ForeignKey(Game, db_index=True, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_index=True,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    creation_time = models.DateTimeField()
    edit_time = models.DateTimeField(null=True, blank=True)
    star_rating = models.SmallIntegerField()


class GameComment(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return '%s: %s: (%s) "%s"' % (
            self.user,
            self.game,
            self.creation_time,
            self.text[:40],
        )

    def GetUsername(self):
        if self.username:
            return self.username
        if self.user:
            return self.user.username
        return "Анонимоўс"

    game = models.ForeignKey(Game, db_index=True, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    username = models.CharField(max_length=64, null=True, blank=True)
    parent = models.ForeignKey(
        "GameComment", null=True, blank=True, on_delete=models.SET_NULL
    )
    creation_time = models.DateTimeField()
    edit_time = models.DateTimeField(null=True, blank=True)
    text = models.TextField()
    is_deleted = models.BooleanField(default=False)


class GameCommentVote(models.Model):
    class Meta:
        unique_together = (("comment", "user"),)
        default_permissions = ()

    comment = models.ForeignKey(GameComment, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE
    )
    vote_time = models.DateTimeField()
    vote = models.SmallIntegerField()
