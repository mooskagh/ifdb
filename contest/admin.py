from django.contrib import admin
from .models import (Competition, CompetitionURLCategory, CompetitionURL,
                     CompetitionNomination, CompetitionDocument,
                     CompetitionSchedule, GameList, GameListEntry)


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ['title', 'start_date', 'end_date']
    search_fields = ['title']


@admin.register(CompetitionURLCategory)
class CompetitionURLCategoryAdmin(admin.ModelAdmin):
    list_display = ['symbolic_id', 'title', 'allow_cloning']
    search_fields = ['symbolic_id', 'title']


@admin.register(CompetitionURL)
class CompetitionURLAdmin(admin.ModelAdmin):
    list_display = ['competition', 'category', 'description']
    search_fields = ['competition', 'url', 'category', 'description']


@admin.register(CompetitionNomination)
class CompetitionNominationAdmin(admin.ModelAdmin):
    list_display = ['competition', 'title']
    search_fields = ['competition', 'title']


@admin.register(CompetitionDocument)
class CompetitionDocumentAdmin(admin.ModelAdmin):
    list_display = ['competition', 'slug', 'title', 'view_perm']
    search_fields = ['competition', 'slug', 'title', 'text']


@admin.register(CompetitionSchedule)
class CompetitionScheduleAdmin(admin.ModelAdmin):
    pass


@admin.register(GameList)
class GameListAdmin(admin.ModelAdmin):
    pass


@admin.register(GameListEntry)
class GameListEntryAdmin(admin.ModelAdmin):
    pass
