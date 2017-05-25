from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import PermissionDenied

# Create your models here.


class Game(models.Model):
    def __str__(self):
        return self.title

    title = models.CharField(_('Title'), max_length=255)
    description = models.TextField(_('Description'), null=True, blank=True)
    release_date = models.DateField(_('Release date'), null=True, blank=True)
    creation_time = models.DateTimeField(_('Added at'))
    edit_time = models.DateTimeField(_('Last edit'), null=True, blank=True)
    is_hidden = models.BooleanField(_('Hidden'), default=False)
    is_readonly = models.BooleanField(_('Readonly'), default=False)
    tags = models.ManyToManyField('GameTag')
    added_by = models.ForeignKey(User)

    # -(GameContestEntry)
    # (GameRatings)
    # (GameComments)
    # (LoadLog) // For computing popularity
    # -(GamePopularity)
    def FillAuthors(self, authors):
        # TODO(crem) Erase before creation.
        for role, author in authors:
            r = GameAuthorRole.GetByNameOrId(role)
            a = Author.GetByNameOrId(author)
            ga = GameAuthor()
            ga.game = self
            ga.author = a
            ga.role = r
            ga.save()

    def FillTags(self, tags):
        # TODO(crem) Erase before creation.
        for category, value in tags:
            cat = GameTagCategory.GetByNameOrId(category)
            if not cat.show_in_edit:
                raise PermissionDenied
            val = GameTag.GetByNameOrId(value, cat)
            self.tags.add(val)
        self.save()


class URL(models.Model):
    def __str__(self):
        return "%s : %s" % (self.local_url, self.original_url)

    original_url = models.URLField(null=True, blank=True)
    local_url = models.CharField(null=True, blank=True, max_length=255)
    local_path = models.CharField(null=True, blank=True, max_length=255)
    content_type = models.CharField(null=True, blank=True, max_length=255)
    show_original = models.BooleanField(default=True)
    show_local = models.BooleanField(default=True)
    is_broken = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    creation_date = models.DateTimeField()
    use_count = models.IntegerField(default=0)
    creator = models.ForeignKey(User, null=True, blank=True)


class URLCategory(models.Model):
    def __str__(self):
        return self.title

    symbolic_id = models.SlugField()
    title = models.CharField(max_length=255)
    description = models.CharField(null=True, blank=True, max_length=255)
    allow_in_editor = models.BooleanField(default=True)
    order = models.SmallIntegerField(default=0)


class GameURL(models.Model):
    def __str__(self):
        return "%s (%s): %s" % (self.game, self.category, self.url)

    game = models.ForeignKey(Game)
    url = models.ForeignKey(URL)
    category = models.ForeignKey(URLCategory)
    description = models.CharField(null=True, blank=True, max_length=255)
    order = models.SmallIntegerField(default=0)


class Author(models.Model):
    def __str__(self):
        return self.name

    name = models.CharField(max_length=255)

    @staticmethod
    def GetByNameOrId(val):
        if isinstance(val, int):
            return Author.objects.get(id=val)
        obj, _ = Author.objects.get_or_create(name=val)
        return obj


class GameAuthorRole(models.Model):
    def __str__(self):
        return self.title

    symbolic_id = models.SlugField(null=True, blank=True)
    title = models.CharField(max_length=255)
    order = models.SmallIntegerField(default=0)

    @staticmethod
    def GetByNameOrId(val):
        if isinstance(val, int):
            return GameAuthorRole.objects.get(id=val)
        obj, _ = GameAuthorRole.objects.get_or_create(title=val)
        return obj


class GameAuthor(models.Model):
    def __str__(self):
        return "%s -- %s (%s)" % (self.game, self.author, self.role)

    game = models.ForeignKey(Game)
    author = models.ForeignKey(Author)
    role = models.ForeignKey(GameAuthorRole)


class GameTagCategory(models.Model):
    def __str__(self):
        return self.name

    symbolic_id = models.SlugField(null=True, blank=True)
    name = models.CharField(max_length=255)
    allow_new_tags = models.BooleanField(default=False)
    show_in_edit = models.BooleanField(default=True)
    show_in_search = models.BooleanField(default=True)
    show_in_details = models.BooleanField(default=True)
    order = models.SmallIntegerField(default=0)

    @staticmethod
    def GetByNameOrId(val):
        if isinstance(val, int):
            return GameTagCategory.objects.get(id=val)
        return GameTagCategory.objects.get(name=val)


class GameTag(models.Model):
    def __str__(self):
        return "%s: %s" % (self.category, self.name)

    symbolic_id = models.SlugField(null=True, blank=True)
    category = models.ForeignKey(GameTagCategory)
    name = models.CharField(max_length=255)
    show_in_edit = models.BooleanField(default=True)
    show_in_search = models.BooleanField(default=True)
    show_in_details = models.BooleanField(default=True)
    order = models.SmallIntegerField(default=0)

    @staticmethod
    def GetByNameOrId(val, category):
        if isinstance(val, int):
            return GameTag.objects.get(id=val, category=category)
        if category.allow_new_tags:
            return GameTag.objects.get_or_create(
                name=val, category=category)[0]
        else:
            return GameTag.objects.get(name=val, category=category)
