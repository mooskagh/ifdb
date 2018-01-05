from django.contrib.auth.models import (AbstractBaseUser, PermissionsMixin,
                                        UserManager)
from django.core.mail import send_mail
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import ugettext as _
from django.conf import settings
from games.models import Game


class User(AbstractBaseUser, PermissionsMixin):
    """
    A class implementing a fully featured User model with admin-compliant
    permissions.

    Email and password are required. Other fields are optional.
    """

    class Meta:
        default_permissions = ()
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        abstract = False

    def __str__(self):
        return self.username or self.email

    email = models.EmailField(
        _('email address'),
        unique=True,
        error_messages={
            'unique': _("A user with that email already exists."),
        })
    username = models.CharField(
        _('username'),
        max_length=30,
        unique=True,
        blank=True,
        null=True,
        help_text=_('максимум 30 символов, ну и всякие другие требования'),
        validators=[
            RegexValidator(
                r'^[\w\d_\.,\-]+(?: [\w\d_\.,\-]+)*$',
                _('Enter a valid username. This value may contain only '
                  'letters, numbers and _ character.'), 'invalid'),
        ],
        error_messages={
            'unique': _("The username is already taken."),
        })
    is_staff = models.BooleanField(
        _('Staff Status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin '
                    'site.'))
    is_active = models.BooleanField(
        'Active',
        default=True,
        help_text=_('Designates whether this user should be treated as '
                    'active. Unselect this instead of deleting accounts.'))
    date_joined = models.DateTimeField(_('Date Joined'), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def get_full_name(self):
        """
        Returns email instead of the fullname for the user.
        """
        return self.username or self.email

    def get_short_name(self):
        """
        Returns the short name for the user.
        This function works the same as `get_full_name` method.
        It's just included for django built-in user comparability.
        """
        return self.get_full_name()

    def email_user(self, subject, message, from_email=None, **kwargs):
        """
        Sends an email to this User.
        """
        send_mail(subject, message, from_email, [self.email], **kwargs)


class TaskQueueElement(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        def StatusStr():
            if self.fail:
                return 'fail'
            if self.pending:
                return 'pending'
            if self.success:
                return 'success'
            return 'none'

        return "%s -- %s (%s)" % (StatusStr(), self.name, self.command_json)

    name = models.CharField(
        db_index=True, max_length=255, null=True, blank=True)
    command_json = models.CharField(max_length=512)
    priority = models.IntegerField(default=100)
    # json:
    #   module: str
    #   function: str
    #   argv: []
    #   kwarg: {}
    onfail_json = models.CharField(null=True, blank=True, max_length=512)
    retries_left = models.IntegerField(default=3)
    retry_minutes = models.IntegerField(default=2000)
    cron = models.CharField(null=True, blank=True, max_length=32)
    enqueue_time = models.DateTimeField(null=True, blank=True)
    scheduled_time = models.DateTimeField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    finish_time = models.DateTimeField(null=True, blank=True)
    dependency = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL)
    pending = models.BooleanField(default=True)
    success = models.BooleanField(default=False)
    fail = models.BooleanField(default=False)


class Package(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    name = models.CharField(db_index=True, max_length=128)
    download_perm = models.CharField(max_length=256, default="@all")
    edit_perm = models.CharField(max_length=256, default="@pkgadm")
    game = models.ForeignKey(
        Game, null=True, blank=True, on_delete=models.CASCADE)


class PackageVersion(models.Model):
    class Meta:
        default_permissions = ()

    package = models.ForeignKey(Package, on_delete=models.CASCADE)
    version = models.CharField(max_length=32)
    md5hash = models.CharField(max_length=32)
    metadata_json = models.TextField()
    creation_date = models.DateTimeField()


class PackageSession(models.Model):
    class Meta:
        default_permissions = ()

    package = models.ForeignKey(
        Package,
        db_index=True,
        null=True,
        blank=True,
        on_delete=models.SET_NULL)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL)
    client = models.CharField(max_length=64)
    duration_secs = models.IntegerField(null=True, blank=True)
    start_time = models.DateTimeField()
    last_update = models.DateTimeField()
    is_finished = models.BooleanField(default=False)


class Document(models.Model):
    class Meta:
        default_permissions = ()

    slug = models.SlugField(db_index=True)
    parent = models.ForeignKey(
        'Document', null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=256)
    text = models.TextField()
    last_update = models.DateTimeField()
    view_perm = models.CharField(max_length=256, default="@admin")
    list_perm = models.CharField(max_length=256, default="@admin")
    order = models.IntegerField(default=0)


class Snippet(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    title = models.CharField(max_length=256)
    url = models.CharField(max_length=256, null=True, blank=True)
    style_json = models.CharField(max_length=256)
    content_json = models.TextField()
    view_perm = models.CharField(max_length=256, default="@all")
    order = models.SmallIntegerField(default=0)
    show_start = models.DateTimeField(null=True, blank=True)
    show_end = models.DateTimeField(null=True, blank=True)
    is_async = models.BooleanField(default=False)


class SnippetPin(models.Model):
    class Meta:
        default_permissions = ()
        unique_together = (("snippet", "user"), )

    snippet = models.ForeignKey(Snippet, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_hidden = models.BooleanField(default=False)
    order = models.SmallIntegerField(null=True, blank=True)


class FeedCache(models.Model):
    class Meta:
        default_permissions = ()
        unique_together = (("feed_id", "item_id"), )
        indexes = [
            models.Index(fields=['date_published']),
            models.Index(fields=['feed_id', 'item_id']),
        ]

    feed_id = models.CharField(max_length=32)
    item_id = models.CharField(max_length=512)
    date_published = models.DateTimeField()
    date_discovered = models.DateTimeField()
    title = models.CharField(max_length=256)
    authors = models.CharField(max_length=256)
    url = models.CharField(max_length=2048)


class BlogFeed(models.Model):
    class Meta:
        default_permissions = ()

    feed_id = models.CharField(max_length=32)
    title = models.CharField(max_length=256)
    url = models.CharField(max_length=256, null=True, blank=True)
    show_author = models.BooleanField()
    rss = models.CharField(max_length=256)
    rss_comments = models.CharField(max_length=256, null=True, blank=True)