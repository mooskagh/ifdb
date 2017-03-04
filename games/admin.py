from django.contrib import admin
from .models import *

admin.site.register(Game)
admin.site.register(URL)
admin.site.register(URLCategory)
admin.site.register(GameURL)
admin.site.register(Author)
admin.site.register(GameAuthorRole)
admin.site.register(GameAuthor)
admin.site.register(GameTagCategory)
admin.site.register(GameTag)
