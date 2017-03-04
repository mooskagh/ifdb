from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _

# Create your models here.


class Game(models.Model):
    def __str__(self):
        return self.title

    title = models.CharField(_('Title'), max_length=255)
    description = models.TextField(_('Description'))
    creation_time = models.DateTimeField(_('Added at'))
    edit_time = models.DateTimeField(_('Last edit'))
    is_hidden = models.BooleanField(_('Hidden'), default=False)
    is_readonly = models.BooleanField(_('Readonly'), default=False)
    added_by = models.ForeignKey(User)

    # -(GameContestEntry)
    # (GameRatings)
    # (GameComments)
    # (LoadLog) // For computing popularity
    # -(GamePopularity)


class URL(models.Model):
    original_url = models.URLField(null=True, blank=True)
    local_url = models.CharField(null=True, blank=True, max_length=255)
    local_path = models.FilePathField(null=True, blank=True)
    content_type = models.CharField(null=True, blank=True, max_length=255)
    show_original = models.BooleanField(default=True)
    show_local = models.BooleanField(default=True)
    is_broken = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    creation_date = models.DateTimeField()
    use_count = models.IntegerField(default=0)
    creator = models.ForeignKey(User)


class URLCategory(models.Model):
    symbolic_id = models.SlugField()
    title = models.CharField(max_length=255)
    description = models.CharField(null=True, blank=True, max_length=255)
    allow_in_editor = models.BooleanField(default=True)
    order = models.SmallIntegerField(default=0)


class GameURL(models.Model):
    game = models.ForeignKey(Game)
    url = models.ForeignKey(URL)
    category = models.ForeignKey(URLCategory)
    description = models.CharField(null=True, blank=True, max_length=255)
    order = models.SmallIntegerField(default=0)


class Author(models.Model):
    name = models.CharField(max_length=255)


class GameAuthorRole(models.Model):
    symbolic_id = models.SlugField()
    title = models.CharField(max_length=255)
    order = models.SmallIntegerField(default=0)


class GameAuthor(models.Model):
    game = models.ForeignKey(Game)
    author = models.ForeignKey(Author)
    role = models.ForeignKey(GameAuthorRole)


class GameTagCategory(models.Model):
    symbolic_id = models.SlugField()
    name = models.CharField(max_length=255)
    description = models.CharField(null=True, blank=True, max_length=255)
    mutaly_exclusive = models.BooleanField(default=False)
    allow_new_tags = models.BooleanField(default=False)
    show_in_search = models.BooleanField(default=True)
    show_in_details = models.BooleanField(default=True)
    order = models.SmallIntegerField(default=0)


class GameTag(models.Model):
    symbolic_id = models.SlugField()
    category = models.ForeignKey(GameTagCategory)
    title = models.CharField(max_length=255)
    description = models.CharField(null=True, blank=True, max_length=255)
    show_in_search = models.BooleanField(default=False)
    show_in_details = models.BooleanField(default=True)
