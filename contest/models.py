from django.db import models
from games.models import Game, URL


# Create your models here.
class Competition(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.title

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=32)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    # Support for private contests (view_perm?)


class CompetitionURLCategory(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s (%s)" % (self.title, self.symbolic_id)

    symbolic_id = models.SlugField(
        max_length=32, null=True, blank=True, db_index=True, unique=True)
    title = models.CharField(max_length=255, db_index=True)
    allow_cloning = models.BooleanField(default=True)
    order = models.SmallIntegerField(default=0)


class CompetitionURL(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s -- %s" % (self.competition, self.url)

    def GetLocalUrl(self):
        if self.category.allow_cloning:
            return self.url.GetLocalUrl()
        else:
            return self.url.original_url

    def GetRemoteUrl(self):
        return self.url.original_url

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    url = models.ForeignKey(URL, on_delete=models.CASCADE)
    category = models.ForeignKey(
        CompetitionURLCategory, on_delete=models.CASCADE)
    description = models.CharField(null=True, blank=True, max_length=255)


class CompetitionDocument(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s -- [%s] -- %s" % (self.competition, self.slug, self.title)

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    slug = models.SlugField(blank=True)
    title = models.CharField(max_length=256)
    text = models.TextField()
    view_perm = models.CharField(max_length=256, default="@admin")


class CompetitionSchedule(models.Model):
    class Meta:
        default_permissions = ()

    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    when = models.DateTimeField()
    done = models.BooleanField()
    show = models.BooleanField()
    title = models.CharField(null=True, blank=True, max_length=255)
    command = models.TextField(null=True, blank=True)
    # text = models.TextField()   # "Blog post" about the event.


class GameList(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s -- %s" % (self.competition, self.title)

    competition = models.ForeignKey(
        Competition, null=True, blank=True, on_delete=models.CASCADE)
    title = models.CharField(null=True, blank=True, max_length=255)
    order = models.SmallIntegerField(default=0)
    # edit_perm = models.CharField(max_length=255, default="@admin")


class GameListEntry(models.Model):
    class Meta:
        default_permissions = ()

    def __str__(self):
        return "%s -- %s -- %s" % (str(self.rank), self.game, self.gamelist)

    gamelist = models.ForeignKey(GameList, on_delete=models.CASCADE)
    rank = models.IntegerField(null=True, blank=True)
    game = models.ForeignKey(
        Game, null=True, blank=True, on_delete=models.SET_NULL)
    datetime = models.DateTimeField(null=True, blank=True)
    comment = models.CharField(max_length=255, null=True, blank=True)
    # TODO (Add "authors" field for upcoming games in trainli support)
