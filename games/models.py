from django.db import models
from django.conf import settings
from django.utils.translation import ugettext_lazy as _

# Create your models here.


class Game(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    title = models.CharField(_('Title'), max_length=255)
    description = models.TextField(_('Description'), null=True, blank=True)
    release_date = models.DateField(
        _('Release date'), null=True, blank=True, db_index=True)
    creation_time = models.DateTimeField(_('Added at'), db_index=True)
    edit_time = models.DateTimeField(_('Last edit'), null=True, blank=True)
    view_perm = models.CharField(
        _('Game view permission'), max_length=255, default='(alias game_view)')
    edit_perm = models.CharField(
        _('Edit permission'), max_length=255, default='(alias game_edit)')
    comment_perm = models.CharField(
        _('Comment permission'),
        max_length=255,
        default='(alias game_comment)')
    delete_perm = models.CharField(
        _('Delete permission'), max_length=255, default='(alias game_delete)')
    vote_perm = models.CharField(
        _('Vote permission'), max_length=255, default='(alias game_vote)')
    tags = models.ManyToManyField('GameTag', blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True)

    # -(GameContestEntry)
    # (LoadLog) // For computing popularity
    # -(GamePopularity)


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
        null=True, blank=True, max_length=2048, db_index=True)
    original_filename = models.CharField(null=True, blank=True, max_length=255)
    content_type = models.CharField(null=True, blank=True, max_length=255)
    ok_to_clone = models.BooleanField(default=True)
    is_uploaded = models.BooleanField(default=False)
    is_broken = models.BooleanField(default=False)
    creation_date = models.DateTimeField()
    use_count = models.IntegerField(default=0)
    file_size = models.IntegerField(null=True, blank=True)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True)


class GameURLCategory(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    RECODABLE_CAT = None

    @staticmethod
    def IsRecodable(id):
        if GameURLCategory.RECODABLE_CAT is None:
            GameURLCategory.RECODABLE_CAT = GameURLCategory.objects.get(
                symbolic_id='play_in_interpreter').id

        return id == GameURLCategory.RECODABLE_CAT

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True)
    title = models.CharField(max_length=255, db_index=True)
    allow_cloning = models.BooleanField(default=True)
    order = models.SmallIntegerField(default=0)


class GameURL(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s (%s): %s" % (self.game.title, self.category,
                                self.url.original_url)

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


class InterpretedGameUrl(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s (%s)" % (self.original.url.original_url, self.recoded_url)

    def GetRecodedUrl(self):
        return self.recoded_url or self.original.GetLocalUrl()

    original = models.OneToOneField(
        GameURL, on_delete=models.CASCADE, primary_key=True)
    recoded_filename = models.CharField(null=True, blank=True, max_length=255)
    recoded_url = models.CharField(null=True, blank=True, max_length=255)
    recoding_date = models.DateTimeField()
    is_playable = models.NullBooleanField()
    configuration_json = models.CharField(
        null=True, blank=True, max_length=255)


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
                PersonalityURLCategory.objects.get(symbolic_id='other_site').id
            )
        return PersonalityURLCategory.OTHER_SITE_CAT

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True)
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
        _('Game view permission'),
        max_length=255,
        default='(alias personality_view)')
    edit_perm = models.CharField(
        _('Edit permission'),
        max_length=255,
        default='(alias personality_edit)')


class PersonalityUrl(models.Model):
    class Meta:
        default_permissions = ()

    personality = models.ForeignKey(Personality, on_delete=models.CASCADE)
    url = models.ForeignKey(URL, on_delete=models.CASCADE)
    category = models.ForeignKey(
        PersonalityURLCategory, on_delete=models.CASCADE)
    description = models.CharField(null=True, blank=True, max_length=255)


class PersonalityAlias(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name

    personality = models.ForeignKey(
        Personality, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=255)
    keep_if_empty = models.BooleanField(default=False)
    hidden_for = models.ForeignKey(
        'PersonalityAlias', null=True, blank=True, on_delete=models.SET_NULL)
    is_blacklisted = models.BooleanField(default=False)


class PersonalityAliasRedirect(models.Model):
    class Meta:
        default_permissions = ()

    name = models.CharField(max_length=255, unique=True, db_index=True)
    hidden_for = models.ForeignKey(
        PersonalityAlias, null=True, blank=True, on_delete=models.CASCADE)


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

    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    author = models.ForeignKey(PersonalityAlias, on_delete=models.CASCADE)
    role = models.ForeignKey(GameAuthorRole, on_delete=models.CASCADE)


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
    category = models.ForeignKey(GameTagCategory, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, db_index=True)


class GameVote(models.Model):
    class Meta:
        unique_together = (('game', 'user'), )
        default_permissions = ()

    def __str__(self):
        return "%s: %s (%d)" % (self.user, self.game, self.star_rating)

    game = models.ForeignKey(Game, db_index=True, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_index=True,
        null=True,
        blank=True,
        on_delete=models.SET_NULL)
    creation_time = models.DateTimeField()
    edit_time = models.DateTimeField(null=True, blank=True)
    star_rating = models.SmallIntegerField()


class GameComment(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s: %s: (%s) \"%s\"" % (self.user, self.game,
                                        self.creation_time, self.text[:40])

    def GetUsername(self):
        if self.username:
            return self.username
        if self.user:
            return self.user.username
        return 'Анонимоўс'

    game = models.ForeignKey(Game, db_index=True, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL)
    username = models.CharField(max_length=64, null=True, blank=True)
    parent = models.ForeignKey(
        'GameComment', null=True, blank=True, on_delete=models.SET_NULL)
    creation_time = models.DateTimeField()
    edit_time = models.DateTimeField(null=True, blank=True)
    text = models.TextField()
    is_deleted = models.BooleanField(default=False)
