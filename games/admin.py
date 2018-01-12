from django.contrib import admin
from .models import (Game, PersonalityAlias, GameTagCategory, GameTag, URL,
                     GameURLCategory, GameURL, GameAuthorRole, GameAuthor,
                     GameVote, GameComment, InterpretedGameUrl, Personality,
                     PersonalityUrl)


class GameAuthorAdmin(admin.TabularInline):
    model = GameAuthor
    readonly_fields = ('id', )
    raw_id_fields = ['game', 'author']
    extra = 1


class InlinePersonalityUrlAdmin(admin.TabularInline):
    model = PersonalityUrl
    readonly_fields = ('id', )
    raw_id_fields = ['url', 'personality']
    extra = 1


class InlineGameURLAdmin(admin.TabularInline):
    model = GameURL
    readonly_fields = ('id', )
    raw_id_fields = ['url', 'game']
    extra = 1


@admin.register(PersonalityUrl)
class PersonalityUrlAdmin(admin.ModelAdmin):
    list_display = ['personality', 'description', 'category', 'url']
    raw_id_fields = ['personality', 'url']
    search_fields = ['pk', 'personality', 'description', 'url']


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ['pk', 'title', 'creation_time', 'added_by']
    list_filter = ['creation_time', 'added_by']
    search_fields = ['pk', 'title']

    inlines = [GameAuthorAdmin, InlineGameURLAdmin]


class InlinePersonalityAliasAdmin(admin.TabularInline):
    model = PersonalityAlias
    readonly_fields = ('id', )
    raw_id_fields = ['hidden_for']
    extra = 1


@admin.register(PersonalityAlias)
class PersonalityAliasAdmin(admin.ModelAdmin):
    def _game_count(self, obj):
        return len(obj.gameauthor_set.all())

    list_display = [
        'name', 'pk', 'is_blacklisted', 'hidden_for', '_game_count'
    ]
    search_fields = ['pk', 'name']
    inlines = [GameAuthorAdmin]
    raw_id_fields = ['personality', 'hidden_for']


@admin.register(Personality)
class PersonalityAdmin(admin.ModelAdmin):
    def _alias_count(self, obj):
        return len(obj.personalityalias_set.all())

    def _aliases(self, obj):
        aliases = ["%s" % x for x in obj.personalityalias_set.all()]
        return '; '.join(aliases)

    list_display = ['pk', 'name', '_alias_count', '_aliases']
    search_fields = ['pk', 'name', 'personalityalias__name']
    inlines = [InlinePersonalityUrlAdmin, InlinePersonalityAliasAdmin]


@admin.register(GameTagCategory)
class GameTagCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'symbolic_id', 'allow_new_tags']
    search_fields = ['pk', 'name', 'symbolic_id']


@admin.register(GameTag)
class GameTagAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'symbolic_id']
    search_fields = ['pk', 'name', 'symbolic_id']
    list_filter = ['category']


@admin.register(URL)
class URLAdmin(admin.ModelAdmin):
    def _original_url(self, obj):
        if len(obj.original_url) < 80:
            return obj.original_url
        return obj.original_url[:80] + '…'

    list_display = [
        '_original_url', 'local_url', 'ok_to_clone', 'is_uploaded',
        'is_broken', 'creation_date'
    ]
    search_fields = ['pk', 'original_url', 'local_url']
    list_filter = [
        'ok_to_clone', 'is_uploaded', 'is_broken', 'creation_date', 'creator'
    ]

    inlines = [InlineGameURLAdmin, InlinePersonalityUrlAdmin]


@admin.register(GameURLCategory)
class GameURLCategoryAdmin(admin.ModelAdmin):
    list_display = ['title', 'symbolic_id', 'allow_cloning']
    search_fields = ['pk', 'title', 'symbolic_id']


@admin.register(GameURL)
class GameURLAdmin(admin.ModelAdmin):
    def _game(self, obj):
        if len(obj.game.title) < 80:
            return obj.game.title
        return obj.game.title[:80] + '…'

    def _url(self, obj):
        if len(obj.url.original_url) < 80:
            return obj.url.original_url
        return obj.url.original_url[:80] + '…'

    list_display = ['description', '_game', 'category', '_url']
    search_fields = ['pk', 'description', 'game__title', 'url__id']
    list_filter = ['category']
    raw_id_fields = ['game', 'url']


@admin.register(GameAuthorRole)
class GameAuthorRoleAdmin(admin.ModelAdmin):
    list_display = ['title', 'symbolic_id', 'order']
    search_fields = ['pk', 'title', 'symbolic_id']


@admin.register(GameAuthor)
class GameAuthorAdmin(admin.ModelAdmin):
    list_display = ['game', 'author', 'role']
    search_fields = ['pk', 'game', 'author']
    list_filter = ['role']
    raw_id_fields = ['game', 'author']


@admin.register(GameVote)
class GameVoteAdmin(admin.ModelAdmin):
    list_display = ['game', 'user', 'star_rating']
    list_filter = ['star_rating', 'creation_time', 'edit_time']
    search_fields = ['pk', 'game', 'author']


@admin.register(GameComment)
class GameCommentAdmin(admin.ModelAdmin):
    list_display = ['game', 'user', 'creation_time', 'subject', 'is_deleted']
    list_filter = ['creation_time', 'is_deleted']
    search_fields = ['pk', 'subject', 'text']
    raw_id_fields = ['game', 'parent']


@admin.register(InterpretedGameUrl)
class InterpretedGameUrlAdmin(admin.ModelAdmin):
    def _original_url(self, obj):
        ourl = obj.original.url.original_url
        if len(ourl) < 80:
            return ourl
        return ourl[:80] + '…'

    def _game(self, obj):
        g = obj.original.game.title
        if len(g) < 80:
            return g
        return g[:80] + '…'

    list_display = ['_original_url', '_game', 'recoded_url', 'is_playable']
    list_filter = ['is_playable']
    raw_id_fields = ['original']
