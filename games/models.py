from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _

# Create your models here.


class Game(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    title = models.CharField(_('Title'), max_length=255)
    description = models.TextField(_('Description'), null=True, blank=True)
    release_date = models.DateField(_('Release date'), null=True, blank=True)
    creation_time = models.DateTimeField(_('Added at'), db_index=True)
    edit_time = models.DateTimeField(_('Last edit'), null=True, blank=True)
    view_perm = models.CharField(
        _('Game view permission'), max_length=255, default='@all')
    edit_perm = models.CharField(
        _('Edit permission'), max_length=255, default='@auth')
    comment_perm = models.CharField(
        _('Comment permission'), max_length=255, default='@auth')
    tags = models.ManyToManyField('GameTag', blank=True)
    added_by = models.ForeignKey(User)

    # -(GameContestEntry)
    # (GameRatings)
    # (GameComments)
    # (LoadLog) // For computing popularity
    # -(GamePopularity)
    def GetAuthors(self):
        authors = {}
        roles = []
        for x in GameAuthor.objects.filter(game=self):
            if x.role in authors:
                authors[x.role].append(x.author)
            else:
                roles.append(x.role)
                authors[x.role] = [x.author]
        roles.sort(key=lambda x: x.order)
        res = []
        for r in roles:
            res.append({'role': r, 'authors': authors[r]})
        return res

    def GetTagsForDetails(self, perm):
        tags = {}
        cats = []
        for x in self.tags.all():
            category = x.category
            if not perm(category.show_in_details_perm):
                continue
            if category in tags:
                tags[category].append(x)
            else:
                cats.append(category)
                tags[category] = [x]
        cats.sort(key=lambda x: x.order)
        res = []
        for r in cats:
            res.append({'category': r, 'tags': tags[r]})
        return res

    def GetURLs(self):
        urls = {}
        cats = []
        for x in GameURL.objects.filter(game=self):
            category = x.category
            if category in urls:
                urls[category].append(x)
            else:
                cats.append(category)
                urls[category] = [x]
        cats.sort(key=lambda x: x.order)
        res = []
        for r in cats:
            res.append({'category': r, 'urls': urls[r]})
        return res


class URL(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s" % (self.original_url)

    local_url = models.CharField(null=True, blank=True, max_length=255)
    original_url = models.CharField(
        null=True, blank=True, max_length=255, db_index=True)
    original_filename = models.CharField(null=True, blank=True, max_length=255)
    content_type = models.CharField(null=True, blank=True, max_length=255)
    ok_to_clone = models.BooleanField(default=True)
    is_uploaded = models.BooleanField(default=False)
    is_broken = models.BooleanField(default=False)
    creation_date = models.DateTimeField()
    use_count = models.IntegerField(default=0)
    file_size = models.IntegerField(null=True, blank=True)
    creator = models.ForeignKey(User, null=True, blank=True)


class RecodedURL(models.Model):
    original = models.ForeignKey(URL)
    recoded_url = models.CharField(null=True, blank=True, max_length=255)
    interpreter = models.CharField(max_length=32)


class URLCategory(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True)
    title = models.CharField(max_length=255, db_index=True)
    allow_cloning = models.BooleanField(default=True)
    order = models.SmallIntegerField(default=0)


class GameURL(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s (%s): %s" % (self.game, self.category, self.url)

    game = models.ForeignKey(Game)
    url = models.ForeignKey(URL)
    category = models.ForeignKey(URLCategory)
    description = models.CharField(null=True, blank=True, max_length=255)


class Author(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    name = models.CharField(max_length=255)


class GameAuthorRole(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True)
    title = models.CharField(max_length=255, db_index=True)
    order = models.SmallIntegerField(default=100)


class GameAuthor(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s -- %s (%s)" % (self.game, self.author, self.role)

    game = models.ForeignKey(Game)
    author = models.ForeignKey(Author)
    role = models.ForeignKey(GameAuthorRole)


class GameTagCategory(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True)
    name = models.CharField(max_length=255, db_index=True)
    allow_new_tags = models.BooleanField(default=True)
    show_in_edit_perm = models.CharField(max_length=255, default='@all')
    show_in_search_perm = models.CharField(max_length=255, default='@all')
    show_in_details_perm = models.CharField(max_length=255, default='@all')
    order = models.SmallIntegerField(default=0)


class GameTag(models.Model):
    class Meta:
        unique_together = (('category', 'name'), )
        default_permissions = ()

    def __str__(self):
        return "%s: %s" % (self.category, self.name)

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True)
    category = models.ForeignKey(GameTagCategory)
    name = models.CharField(max_length=255, db_index=True)
    order = models.SmallIntegerField(default=0)


class GameVote(models.Model):
    class Meta:
        unique_together = (('game', 'user'), )
        default_permissions = ()

    def __str__(self):
        return "%s: %s (%d)" % (self.user, self.game, self.star_rating)

    game = models.ForeignKey(Game, db_index=True)
    user = models.ForeignKey(User, db_index=True)
    creation_time = models.DateTimeField()
    edit_time = models.DateTimeField(null=True, blank=True)
    game_finished = models.BooleanField()
    play_time_mins = models.IntegerField()
    star_rating = models.SmallIntegerField()


class GameComment(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s: %s: %s (%s)" % (self.user, self.game, self.subject,
                                    self.creation_time)

    game = models.ForeignKey(Game, db_index=True)
    user = models.ForeignKey(User, null=True, blank=True)
    parent = models.ForeignKey('GameComment', null=True, blank=True)
    foreign_username = models.CharField(max_length=255, null=True, blank=True)
    foreign_id = models.CharField(
        max_length=255, null=True, blank=True, db_index=True)
    foreign_url = models.CharField(max_length=255, null=True, blank=True)
    creation_time = models.DateTimeField()
    edit_time = models.DateTimeField(null=True, blank=True)
    subject = models.CharField(max_length=255, null=True, blank=True)
    text = models.TextField()
    is_deleted = models.BooleanField(default=False)


