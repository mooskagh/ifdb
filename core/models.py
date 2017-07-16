from django.contrib.auth.models import (AbstractBaseUser, PermissionsMixin,
                                        UserManager)
from django.core.mail import send_mail
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import ugettext as _
from games.models import Game


class User(AbstractBaseUser, PermissionsMixin):
    """
    A class implementing a fully featured User model with admin-compliant
    permissions.

    Email and password are required. Other fields are optional.
    """

    class Meta(object):
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
        _('Active'),
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
    dependency = models.ForeignKey('self', null=True, blank=True)
    pending = models.BooleanField(default=True)
    success = models.BooleanField(default=False)
    fail = models.BooleanField(default=False)


class Package(models.Model):
    def __str__(self):
        return self.name

    name = models.CharField(db_index=True, max_length=128)
    download_perm = models.CharField(max_length=256, default="@all")
    edit_perm = models.CharField(max_length=256, default="@pkgadm")
    game = models.ForeignKey(Game, null=True, blank=True)


class PackageVersion(models.Model):
    package = models.ForeignKey(Package)
    version = models.CharField(max_length=32)
    md5hash = models.CharField(max_length=32)
    metadata_json = models.TextField()
    creation_date = models.DateTimeField()
