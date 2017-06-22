from django.contrib import admin
from .models import (Game, Author, GameTagCategory, GameTag, URL, URLCategory,
                     GameURL, GameAuthorRole, GameAuthor, GameVote,
                     GameComment, RecodedGameURL)


class GameAuthorAdmin(admin.TabularInline):
    model = GameAuthor
    extra = 1


class GameURLAdmin(admin.TabularInline):
    model = GameURL
    extra = 1


class GameAdmin(admin.ModelAdmin):
    inlines = [GameAuthorAdmin, GameURLAdmin]


admin.site.register(Game, GameAdmin)
admin.site.register(Author)
admin.site.register(GameTagCategory)
admin.site.register(GameTag)

admin.site.register(URL)
admin.site.register(URLCategory)
admin.site.register(GameURL)
admin.site.register(GameAuthorRole)
admin.site.register(GameAuthor)
admin.site.register(GameVote)
admin.site.register(GameComment)
admin.site.register(RecodedGameURL)
