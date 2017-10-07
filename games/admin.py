from django.contrib import admin
from .models import (Game, PersonalityAlias, GameTagCategory, GameTag, URL,
                     GameURLCategory, GameURL, GameAuthorRole, GameAuthor,
                     GameVote, GameComment, InterpretedGameUrl)


class GameAuthorAdmin(admin.TabularInline):
    model = GameAuthor
    extra = 1


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ['pk', 'title', 'creation_time', 'added_by']
    list_filter = ['creation_time', 'added_by']
    search_fields = ['pk', 'title']

    inlines = [GameAuthorAdmin]


@admin.register(PersonalityAlias)
class PersonalityAliasAdmin(admin.ModelAdmin):
    list_display = ['name', 'pk']
    search_fields = ['pk', 'name']


@admin.register(GameTagCategory)
class GameTagCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'symbolic_id', 'allow_new_tags']
    search_fields = ['name', 'symbolic_id']


@admin.register(GameTag)
class GameTagAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'symbolic_id']
    search_fields = ['name', 'symbolic_id']
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
    search_fields = ['original_url', 'local_url']
    list_filter = [
        'ok_to_clone', 'is_uploaded', 'is_broken', 'creation_date', 'creator'
    ]


@admin.register(GameURLCategory)
class GameURLCategoryAdmin(admin.ModelAdmin):
    list_display = ['title', 'symbolic_id', 'allow_cloning']
    search_fields = ['title', 'symbolic_id']


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
    search_fields = ['description', 'game__title']
    list_filter = ['category']


@admin.register(GameAuthorRole)
class GameAuthorRoleAdmin(admin.ModelAdmin):
    list_display = ['title', 'symbolic_id']
    search_fields = ['title', 'symbolic_id']


@admin.register(GameAuthor)
class GameAuthorAdmin(admin.ModelAdmin):
    list_display = ['game', 'author', 'role']
    search_fields = ['game', 'author']
    list_filter = ['role']


@admin.register(GameVote)
class GameVoteAdmin(admin.ModelAdmin):
    list_display = [
        'game', 'user', 'star_rating', 'game_finished', 'play_time_mins'
    ]
    list_filter = [
        'star_rating', 'game_finished', 'play_time_mins', 'creation_time',
        'edit_time'
    ]
    search_fields = ['game', 'author']


@admin.register(GameComment)
class GameCommentAdmin(admin.ModelAdmin):
    list_display = ['game', 'user', 'creation_time', 'subject', 'is_deleted']
    list_filter = ['creation_time', 'is_deleted']
    search_fields = ['subject', 'text']


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
