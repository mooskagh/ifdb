from django.contrib import admin
from .models import (Competition, CompetitionURLCategory, CompetitionURL,
                     CompetitionDocument, CompetitionSchedule, GameList,
                     GameListEntry)


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ['slug', 'title', 'start_date', 'end_date']
    search_fields = ['title']


@admin.register(CompetitionURLCategory)
class CompetitionURLCategoryAdmin(admin.ModelAdmin):
    list_display = ['symbolic_id', 'title', 'allow_cloning']
    search_fields = ['symbolic_id', 'title']


@admin.register(CompetitionURL)
class CompetitionURLAdmin(admin.ModelAdmin):
    list_display = ['competition', 'category', 'description']
    search_fields = [
        'competition__title', 'url__original_url', 'category__title',
        'category__symbolic_id', 'description'
    ]
    raw_id_fields = ['url']
    list_filter = ['competition', 'category']


@admin.register(CompetitionDocument)
class CompetitionDocumentAdmin(admin.ModelAdmin):
    list_display = ['competition', 'slug', 'title', 'view_perm']
    search_fields = ['competition__title', 'slug', 'title', 'text']
    list_filter = ['competition']


@admin.register(CompetitionSchedule)
class CompetitionScheduleAdmin(admin.ModelAdmin):
    pass


@admin.register(GameList)
class GameListAdmin(admin.ModelAdmin):
    list_display = ['competition', 'title', 'order']
    list_filter = ['competition']


@admin.register(GameListEntry)
class GameListEntryAdmin(admin.ModelAdmin):
    def Competition(self, obj):
        return obj.gamelist.competition

    def List(self, obj):
        return obj.gamelist.title

    list_display = [
        'Competition', 'List', 'rank', 'game', 'datetime', 'comment'
    ]
    list_filter = ['gamelist__competition', 'gamelist__title']
    raw_id_fields = ['game']
